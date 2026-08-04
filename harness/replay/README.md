# harness/replay/

The controlled-evaluation engine. Takes a sampled task suite per class and replays each task across model tiers under identical harness conditions, with and without the relevant skill attached — producing a 2 × tiers grid per task. This is where the quality-per-tier curves come from.

## What goes here

- Task suite construction: sampling per priority class from real traffic distributions (public in fall, eBay's in spring).
- The replay runner: identical prompts, context, and tooling per tier; the only variables are model tier and skill on/off.
- The **objective track**: hidden-test pass rate where tests exist; compile, lint, and type-check gates as a floor everywhere.

## Inputs

- Task classes from `harness/classifier` (defines the sampling frame).
- Task material from `data/` (public repo tasks in fall).
- The model lineup and rates under test (config, per eBay's actual contracts or proxy pricing).

## Outputs

- `eval_result` records per cell (task × tier × skill), with objective-track outcomes and raw output artifacts, written to `data/`.
- Output **pairs** for tasks without test coverage, handed to `harness/judge`.

## Consumed by

- `harness/judge` — scores the no-test pairs.
- `harness/routing` — objective-track curves.
- `notebooks/` — curve plots with confidence intervals.
