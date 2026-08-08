# Schema & data conventions (v0)

Rules every component and every schema follows. Short on purpose — if a rule needs a page, it becomes an ADR in `decisions/`.

## Versioning

- Every schema has a required `schema_version` field, semver starting at `0.1.0`. All six schemas are v0: **expected to change after engineer interviews**, and no component may hard-code against field presence beyond what a version's schema guarantees.
- Every data record states the `schema_version` it was written under. Re-runs write new artifacts; old records are never rewritten to a new version.
- Three version axes are deliberately independent: the **schema** version (record shape), the **taxonomy** version (what the labels mean), and the **producer** version (`classifier_version`, `signals_version`, `tracer_version`, `router_version`, `judge_version`). Bumping one never implies bumping another.
- Source log formats drift under us: real Claude Code logs show fields appearing between CLI versions (e.g. `promptSource` exists in 2026-08 logs, not 2026-07 ones). Connectors record `source_format_version` and treat absent fields as "unrecorded", never as defaults.

## Uncertainty vocabulary (used identically in all schemas)

- **AI attribution** is always the enum `known | partial | unknown`, and is only ever established from tracking-database evidence, session-trace linkage, or explicit self-report. **Never from what the code looks like.**
- Every enum that describes the world includes `unknown` (not classification-status enums like `classified/unclassified`, which describe our own output). Absence of evidence is encoded, never omitted or defaulted.
- `unclassified` is a legal classifier outcome and is reported as a share of traffic, not dropped.
- Judged scores travel with their calibration block (`agreement_statistic`, `calibration_n`, `cleared_agreement_gate`) — a score may not circulate without it.
- Every aggregate carries `n`; where `n` supports one, a CI object `{lower, upper, level, method}`.
- Where two measurement tracks disagree, the disagreement is representable (`triangulation.verdict = tracks_disagree`) and there is intentionally **no field anywhere that can hold an average of the two tracks**.
- "Not yet measurable" (young commits vs. survival horizons) is a distinct status, never conflated with a measured zero.

## Classification unit and turn indexing

The unit of classification is **unsettled between per-prompt, per-segment, and per-session**; every task_class record states its `unit`, and the same traffic may legally carry classifications at several granularities so distributions can be compared.

- A **user prompt turn** is a `type=user` log record containing user-authored text: not a tool result, not `isMeta`, not command/attachment/interruption bookkeeping. **Turn indices** are 0-based ordinals over these records within a session; all `turn_range` fields are inclusive and use this indexing.
- A **prompt unit** is one user prompt turn plus its response window (everything up to the next user prompt turn).

## Segmentation (segmenter_version 0.1.0)

Segments are defined by **observable boundaries only — no semantic or content inference in v0**. Boundary rules are versioned; segment classifications are only comparable within one `segmenter_version`. A new segment opens at user prompt turn T when any rule fires (precedence for `opened_by` labeling: `turn_gap` > `branch_change` > `file_set_jump` > `interrupt`):

1. **session_start** — T is the session's first prompt turn.
2. **turn_gap** — more than **30 minutes** of wall clock between the last record before T and T.
3. **branch_change** — `gitBranch` at T differs from the previous prompt turn's.
4. **file_set_jump** — the files edited in T's response window and those edited so far in the current segment are both non-empty and disjoint **at both the file and top-level-directory level**. (Segmentation is offline; looking ahead into T's window is allowed.)
5. **interrupt** — the previous response window contained a user interruption (an `interrupted` tool result or an interruption marker record).

Known v0 limitations, recorded rather than patched: `file_set_jump` under-segments repos where one directory holds everything and over-segments scaffolding that touches many new files; `interrupt` may split mid-task corrections that are really the same intent. These are measurement questions for the unit-choice comparison, not bugs to silently tune away.

## Provenance annotations

Schema properties carry `x-provenance`:

- `observed` — the field exists verbatim in real logs we have read.
- `derived` — computable from real log contents.
- `aspirational` — requires a source we don't have yet (enterprise telemetry, org mapping, price sheets). Aspirational fields are nullable and their absence is expected until those integrations exist.

## Content and privacy

- Session records are **content-free**: no prompts, code, file contents, or command output. Classifiers list the features they consumed (`features_used`).
- Paths, private repo names, and org identifiers are salted-hashed at the connector (`project_ref`, `repo_ref`, `team_ref`). Public OSS repo refs may stay plain.
- Reporting is team-level and above. Per-change attribution fields exist as evidence and are aggregated before any surface renders them. No individual rankings, ever.

## Field style

- `snake_case` field names; ISO-8601 UTC timestamps (`*_at`); durations as `*_ms`; counts as plain integers; fractions in `[0,1]` named `*_fraction`.
- `additionalProperties: false` everywhere — unknown fields are a validation error, which is how format drift gets noticed instead of silently ignored.
- v0 keeps each schema file self-contained (small `$defs` duplicated, e.g. the CI object) so components can validate against a single file. Consolidating shared defs is a v1 decision.
