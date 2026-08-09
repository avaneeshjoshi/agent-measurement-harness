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
