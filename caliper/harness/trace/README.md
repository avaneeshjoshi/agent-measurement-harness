# harness/trace/

**Status (ADR-0019, see [`PROGRESS.md`](../../../PROGRESS.md)):** `tracer.py` is v0 — three edge producers behind `caliper trace`: commit → ticket (ticket key in the commit message, versioned regex + blocklist), session → ticket (key in the session's branch name), and session → commit by salted file-ref overlap with a causality constraint (time is a tiebreaker only; one edge per commit). Records write to `~/.caliper/extracted/trace/trace_events.jsonl`; `caliper trace` prints the chain-rate with its n. **Not built:** deployment and outcome nodes, any `value_dimensions` producer (every edge carries `null`), and any consumer — serve still labels nearby commits temporal proximity until a surface renders real edges. The rest of this page is the intended design.

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
