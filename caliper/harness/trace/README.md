# harness/trace/

**Design README only — no code exists yet (see [`PROGRESS.md`](../../PROGRESS.md)).** The contract (`schemas/trace_event.schema.json`) is drafted; zero trace records exist anywhere. Everything below is the intended design.

The value-traceability layer: connects agent activity to the work the organization intended to deliver. Technical quality says "the output was good"; this layer answers "was it worth doing."

## What goes here

- Linkage logic for the chain: **agent session → generated change → commit/PR → Jira ticket or initiative → deployment → available downstream outcome**, using the identifiers each system exposes (branch names, PR references, ticket keys, deploy metadata).
- The value dimensions per traced item, kept as **separate fields, never collapsed into a single score**: business/roadmap priority, engineering category, estimated complexity, production criticality and risk, delivery status, review effort/rework/reversions, downstream outcome, and strength + confidence of the AI contribution.
- Explicit handling of broken chains: where identifiers or links are missing, the trace records *where* the chain broke — that map of lost linkages is itself a deliverable.

## Inputs

- Session records, Git/PR history, and ticket metadata from `data/` (via `connectors/` — synthetic Jira and public GitHub for now).
- `schemas/trace_event.schema.json` — the integration contract this package implements.

## Outputs

- `trace_event` records written to `data/`.

## Consumed by

- `harness/routing` — priority/risk context for routing decisions (a production-critical fix may justify a stronger model even when the task type looks routine).
- `dashboard/` — the decision buckets (high-priority work with strong AI contribution, high spend on abandoned work, etc.).

## Rules

- Jira priority and story points are **context, not value**. The customer org defines which combinations constitute a meaningful outcome; the system makes those definitions visible, never hard-codes them.
- Associations, not causal claims. Where volume permits, matched comparisons and before/after baselines — with confounders documented.
