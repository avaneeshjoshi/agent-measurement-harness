# ADR-0002: Classification unit — first empirical comparison (prompt vs segment)

**Date:** 2026-08-07 · **Status:** open question, evidence gathered · **Supplements:** ADR-0001

## Context

The classification unit is unsettled between three candidates: **per-prompt**, **per-segment** (a run of turns pursuing one intent), **per-session**. ADR-0001's "session = task" framing was wrong and is corrected here: task_class v0 now carries a required `unit` enum + `unit_ref`, and classifications at multiple granularities over the same traffic are legal precisely so this comparison can be run. Session-level `segments` were promoted from aspirational to derived, using observable boundaries only (segmenter_version 0.1.0, rules in `docs/conventions.md`).

## Method

All local Claude Code sessions (8 sessions with ≥1 real prompt, Jul–Aug 2026) were hand-labeled at both granularities. **Labels used prompt text** — this is calibration-set methodology (`classifier_version: human-calibration-2026-08-07`); the production classifier must reproduce these labels content-free, and these 97 records (83 prompt, 14 segment) in `data/calibration/unit-comparison-2026-08-07/` are its first validation target. Segment labels were assigned mechanically as the dominant member-prompt label, ties broken by edit volume (rule `segment-dominant-prompt-label-v0`; ties recorded as `status: ambiguous` with alternatives). Task-notification records (automated pings) were excluded from prompt turns. Solo-developer caveat applies throughout: distributions here validate the *instrument*, not enterprise usage.

## Result: the unit choice changes the answer

| task_type | per-prompt (n=83) | per-segment (n=14) |
|---|---|---|
| exploratory_qa | 30.1% | 21.4% |
| ui_verification_loop | 26.5% | 28.6% |
| feature_implementation | 22.9% | 21.4% |
| config_infra | 4.8% | 7.1% |
| other | 4.8% | 7.1% |
| agent_meta_work | 2.4% | 7.1% |
| documentation | 2.4% | 7.1% |
| single_file_bug_fix | 2.4% | **0%** |
| multi_file_refactor | 2.4% | **0%** |
| boilerplate_scaffolding | 1.2% | **0%** |

## Findings

1. **Dominant-label segment classification systematically erases minority classes.** Bug fixes, refactors, and scaffolding exist at prompt level but vanish at segment level — they occur as steps inside segments dominated by something else. A segment-level distribution built this way can never show a class that only occurs embedded. Interpretation: **per-prompt measures the activity mix, per-segment measures the mission mix** — they answer different questions and should probably both be reported rather than one chosen.
2. **The v0 segmenter degenerated to a gap-splitter on this data.** Boundaries fired: session_start ×8, turn_gap ×6, file_set_jump ×0, branch_change ×0, interrupt ×0. Single-branch solo work never changes branch, edits cluster in one directory, and interruptions were absent. The three non-gap rules are untested, not validated — enterprise data (real branching, multi-module repos) is required to exercise them.
3. **n=14 segments is far too small for stable shares** — segment percentages above are directional only. Prompt-level n=83 is marginal.
4. **Structural find — sessions are not disjoint.** An identical prompt appears in two different session logs (a resume/fork artifact). Session-level accounting double-counts unless forks are deduplicated; connectors must handle this.
5. **Taxonomy misfits confirmed at prompt level**: multi-file bug fixes have no slot (`single_file_bug_fix` is too narrow, `multi_file_refactor` is not bug-fixing) — 2 of 4 `other` labels; schema/contract design work is the other 2. Candidate interview questions, matching ADR-0001 §"failed against real sessions".
6. **`exploratory_qa` shrinks 30% → 21% under segmentation** because question bursts collapse into the work they precede. At prompt level, nearly a third of interactions are questions, not code changes — if enterprise traffic looks similar, replay-based evaluation (which assumes a code deliverable) covers well under half of real usage. Worth checking early in the first enterprise/customer data.

## Decisions

- Keep `unit` required and multi-granular storage legal (implemented in task_class 0.1.0).
- Per-session classification was not run: with 8 sessions the answer is visibly degenerate (sessions are multi-mission; see finding 1 amplified). Revisit when session counts justify it.
- `segment-dominant-prompt-label-v0` is retained as a baseline but finding 1 makes it unsuitable as the only segment classifier; alternatives (multi-label segments, embedded-task extraction) are interview-informed future work.
