# schemas/

The shared contracts. Every record that crosses a component boundary conforms to a JSON Schema defined here — this is how components "communicate" without importing each other, and what makes any single stage re-runnable or replaceable in isolation.

## What goes here

Writers/readers marked *(planned)* don't exist yet — see [`PROGRESS.md`](../PROGRESS.md) for what's real.

| Schema | Describes | Written by | Read by |
|---|---|---|---|
| `session.schema.json` | A normalized agent session: content-free metadata (diff size, files touched, session shape, language, tool-call pattern, model, tokens) | `connectors/` | `harness/classifier`, `harness/report`, `cli/policy`, `harness/trace` *(planned)* |
| `prompt_unit.schema.json` | One user prompt turn plus its response window, as content-free per-unit metadata (claude_code and codex only; Cursor is session-grain) | `connectors/` | `harness/classifier` |
| `task_class.schema.json` | A classification of one unit of agent work (prompt / segment / session): task type × context breadth × risk axes, with unit, classifier version, and confidence | `harness/classifier` | `harness/report`, `cli/policy`, `harness/routing` *(planned)*, `dashboard/` *(planned)* |
| `eval_result.schema.json` | One replay cell: task × model tier × (skill on/off), objective-track results (test pass, lint/type gates) and/or judged-track scores | `harness/replay` (`harness/judge` *(planned)*) | `cli/policy`, `harness/routing` *(planned)*, `notebooks/` *(planned)*, `dashboard/` *(planned)* |
| `production_signal.schema.json` | Per-change history signals: survival at 30/60/90 days, two-week rework, review iterations, revert linkage, AI-attribution confidence | `connectors/git_history.py` (moves to `harness/signals` at the normalize/compute split, ADR-0006 §7) | `harness/report`, `dashboard/` *(planned)*, triangulation in `notebooks/` *(planned)* |
| `trace_event.schema.json` | One link in the value chain: session → commit/PR → ticket/initiative → deployment → outcome, plus the value dimensions (priority, category, criticality, delivery status, AI-contribution strength) kept as **separate fields, never a single score** | `harness/trace` *(planned — zero records exist)* | `harness/routing` *(planned)*, `dashboard/` *(planned)* |
| `routing_policy.schema.json` | A per-class routing recommendation with cost/quality evidence and ADR references | `harness/routing` *(planned — the one existing record, rp-0001, was hand-written against this schema, ADR-0008)* | `cli/policy`, `dashboard/` *(planned)* |

## Rules

- Schemas are versioned; breaking changes bump the version and old data is never rewritten.
- Validation runs in the test suite (`tests/`) against the fixtures in `data/fixtures/`, on every push and PR (`.github/workflows/ci.yml`).
- The trace event schema doubles as the external integration contract — it's what a customer org reviews before a deployment.
