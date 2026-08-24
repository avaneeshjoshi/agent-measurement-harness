# harness/replay/

## Status (2026-08-10, ADR-0007/0008)

BUILT: `mining.py` (historically-validated bug-fix task mining — hidden tests fail pre-fix, pass at fix), `runner.py` (headless replay across tiers under a locked config, per-cell idempotent appends), versioned pricing (`pricing_snapshots/`, `caliper pricing update`). First real results: 30 commons-lang tasks × 3 tiers (ADR-0007) plus the n_runs=3 variance subset (ADR-0008), records in `data/derived/replay/`.

NOT built yet, described below as design: the skill on/off dimension, classifier-driven per-class sampling (mining is repo-history-based today), and the judge handoff for no-test tasks.

The controlled-evaluation engine. Takes a sampled task suite per class and replays each task across model tiers under identical harness conditions, with and without the relevant skill attached — producing a 2 × tiers grid per task. This is where the quality-per-tier curves come from.

## What goes here

- Task suite construction: sampling per priority class from real traffic distributions (public-repo traffic first; customer traffic once deployed).
- The replay runner: identical prompts, context, and tooling per tier; the only variables are model tier and skill on/off.
- The **objective track**: hidden-test pass rate where tests exist; compile, lint, and type-check gates as a floor everywhere.

## Inputs

- Task classes from `harness/classifier` (defines the sampling frame).
- Task material from `data/` (public repo tasks initially).
- The model lineup and rates under test (config, per the org's actual contracts or proxy pricing).

## Outputs

- `eval_result` records per cell (task × tier × skill), with objective-track outcomes and raw output artifacts, written to `data/`.
- Output **pairs** for tasks without test coverage, handed to `harness/judge`.

## Consumed by

- `harness/judge` — scores the no-test pairs.
- `harness/routing` — objective-track curves.
- `notebooks/` — curve plots with confidence intervals.
