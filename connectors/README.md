# connectors/

Ingestion. Everything that touches an external system lives here, and nothing else in the repo does — the harness itself never calls GitHub, Jira, or an agent tool directly.

## What goes here

One subpackage per source:

| Connector | Source | Produces |
|---|---|---|
| `github/` | Repo + PR history (public OSS repos first; customer repos once deployed in their environment) — commits, PRs, reviews, reverts, CI status | Raw material for `harness/signals` and `harness/trace` |
| `jira/` | Project-management metadata — ticket, priority, story points, issue type, initiative links. **Synthetic generator for now**; real integration only after a customer's security review approves it | Ticket context for `harness/trace` |
| `telemetry/` | Agent/IDE session exports — session shape, model, tokens, patches accepted/rejected. One adapter per harness: Claude Code, Cursor, Codex first-class; new harnesses enter via `source_tool: other` and get promoted per ADR-0003. Synthetic for now | Session records for `harness/classifier` |

## Local-log source plugins (built — the extractor's first milestone)

The telemetry path is live for local logs: `claude_code.py`, `cursor.py`, and
`codex.py` implement the `SourcePlugin` interface in `base.py`
(`discover() → read() → emit()`), driven by `caliper extract` (see `cli/`).
Each plugin file's docstring records the format facts it is grounded in;
the structural validation behind them is ADR-0001 (Claude Code, Cursor
tracking DB) and ADR-0004 (Codex rollout JSONL, Cursor state DB). Hard rules:
read-only sources, SQLite snapshot-copied before opening, content dropped at
emission by default, fields a tool cannot provide are absent — never defaulted.

`git_history.py` is the outcome-side counterpart (driven by `caliper signals`):
local-git production signals — blame-based survival, rework, revert linkage,
evidence-only AI attribution — for the repos the extracted sessions reference
(ADR-0006). It computes what `harness/signals` will own once the GitHub
connector exists; the local-git read and the signal math live together here
until that split is real.

## How it communicates with the rest

Connectors have exactly one job: **normalize an external source into records that validate against `schemas/` and write them into `data/`**. Downstream components read those files; they never see a raw API response. This boundary is deliberate — it's what lets the whole harness run fully inside a customer's environment on an export if their security review rules out live integrations, and it's where "content-free metadata first" is enforced: content-level fields simply aren't extracted unless the connector is explicitly configured to.
