# connectors/

Ingestion. Everything that touches an external system lives here, and nothing else in the repo does — the harness itself never calls GitHub, Jira, or an agent tool directly.

## What goes here

One subpackage per source:

| Connector | Source | Produces |
|---|---|---|
| `github/` | Repo + PR history (public OSS repos in fall, eBay's in spring) — commits, PRs, reviews, reverts, CI status | Raw material for `harness/signals` and `harness/trace` |
| `jira/` | Project-management metadata — ticket, priority, story points, issue type, initiative links. **Synthetic generator in fall**, real integration only after eBay's review approves it | Ticket context for `harness/trace` |
| `telemetry/` | Agent/IDE session exports (Cursor, Claude Code) — session shape, model, tokens, patches accepted/rejected. Synthetic in fall | Session records for `harness/classifier` |

## How it communicates with the rest

Connectors have exactly one job: **normalize an external source into records that validate against `schemas/` and write them into `data/`**. Downstream components read those files; they never see a raw API response. This boundary is deliberate — it's what lets the whole harness run fully in-house on an export if eBay's review rules out live integrations, and it's where "content-free metadata first" is enforced: content-level fields simply aren't extracted unless the connector is explicitly configured to.
