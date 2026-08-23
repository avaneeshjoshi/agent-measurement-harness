# data/

The medium every component communicates through: connectors write normalized records here, harness stages read and write here, and the intended dashboard will read from here (no dashboard exists yet — see [`PROGRESS.md`](../PROGRESS.md)). Every record validates against a schema in `schemas/`; the test suite enforces it on every push and PR (`.github/workflows/ci.yml`).

## What's here

| Subdir | Contents |
|---|---|
| `extracted/` | Connector output: normalized sessions, prompt units, git production signals, run manifests, the first-look report. **Gitignored — local traffic never enters the repo** (enforced by test) |
| `derived/` | Harness output (committed): task classes, eval results, the routing policy record |
| `calibration/` | The human-labeled sets — today the ADR-0002 unit-comparison labels; the 100–200 task judge-calibration set is planned and needs human raters |
| `fixtures/` | Small hand-built source-log samples used by `tests/` |

Planned, not yet existing: a `synthetic/` tree (generated Jira projects and telemetry sessions for an end-to-end demo).

## Rules

- **No customer data, ever, in this repo.** Development runs entirely on public OSS repos, synthetic project-management data, and synthetic telemetry. In customer deployments, content-level data exists only inside the customer's environment — this repo holds the tooling, not the traffic.
- Extracted local traffic (`extracted/`) is never committed; fixtures, calibration sets, and the derived records that back cited numbers are.
- Records are append-only and versioned by the schema version that produced them; re-runs write new artifacts rather than mutating old ones, so every reported number stays reproducible.
