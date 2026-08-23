# ADR-0011: Continuous collection — data home, scheduled extraction, gap detection, drift canaries

**Date:** 2026-08-23 · **Status:** accepted · **Elevates:** ADR-0009's retention finding and ADR-0005's format-drift finding from documented limitations to product requirements

## Context

Two findings gate everything downstream of collection:

1. **Retention is ~days.** A raw Claude Code log present behind the 2026-08-07
   calibration set was gone by 2026-08-10 (ADR-0009 §infrastructure-1). Manual
   extraction against that window loses data permanently; backfill is lossy by
   construction. PROGRESS.md carries this as the highest-leverage gap.
2. **Format drift degrades coverage silently.** `additionalProperties: false`
   catches *added* fields loudly, but a vendor *removing* a field (Codex's
   `session_meta.git` block, ADR-0005 §4) just sinks coverage — extraction
   continues correctly with absent fields and nothing alerts.

This ADR records the design that fixes both: a scheduled extractor with an
activity gate, gap detection against a named retention constant, drift
canaries, opt-in content sidecars, and — as a precondition — moving collected
data out of the repo.

## Decision 1: data home is `~/.caliper/`, and the move is a migration

Extracted traffic is **user data, not repo data**: it must survive without a
git tree present, and a background job must not write into a repo path. The
default output tree moves from `<repo>/data/extracted/` to
`~/.caliper/extracted/` (job logs under `~/.caliper/logs/`).

- **Why `~/.caliper` and not `~/Library/Application Support`:** it matches the
  convention of the exact tools Caliper reads (`~/.claude`, `~/.codex`,
  `~/.cursor`), it is identical on Linux when the systemd port lands, and it
  keeps paths short in docs and plists. `CALIPER_HOME` overrides the root
  (tests use this); `--data-dir` still wins where offered.
- **Migration, not a default flip.** Real data exists (295 sessions, 88
  signals, manifests, the report, `.salt` — and losing the salt breaks every
  future join to existing history). On CLI start, a populated legacy tree is
  moved to the new home: same-volume rename; on cross-device fallback,
  copy → verify (`.salt` bytes + file count) → only then remove the source,
  and a failed verify cleans the partial target and leaves the legacy tree
  untouched. **A populated target is never overwritten** — both-populated
  prints a notice and uses the new home. Idempotent by construction.
- Committed evidence stays in the repo: `data/derived/`, `data/calibration/`,
  `data/fixtures/` are citable repo data. The `.gitignore` rule for
  `data/extracted/` remains as a guard for stragglers.
- **`~/caliper-eval/` stays where it is.** It is a disposable eval workspace —
  large mined git clones and run trees, rebuildable via `caliper replay mine`.
  The canonical task list and predictions are already committed
  (`data/derived/replay/tasks.jsonl` — verified byte-identical to the
  workspace copy — and `predictions.json`), so ADR-0007/0008 reproducibility
  does not depend on that tree.
- Known consequence: the CLI still needs the repo clone at runtime (schemas
  are not packaged; `repo_root()` resolves through the editable install).
  Packaging schemas via importlib.resources is future work, recorded here.

## Decision 2: launchd-scheduled extraction, hourly, activity-gated

Installed during `caliper setup` (or `caliper schedule install`) as a launchd
user agent `dev.caliper.extract` at `~/Library/LaunchAgents/`:

| Key | Value | Why |
|---|---|---|
| `ProgramArguments` | absolute `caliper` path (resolved at install; fallback `python -m cli.main`) + `extract --scheduled` | launchd has no useful PATH; the binary's shebang is absolute |
| `StartInterval` | `3600` | hourly while awake; launchd does **not** fire during sleep and coalesces a missed interval into one run on wake — the "4am on a closed laptop" case is solved at this layer |
| `RunAtLoad` | `true` | login catch-up; the activity gate makes it a no-op when idle |
| `ProcessType` / `LowPriorityBackgroundIO` / `Nice` | `Background` / `true` / `10` | never compete with the user's own agent sessions |
| `StandardOutPath`/`StandardErrorPath` | `~/.caliper/logs/extract.log` | failures visible, not silent; idle ticks log one line (~10 KB/yr), so no rotation machinery |
| no `KeepAlive` | — | a failing job must not respawn-loop |

**Activity gate = watermark.** The scheduled run stat-scans discovered
artifacts first (including SQLite `-wal`/`-shm` siblings — Cursor's WAL can
absorb hours of writes without touching the main DB's mtime). Nothing newer
than `watermark[source] − WATERMARK_SLACK_S` → update liveness state, print
one line, exit — validators and stores never load. Otherwise extract with the
watermark as an mtime filter, so runs are O(new). Skipping an unchanged
artifact is safe: the store merges from existing records.

**Daily full pass.** Incremental runs have one known correctness hole:
Claude Code fork detection (`finalize()`, ADR-0004 §fork_of) groups only the
*emitted* batch — a fork whose original's file didn't change is emitted alone
and gets `fork_of: null`. The scheduled runner therefore ignores the
watermark once per `FULL_PASS_INTERVAL_S` (24 h), re-deriving fork families
from the full file set. For the heal to actually write, `SessionStore.upsert`
gains a record-equality condition: "unchanged" now also requires the computed
record to equal the stored one (ignoring `extracted_at`) — previously a
changed derived field under an unchanged source hash was silently discarded.
Fork-link staleness is thus bounded at <24 h; recorded as a limitation, not
hidden.

**Concurrency.** One `fcntl.flock` (non-blocking) on
`~/.caliper/extracted/.extract.lock`, held by scheduled *and* manual runs.
The kernel releases it on process death — no stale-pid logic. This also
closes the pre-existing hazard that `content.jsonl` appends are not atomic
under concurrent writers. A scheduled run that finds the lock held exits 0
("skip: lock held"); a manual run warns and exits 1.

**Linux (not built):** systemd user timer — `OnUnitActiveSec=1h`,
`Persistent=true` for wake catch-up, `Nice=10` + `IOSchedulingClass=idle` as
the non-interference equivalents. macOS-only until someone needs it.

## Decision 3: gap detection with a named constant

`RETENTION_OBSERVED_DAYS = 3` (`cli/health.py`) — the ADR-0009 observation,
cited at the constant, never inlined as a magic number. Per source, when
`now − last_covered` exceeds it, the **next interactive CLI invocation**
opens with a loud warning naming the source and the window
(`last_covered → now − retention`), phrased "activity in this window **may
be** permanently lost" — rotation means we cannot prove what existed, and the
absent-is-not-zero rule applies to warnings too — and stating this is the
known retention limitation (ADR-0009), not a bug.

- **An idle tick counts as coverage.** A gated no-op verified nothing new
  existed, so it advances `last_covered`; otherwise a quiet week would fire a
  false loss alarm. A source reported "not present on this machine" also
  advances — there is nothing to lose.
- Suppressed during `caliper setup` (it is about to backfill) and inside
  `--scheduled` runs (it *is* the collector; the gap still lands in its log).
- No prior coverage at all → no warning (a fresh clone is not a gap).
- State lives in `~/.caliper/extracted/.collection.json`; detection falls
  back to scanning manifest timestamps so pre-state users are warned too.

## Decision 4: drift canaries

Two families, because scheduled runs often emit 1–3 records and per-run rates
would false-positive constantly:

- **Count canaries** (per source, after every extract): unknown-shape count
  and skip rate vs a baseline pooled over the last `CANARY_BASELINE_RUNS`
  (20) manifests **with matching connector+schema versions** — a version bump
  re-emits everything and must reset the baseline, not trip it. Alarm iff
  `count ≥ CANARY_MIN_EVENTS` (5) **and** the Laplace-smoothed rate
  `(x+1)/(n+2)` is ≥ `CANARY_RATE_MULTIPLIER` (3×) the pooled baseline rate.
  The absolute floor kills "one weird record in a three-record run".
  This required adding the unknown-shape counters in the first place —
  plugins previously ignored unrecognized record types silently. Codex seeds
  a curated `_KNOWN_IGNORED` set (event/payload types Caliper already
  deliberately ignores) so day one isn't all noise; additions to that set are
  connector maintenance per ADR-0005 §4.
- **Field-coverage canary** (the removed-field case): computed over
  `sessions.jsonl` trailing windows keyed by `started_at` — recent
  `COVERAGE_RECENT_DAYS` (7) vs the prior `COVERAGE_BASELINE_DAYS` (28) —
  with depth-2 dotted-key flattening. Only fields with baseline coverage ≥
  `COVERAGE_BASELINE_FLOOR` (0.8) and both windows above minimum n (10/30)
  are eligible; alarm on an absolute drop ≥ `COVERAGE_DROP_ABS` (0.3). This
  catches exactly the ADR-0005 Codex-git-block failure.

Alarms are written into the run manifest **and** persisted to
`pending_alarms` in state — the persistence is load-bearing, because a
scheduled run's stdout goes to a log nobody reads; the next interactive
invocation surfaces them. Alarms self-clear: each run replaces the alarms for
the sources it processed, so a condition that stops firing disappears without
an ack workflow. Thresholds are v0 judgment calls; retuning them requires a
note here, not silent edits (same rule as classifier thresholds, ADR-0009).

## Decision 5: content sidecars are an explicit, local, forward-only opt-in

Scheduled runs write content sidecars only when the user opted in during
setup (state `include_content`, default **off**; non-interactive setup never
enables it). The trust screen states what it enables in plain terms: prompt
text written to `~/.caliper/extracted/*/content.jsonl`, local only, never in
session records — and the trust screen's "never reads" bullet is amended so
it cannot become false the moment someone opts in. Rationale: this corpus is
what the classifier's teacher-labeling follow-up (ADR-0009) needs, and it can
only accumulate from the moment it is switched on.

## Decision 6: Full Disk Access is a choice the user makes, never an assumption

Extraction needs no TCC permission — agent logs are dotfiles plus Cursor's
Application Support tree. TCC bites when **signals** reads git repos under
`~/Documents`, `~/Desktop`, `~/Downloads`, or iCloud from a background
context. `caliper schedule install` therefore:

1. Detects whether session-referenced repo paths are TCC-protected
   (path-prefix heuristic — recorded as a heuristic, not a guarantee).
2. If so, states plainly that scheduled signals needs Full Disk Access for
   the Python binary **and that FDA grants read access to everything on the
   machine, not just these repos** — then offers both paths: grant it
   (mode `full`: hourly extract + signals in the daily full pass) or install
   **extraction-only** (mode `extract_only`: no special permission; signals
   stays a manual, interactively-authorized command).
3. **Verifies from the job's own context** — `launchctl kickstart`, then the
   run's own self-check (source roots readable, data dir writable, sample
   repo paths readable in full mode) reported back through state. A job that
   installs green and silently collects nothing is the worst failure mode;
   every scheduled run re-runs the self-check and failures become pending
   alarms + a red `schedule status`.

**Tradeoff, recorded:** FDA is a broad grant accepted for now because it is
the only way a launchd job reads protected repo paths without per-folder
prompts that background jobs cannot trigger. Narrower mechanisms — per-repo
hooks, or keeping signals interactive-only forever — are future work; this
line is the marker to revisit.

## Consequences

- Continuous collection closes the retention gap **forward from
  installation**; everything before enablement is already lost (stated in
  PROGRESS.md, which retires the "extraction is manual" gap to that residual
  form).
- The plist pins an absolute interpreter path: a Python upgrade orphans it.
  `schedule status` checks the path and warns; no KeepAlive means failures
  are visible in `launchctl print` rather than respawn-looping.
- Manifest volume grows (~24/day on active days). Accepted; pruning is future
  work — deliberately not added silently.
- The repo clone must exist for the scheduled job (`WorkingDirectory`,
  schemas). Deleting the clone strands the job → `schedule status` warns on a
  missing target; packaging is the real fix, later.
- New tests cover migration (salt/ref preservation), gap thresholds, canary
  triggers (including the version-bump non-trigger and small-n guards),
  watermark filtering, fork-link healing, lock contention, plist generation,
  and the TCC/verification flows — all pure-logic or injectable-runner tests;
  CI never touches launchctl.

## Postscript (2026-08-23): the retention constant was wrong — corrected by measurement

Challenged the same day it shipped, `RETENTION_OBSERVED_DAYS = 3` did not
survive contact with the filesystem:

- Raw Claude Code logs on this machine span **24.9 days** (205 files; 199 of
  them 7–30 days old). Codex rollout files go back **193 days**; Cursor's
  databases are cumulative. Neither Codex nor Cursor rotates at all.
- The definitive measurement, from extraction provenance: every session
  started 2026-07-09 has a **deleted** raw file (45+ days old at
  measurement); every session from 2026-07-25 on **survives** (29 days old).
  The deletion boundary sits at ~30 days — exactly Claude Code's
  `cleanupPeriodDays` default, which is unset on this machine.

So ADR-0009's observation (a log present Aug 7, gone by Aug 10) was real but
misread: that log was from early July and crossed the **30-day** cleanup
boundary in that window. Generalizing it to "retention ≈ 3 days" was an n=1
over-generalization — the exact failure mode this product exists to catch,
committed inside its own instrument. Recorded as a finding, not silently
retuned.

**Corrected model (implemented in `cli/health.py`):**

- Per-source, per-machine windows, derivation stated in every warning:
  `claude_code` = the user's actual `cleanupPeriodDays`
  (`CLAUDE_CLEANUP_DEFAULT_DAYS = 30` only as fallback — someone at 7 has a
  real 7-day window; someone at 365 should barely ever be warned);
  `codex` and `cursor` = non-rotating.
- Three gap kinds with distinct wording: **loss** (lapse past the rotation
  window — red, names the may-already-be-rotated span), **at_risk** (lapse
  past `RETENTION_WARN_FRACTION = 0.5` of the window — yellow, names the
  collect-before date), **coverage** (non-rotating source stale past
  `COVERAGE_GAP_DAYS = 14` — "nothing is lost, the picture is stale").
- The urgency argument for continuous collection weakens (30 days, not 3)
  but does not vanish: rotation is real, user-configurable downward, and a
  laptop that sits closed for a vacation plus a short `cleanupPeriodDays`
  still loses history silently without the scheduler.
