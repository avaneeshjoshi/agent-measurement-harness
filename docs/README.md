# docs/

The written half of the glass box. Everything that explains *why* the harness works the way it does lives here, versioned alongside the code it governs.

## What's here

| File / dir | Contents |
|---|---|
| [`conventions.md`](conventions.md) | Schema and data rules: versioning, uncertainty vocabulary, segmentation, provenance, privacy, field style |
| [`decisions/`](decisions/) | The decision log — see [`decisions/README.md`](decisions/README.md) |
| [`setup-demo-web-spec.md`](setup-demo-web-spec.md) | Handoff spec for the web demo of the `caliper setup` flow |

## Planned, not yet written

- `proposal.md` — the product thesis: problem, harness design, phasing, assumptions
- `methodology.md` — the scoring protocol in full: two tracks, triangulation rules, calibration procedure, agreement thresholds
- `taxonomy.md` — the three-axis task taxonomy and its validation results (today the taxonomy lives, flagged provisional, in `schemas/task_class.schema.json` and the ADRs that stress-tested it: 0001, 0002, 0009)

## How it communicates with the rest

Docs are not imported at runtime, but they are **normative**: the class definitions the classifier emits and the rubrics the judge will implement get their prose definitions here (machine-readable forms in `schemas/`). When a doc and the code disagree, that's a bug — file it against whichever changed without the other.
