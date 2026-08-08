# harness/classifier/

Classifies agent work along the three taxonomy axes. The classification **unit** (prompt / segment / session) is explicit on every record and deliberately unsettled — see ADR-0002; classifications at multiple granularities over the same traffic are expected. This is the "visibility" deliverable — the task-mix map nobody has today — and the sampling frame every other stage depends on.

## What goes here

- Feature extraction from **content-free metadata only**: diff size, files touched, session length and shape, language, tool-call pattern. Content-based features are gated behind explicit configuration, subject to the customer org's controls.
- The classifier itself (start rules-based, promote to learned once labeled data exists).
- Validation against a human-labeled sample, with agreement statistics published — same standard the judge is held to.

## Inputs

- Session records from `data/` (written by `connectors/telemetry`), validating against `schemas/session.schema.json`.
- Class definitions from `docs/taxonomy.md` (machine-readable form in `schemas/task_class.schema.json`).

## Outputs

- One `task_class` record per classified unit (type × context breadth × risk axes + unit + classifier version + confidence), written to `data/`.

## Consumed by

- `harness/replay` — draws its per-class task samples from these labels.
- `harness/routing` — weights the quality/cost curves by the real task mix.
- `dashboard/` — the usage-distribution views by team, tool, and model.
