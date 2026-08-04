# docs/

The written half of the glass box. Everything that explains *why* the harness works the way it does lives here, versioned alongside the code it governs.

## What goes here

| File / dir | Contents |
|---|---|
| `proposal.md` | The engagement proposal — problem, harness design, phasing, assumptions |
| `methodology.md` | The scoring protocol in full: two tracks (production signals + controlled replay), triangulation rules, calibration procedure, agreement thresholds |
| `taxonomy.md` | The three-axis task taxonomy (task type × context breadth × risk tier) and its validation results |
| `decisions/` | The decision log — see [`decisions/README.md`](decisions/README.md) |

## How it communicates with the rest

Docs are not imported at runtime, but they are **normative**: the per-class rubrics defined in `methodology.md` are the rubrics `harness/judge` implements, and the class definitions in `taxonomy.md` are the labels `harness/classifier` emits (their machine-readable forms live in `schemas/`). When a doc and the code disagree, that's a bug — file it against whichever changed without the other.
