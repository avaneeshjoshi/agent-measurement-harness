# schemas/

The shared contracts. Every record that crosses a component boundary conforms to a JSON Schema defined here — this is how components "communicate" without importing each other, and what makes any single stage re-runnable or replaceable in isolation.

## What goes here

| Schema | Describes | Written by | Read by |
|---|---|---|---|
| `session.schema.json` | A normalized agent session: content-free metadata (diff size, files touched, session shape, language, tool-call pattern, model, tokens, cost) | `connectors/` | `harness/classifier`, `harness/trace` |
| `task_class.schema.json` | A classification label: task type × context breadth × risk tier, with classifier version and confidence | `harness/classifier` | `harness/replay`, `harness/routing`, `dashboard/` |
| `eval_result.schema.json` | One replay cell: task × model tier × (skill on/off), objective-track results (test pass, lint/type gates) and/or judged-track scores | `harness/replay`, `harness/judge` | `harness/routing`, `notebooks/`, `dashboard/` |
| `production_signal.schema.json` | Per-change history signals: survival at 30/60/90 days, two-week rework, review iterations, revert linkage, AI-attribution confidence | `harness/signals` | `dashboard/`, triangulation in `notebooks/` |
| `trace_event.schema.json` | One link in the value chain: session → commit/PR → ticket/initiative → deployment → outcome, plus the value dimensions (priority, category, criticality, delivery status, AI-contribution strength) kept as **separate fields, never a single score** | `harness/trace` | `harness/routing`, `dashboard/` |
| `routing_policy.schema.json` | A per-class routing recommendation with cost/quality evidence and ADR references | `harness/routing` | `dashboard/` |

## Rules

- Schemas are versioned; breaking changes bump the version and old data is never rewritten.
- Validation runs in CI (`tests/`) against every fixture in `data/`.
- The trace event schema is itself a fall deliverable — it's the integration contract eBay reviews before spring.
