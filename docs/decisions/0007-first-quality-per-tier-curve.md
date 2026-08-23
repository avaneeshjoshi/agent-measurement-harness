# ADR-0007: First quality-per-tier curve — 30 real bug-fix tasks × 3 tiers on commons-lang

**Date:** 2026-08-10 · **Status:** accepted · **Records:** `data/derived/replay/eval_results.jsonl` (90 records, eval_result 0.3.0) *(evidence relocated to `data/evidence/adr-0007/`, ADR-0012)*

## Context

First real run of `harness/replay`: 30 mined-and-validated bug-fix tasks from Apache
commons-lang history (ADR-style validation: hidden tests fail at pre-fix, pass at fix),
each replayed from a history-free pre-fix snapshot by Claude Code headless under
identical conditions across three tiers. Total spend $61.08 (pilot included), ~3.1h
wall with 3-way parallelism (plus one harness-cap interruption, below).

## Setup (locked before launch)

Tiers claude-fable-5 / claude-sonnet-5 / claude-haiku-4-5; identical prompt
(`replay-prompt-0.1.0`), workspace, `--max-turns 60`, 30-min wall timeout;
WebSearch/WebFetch disabled; hidden tests overlaid only at scoring; turn-capped or
timed-out runs scored FAILED (no retry); n_runs=1. Predictions were pre-registered
before any result (`~/caliper-eval/predictions.json`).

## Results

| Tier | Solved | Predicted | Total cost | $/solved task | Mean turns | Turn-capped |
|---|---|---|---|---|---|---|
| fable-5 (frontier) | **20/30 = 67%** | 89% | $38.19 | $1.91 | 11.1 | 0 |
| sonnet-5 (mid) | **19/30 = 63%** | 75% | $15.85 | $0.83 | 14.5 | 0 |
| haiku-4.5 (small) | **11/30 = 37%** | 50% | $4.46 | $0.41 | 14.5 | 0 |

## Findings

1. **The curve is not linear — it has a cliff, and the cliff is below the mid-tier.**
   Frontier→mid costs 1 task out of 30 (67%→63%) while cutting spend 58%. Mid→small
   costs 8 tasks (63%→37%) for the remaining savings. On this task class, the routing
   implication is direct: downshifting frontier→mid is nearly free; downshifting
   mid→small is not. A two-point fable/haiku comparison would have missed this
   entirely — the middle point carried the whole answer.
2. **Failure sets nest.** Haiku's 11 solves are (almost) a subset of sonnet's 19,
   which nearly coincide with fable's 20 (sonnet solved one task fable missed, missed
   two fable got). Tiers mostly fail on the same tasks, harder tasks — consistent with
   a difficulty ordering, not with tiers having different skills.
3. **Difficulty gradient confirmed, and it's churn.** Haiku's failed tasks have churn
   median 14 vs 3 for its solves — the pre-registered prediction ("haiku breaks on
   high-churn") is confirmed. The multi-file half of the prediction was untestable:
   only 1 of 30 mined tasks was multi-file (all tiers failed it).
4. **7 tasks defeated every tier** (all clustered in the top half of the churn
   distribution). Some are genuinely hard; some may be under-specified — a one-line
   commit subject is a thin bug report. Instrument follow-up: enrich problem
   statements from JIRA and re-run the all-fail tasks before treating them as a
   capability ceiling.
5. **Per-solve cost misleads across tiers.** Haiku's $0.41/solve looks best, but its
   solves are the easy subset every tier also solves. $/solve is only comparable on
   the intersection of solved tasks; the honest summary is the (quality, total cost)
   pair per tier.
6. **All predictions were ~15-20 points optimistic in absolute terms**, but the
   predicted ordering and the sonnet-close-to-fable intuition were right. Given
   contamination pushes absolute rates UP, real-world uncontaminated performance on
   fresh bugs is likely lower still — gaps remain the reliable signal.

## Caveats (these travel with every use of the numbers)

- **Memorization contamination:** commons-lang is in every tier's training data;
  several fix commits are public. Absolute pass rates are optimistic. This affects
  all tiers roughly equally, so tier-to-tier GAPS are the meaningful quantity;
  absolute rates must not be quoted as capability claims.
- **n_runs=1:** single-run pass/fail is directional, not precise. Observed concretely:
  the pilot's haiku run on getMatchingMethod hit the 60-turn cap; the full-run repeat
  of the same cell failed without capping. Variance estimation (n_runs=3 on a subset)
  is the designated follow-up before any routing_policy record cites these curves.
- **One scoring edge:** sonnet's LANG-1816 run timed out at 30min wall with a tree
  that passed all 356 hidden tests. Scored FAILED per the locked policy (completion is
  part of the deliverable). Recorded here because it flatters fable's gap by one task.
- **One task's statement was sanitized** (test-narrating commit body) and 3 others had
  test-referential lines stripped; zero hidden-test references remained at launch.
- The batch was killed at 74/90 by a ~1h background-process cap and resumed
  cell-exactly; records span two run_ids. Per-cell idempotent appends made the resume
  lossless.

## Decisions

- eval_result 0.3.0 (turn_capped/turns/wall_seconds; task_solved aggregate) is the
  reporting shape for replay.
- The quality-per-tier curve from this run is Caliper's first demo artifact; the
  task-level grid (30×3) is the seed for a starter routing policy — but no
  routing_policy record is emitted until n_runs≥3 variance data exists (finding 6 +
  the n_runs caveat gate it).

## Postscript (2026-08-10): sonnet-5 pricing correction

The LiteLLM cross-check (pricing snapshot 2026-08-10-litellm) surfaced that the
hand sheet priced claude-sonnet-5 at post-intro list ($3/$15) while the billed
rate through 2026-08-31 is the intro rate ($2/$10). Convention adopted:
**cost figures use the billed rate at run date.** Every sonnet-5 rate scales by
exactly 2/3, so this run's sonnet figures restate as: total $15.85 → **$10.57**,
per-solve $0.83 → **$0.56** — sonnet at **28% of fable's cost** (was 42%),
strengthening the mid-tier conclusion. Fable and haiku figures are unchanged (no
promotional rates). The eval_result records are NOT rewritten — they carry
pricing_as_of 2026-08-09 and remain reproducible under that sheet; this
postscript and the updated demo artifact are the corrected citations.
