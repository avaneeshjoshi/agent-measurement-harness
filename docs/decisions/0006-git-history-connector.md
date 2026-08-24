# ADR-0006: Git-history connector — local production signals, schema 0.2.0, first outcome-side run

**Date:** 2026-08-09 · **Status:** accepted

## Context

The extractor (ADR-0004/0005) covers the activity half of the architecture. This ADR
records the first outcome-side component: `connectors/git_history.py` + `caliper
signals`, computing production_signal records from LOCAL git repos only (no forge
APIs), for exactly the repos the extracted sessions reference.

## Decisions

1. **Repo discovery follows the sessions.** Candidate working directories are re-read
   from the same sources the session extractor uses (Claude Code `cwd`, Codex
   `session_meta.cwd`, Cursor workspace `fsPath` + `trackedGitRepos`), resolved to git
   toplevels. Hashing each cwd with the extraction salt reproduces the sessions'
   `project_ref` — the ADR-0005 §3 join key, now exercised in both directions.
2. **Survival is blame-based and horizon-snapshotted.** For commit C at horizon h: take
   the last HEAD-lineage commit before `authored_at + h`, blame each file C touched,
   count lines still attributed to C. Blame results are cached per (snapshot, file).
   `not_yet_measurable` when the horizon hasn't elapsed; `unmeasurable` when C added no
   lines (pure deletions, binary) — absence encoded, never conflated with 0%.
3. **Rework = changed-OR-deleted within 14 days.** Blame cannot distinguish a line
   edited from a line deleted; `lines_reworked = lines_added − surviving@14d` and the
   conflation is documented rather than hidden.
4. **Reverts from explicit markers only** (`This reverts commit <sha>`, abbreviated
   shas handled). No content-similarity guessing — same rule as attribution.
5. **Attribution is evidence-only, three-way**: Cursor `scored_commits` with populated
   tab/composer/human counts → `known` (which includes **known-human**, ai_fraction 0 —
   'known' describes evidence completeness, not AI-ness); a scored row with null counts
   → `partial/vendor_tracking_db`; a `Co-Authored-By` trailer naming an AI tool →
   `partial/self_report`; otherwise `unknown/none`. Never from code content.
6. **production_signal schema 0.1.0 → 0.2.0**: adds required `provenance`
   (connector_version, content_hash, repo_path, head_sha) — same traceability contract
   as session 0.3.0+. `content_hash` covers the computed payload, so the store's
   idempotency works: unchanged repo state → byte-identical records; a horizon
   maturing or new attribution evidence → clean update.
7. **Layering note**: this connector computes what `harness/signals` will own. The
   local-git read and the signal math live together until the GitHub connector forces
   the normalize/compute split; recorded here so it is a decision, not drift.

## First real run (2026-08-09)

7 repos discovered from session references, 88 commits (2025-07-02 → 2026-08-09),
0 validation failures, ~6 min wall (blame on multi-MB generated artifacts dominates).
Attribution: 3 known (of which 1 known-AI, 2 known-human), 53 partial
(31 vendor rows without counts, 22 AI co-author trailers), 32 unknown.

Instrument findings, recorded for the methodology:

1. **Line-weighted survival without artifact filtering is meaningless.** Overall
   line-weighted 30d survival reads 6.5% — driven entirely by one 3,013,346-line
   generated-artifact commit with 0% survival. Per-commit median is 99.3%. Both
   numbers are true; only one describes typical work. Signals reporting must either
   exclude generated files (lockfiles, build artifacts) or lead with per-commit
   distributions. Deferred, not silently patched.
2. **`known` is symmetric evidence** — 2 of 3 fully-scored commits were known-HUMAN.
   Reporting splits must be by ai_fraction, not by attribution status alone.
3. **Rework split by attribution** (solo data, tiny n, association only): partial-AI
   36.6% (15/41) vs unknown 54.5% (12/22). Not evidence of anything yet except that
   the split is computable on real data.
4. **Zero reverts and zero PR merge patterns across all 7 repos** — solo direct-push
   workflow. Review friction and revert linkage are structurally invisible in solo
   local data (the schema's `review: null` case, confirmed); they need multi-person
   repos to validate.
5. **Session→repo join rates** (the point of the exercise): claude_code 20/21 (95%),
   codex 17/21 (81%), cursor 26/43 (60%). Cursor's gap: workspaces that aren't git
   repos and deleted directories. Codex misses: throwaway `Documents/Codex/...`
   scratch dirs and `New project` — real sessions with no repo to trace to.
   Session-window commit joins (≥1 commit authored inside the session's wall-clock
   window): claude_code 19%, cursor 23%, codex 19% — low largely because solo commits
   land after the session's last activity timestamp. Trace-layer implication: joining
   needs commit-time slack after session end, not just containment.

## Known v0 limitations (documented, not patched)

Blame does not follow renames (rename counts as line death). Survival measured against
HEAD lineage only. Rework conflates edit and delete. Generated-file skew per finding 1.
`review` is always null locally. Commit `branch` is null — local git does not record
which branch a commit was authored on.

## Postscript (2026-08-24): blame-failure fabrication pathway — found, fixed, measured

The off-machine audit for ADR-0014 found that a FAILED `git blame` (timeout,
shallow clone, git error on an existing path) recorded
`surviving_fraction: 0.0, status: "measured"` — a fabricated confident zero
on the report's lead table, present since this ADR's first run. A path
absent at the snapshot (genuinely dead lines) and a blame that errored were
conflated into the same empty result.

Fix: the two cases are now distinguished (`cat-file -e` on the snapshot
path); a true blame failure records `status: "unmeasurable"` and a
`null` fraction — never a zero — and a failed 14-day-rework blame records
`rework: null`. Regression test:
`tests/test_git_signals.py::test_blame_failure_is_unmeasurable_never_zero`.

Impact on existing records, measured before correction (pre-fix records
snapshotted, then a full re-run, then a three-way diff): of 88 pre-fix
commits, **0 were affected by the bug** (no `measured 0.0` flipped to
`unmeasurable`), 37 changed through legitimate drift (horizons maturing,
repos moving on, new attribution evidence), 51 were byte-unchanged, and 146
new commits entered since the 2026-08-09 run. **No published figure in this
ADR changes** — the 6.5% line-weighted / 99.3% per-commit-median finding and
the per-repo medians stand. The pathway simply never fired on this machine's
repos (no shallow clones, no blame timeouts); it remains real for foreign
machines, which is why it gated shipping (ADR-0014).

## Postscript 2 (2026-08-24): ground-truth verification — known answers and a hand audit

The durability signals had only ever run on the author's repos with no
ground truth. Two verifications now exist:

**Known-answer tests** (`tests/test_git_signals.py`, the `known_answer_repo`
fixture): six constructed events with exact expected values — an untouched
commit (6/6, 1.0), a commit rewritten 8 days later (rework 4 of 10, the
rewriting sha listed), a real revert whose marker carries an **abbreviated**
sha (the previously untested match path), a commit too young to measure
(`not_yet_measurable`, never 0%), a file deleted entirely before the
snapshot (`measured 0.0` via the cat-file-absent path — deletion is a
measurement), and a 50,000-line generated lockfile that measures like any
code, with the line-weighted-vs-per-commit skew asserted as an executable
fact (line-weighted 0.9998 vs per-commit mean 0.6 in the fixture). Twelve of
thirteen assertions passed on first contact; the one failure was an error in
the hand-computed expectation (the rewriter's own record was omitted from
the median), not in the tool.

**Hand audit of ten real commits** (independent script, raw git only, no
caliper imports): survival@30d and rework agreed **exactly** on 9/10 —
including the 3,013,346-line generated-artifact commit (8 surviving lines,
byte-exact) and a 6,412-line commit (6,020 surviving, 392 reworked). The
single divergence was the hand script's own precedence error: for a
zero-lines-added commit younger than its horizon, the tool says
`unmeasurable` (correct — zero added lines can never be measured at any
age) where the naive check said `not_yet_measurable` (which would promise a
measurement that can never come). The tool's ordering — `lines_added == 0`
dominates age — is deliberate and now documented here.

Two nuances recorded:
- **`known` attribution counts are vendor-scoped, not numstat-scoped.** A
  commit with `lines_added 546` carried vendor counts (0 ai / 328 human)
  because Cursor scores only the lines it observed in-editor; the tool
  reports the vendor's evidence verbatim, and the two denominators must not
  be compared as if equal.
- **Revert linkage is fixture-verified only**: zero revert commits exist in
  any of the nine real repos analyzed (solo direct-push history, as §First
  real run predicted), so the real-world path remains exercised solely by
  the known-answer fixture until multi-person repos arrive.
- Minor latent inconsistency, recorded not fixed: the rework path's
  no-snapshot branch assumes all lines survived where survival's equivalent
  says `unmeasurable`; it is dead code in practice (the commit itself is
  always a snapshot candidate) but should be aligned if ever touched.

## Postscript 3 (2026-08-24): the generated-file deferral is implemented

Finding 1's "exclude generated files or lead with per-commit distributions —
deferred, not silently patched" is now implemented as ADR-0015: a versioned
pattern list plus `.gitattributes linguist-generated`, filtered counts
rendering with the excluded delta stated, and a sixth absence word
(`excluded_generated`) for commits that touched only generated files. The
6.5%-line-weighted figure this ADR reported was the unfiltered world; the
recomputed figures live in ADR-0015's re-run table. This ADR's numbers stand
as what the unfiltered instrument measured at the time.
