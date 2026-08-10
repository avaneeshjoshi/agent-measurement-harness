# ADR-0008: Variance subset (n_runs=3) — the fable/sonnet gap dissolves, the haiku cliff holds; first routing_policy record

**Date:** 2026-08-10 · **Status:** accepted · **Records:** `data/derived/replay/eval_results_variance.jsonl` (90), `data/derived/routing/routing_policies.jsonl` (1)

## Context

ADR-0007 gated any routing_policy record on variance data: the headline "mid tier
matches frontier" rested on 20 vs 19 solved at n_runs=1. This run settles it: 10 tasks
× 3 tiers × 3 repetitions (90 runs, $73.49 list-equivalent), same locked config.
Selection deliberately spans the range: all six tier-disagreement tasks from the full
run (the cells the gap claims rest on), two all-solved anchors, two all-failed anchors.
**The subset is gap-enriched by construction — its per-tier rates are not population
estimates**; the paired comparisons are what it is for.

## Results (solved out of 3)

| Task (churn) | fable | sonnet | haiku |
|---|---|---|---|
| unescapeCsv (2) | 3/3 | 3/3 | 3/3 |
| lookup translator (2) | 3/3 | 3/3 | **3/3** |
| StopWatch NPE (3) | **2/3** | 0/3 | 0/3 |
| LANG-1778 (5) | **1/3** | 3/3 | 0/3 |
| getMatchingMethod (5) | 3/3 | **1/3** | 0/3 |
| LocaleUtils (13) | 0/3 | 0/3 | 0/3 |
| subarray (18) | 3/3 | 3/3 | **2/3** |
| WordUtils.wrap (21) | **0/3** | 0/3 | 0/3 |
| TypeUtils SO (27) | 0/3 | 0/3 | 0/3 |
| LANG-1816 (28) | 0/3 | 0/3 | 0/3 |

## Findings

1. **26/30 cells are deterministic; flakiness lives exactly where the tiers seemed to
   differ.** All four flaky cells are mid-difficulty discriminating tasks. The easy
   tasks always solve, the hard tasks always fail, and the n=1 "tier disagreements"
   were substantially re-rolls of coin flips.
2. **n=1 misclassified 2 of 30 cells outright**: haiku's lookup-translator was ✗ at
   n=1 but is 3/3 here; fable's WordUtils.wrap was ✓ at n=1 but is 0/3 here. Single-run
   grids are directional, as ADR-0007 warned — now quantified (~7% of cells flipped
   completely on this subset).
3. **The fable/sonnet gap does not survive.** 15/30 vs 13/30 runs; per-task sign test
   2 fable-favoring, 1 sonnet-favoring, 7 tied (p=1.0); paired run-level permutation
   p=0.645. The tier wins point in both directions (StopWatch and getMatchingMethod
   favor fable; LANG-1778 favors sonnet) and roughly cancel. **Power caveat:** n=10
   tasks cannot exclude a modest true gap; what it excludes is the confident reading
   of the full run's 1-task difference as signal.
4. **The haiku cliff survives.** Sonnet 13/30 vs haiku 8/30, paired permutation
   p=0.026 — significant even on a subset where haiku was handed its best cells and
   the hard tasks defeat everyone equally. Combined with the full run (19 vs 11 of
   30), the mid→small quality drop is real.
5. **The LANG-1816 timeout edge did not recur** — all three sonnet reps failed within
   the turn budget. The full run's green-tree-at-timeout was a one-off.

## Decision: first routing_policy record (rp-0001, status=draft)

The evidence supports one recommendation with two clauses, emitted as
`data/derived/routing/routing_policies.jsonl`:

- **Route verified bug-fix work (tests exist) to the mid tier** (sonnet-5), escalate
  to frontier on failure. Quality indistinguishable from frontier across both runs;
  list-price cost 42% of frontier per task ($0.53 vs $1.27 full-run means).
- **Do not route below mid.** The small tier loses 8 of 30 tasks against mid at n=1
  and the gap is statistically significant at n=3.

**Status is draft, deliberately.** Everything downstream must carry these limits:
replay-only evidence (triangulation: single_track_only — production signals exist for
local repos but are not yet linkable to this task class); public-repo tasks with
training-data contamination (gaps meaningful, absolutes not); provisional taxonomy
(0.1.0-provisional, class = single_file_bug_fix); task-mix weight from the tiny
hand-labeled calibration set (2/83 prompts), not a classifier; no harness/routing
package yet — this record was assembled manually against the schema
(router_version: manual-adr-0008). Promotion to `proposed` requires: enterprise or
uncontaminated task sources, the classifier providing a real mix weight, and
production-signal triangulation.
