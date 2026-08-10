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

## Status (2026-08-10, ADR-0009)

BUILT: rules-0.1.1 (12 documented rules, content-free enforced by test),
segmenter 0.1.0 (reproduces all validatable ADR-0002 segments exactly),
`caliper classify --unit prompt|segment|session|all`. Consumes
`data/extracted/*/sessions.jsonl` + `prompt_units.jsonl`; emits
`data/derived/classes/task_classes.jsonl`.

Agreement vs the human calibration labels: prompt 53.1% / kappa 0.41
(exploratory_qa F1 0.78, ui_verification_loop 0.71); segment 38.5%.
Intent-distinctions (bug-fix vs feature, config-as-goal, `other`) are not
separable from metadata — findings and follow-ups in ADR-0009.
