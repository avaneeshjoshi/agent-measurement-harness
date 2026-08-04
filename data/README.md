# data/

The medium every component communicates through: connectors write normalized records here, harness stages read and write here, the dashboard reads from here. Every file validates against a schema in `schemas/` (enforced in CI).

## What goes here

| Subdir | Contents |
|---|---|
| `raw/` | Connector output: normalized sessions, Git/PR history, ticket metadata |
| `derived/` | Harness output: task classes, eval results, production signals, trace events, routing policies |
| `calibration/` | The human-labeled sets — classifier labels and the 100–200 task judge-calibration set |
| `fixtures/` | Small hand-built samples used by `tests/` and for schema validation in CI |
| `synthetic/` | Generated traffic: synthetic Jira projects, synthetic telemetry sessions for the end-to-end demo |

## Rules

- **No real eBay data, ever, in this repo.** Fall runs entirely on public OSS repos, synthetic project-management data, and synthetic telemetry. In spring, content-level data exists only inside eBay's environment — this repo holds the tooling, not the traffic.
- Large derived artifacts don't get committed; only fixtures, calibration sets, and small samples do. (What's tracked vs. generated gets settled when the pipeline lands.)
- Records are append-only and versioned by the schema version that produced them; re-runs write new artifacts rather than mutating old ones, so every reported number stays reproducible.
