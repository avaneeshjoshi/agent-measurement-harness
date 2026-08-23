# notebooks/

**Design README only — no notebooks exist yet (see [`PROGRESS.md`](../PROGRESS.md)).** Curve figures produced so far came from the eval pipeline and ADRs directly. Everything below is the intended role of this directory.

Exploratory analysis. Where the curves get plotted, the tracks get triangulated, and report figures come from.

## What goes here

- Curve analysis: quality-per-tier and cost-per-tier plots with confidence intervals, per task class.
- Track triangulation: replay/judge results vs. production signals, with disagreements surfaced explicitly.
- Usage-study analysis: survey + interview data → the task-mix map.
- ROI projection: curves weighted by task mix at the org's model lineup and prices.
- Calibration analysis: judge–human and classifier–human agreement statistics.

## Rules

- Notebooks **read** schema-conforming artifacts from `data/`; they never produce records other components depend on. Anything a notebook computes that the pipeline needs gets promoted into `harness/` as tested code.
- Any figure that ships in a report or the dashboard must be regenerable from a committed notebook + versioned `data/` artifacts.
