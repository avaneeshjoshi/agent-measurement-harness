# harness/judge/

**Design README only — no code exists yet (see [`PROGRESS.md`](../../PROGRESS.md)).** No judge runner, no rubrics, and no calibration set have been built; everything below is the intended design.

The judged quality track, with the safeguards that make LLM-as-judge defensible instead of hand-waved.

## Non-negotiable safeguards (each will get its own ADR in `docs/decisions/` when implemented)

- The judge model is from a **different provider** than any model under test.
- Comparisons are **pairwise and position-swapped**, never absolute scores.
- The judge is **calibrated** against a 100–200 task human-labeled set (rated by practicing engineers, ~1hr each), with judge–human agreement reported per class.
- Judge results are used **only where agreement clears 80%** per class; classes below threshold escalate to human review rather than being silently trusted.

## What goes here

- Pairwise comparison runner with position swapping.
- Per-class rubrics (correctness, convention adherence, maintainability) — the executable form of what `docs/methodology.md` specifies.
- Calibration tooling and agreement-statistics reporting.

## Inputs

- Output pairs from `harness/replay` for tasks lacking test coverage.
- The human-labeled calibration set from `data/calibration/`.

## Outputs

- Judged-track `eval_result` records with per-class agreement stats attached, written to `data/`.

## Consumed by

- `harness/routing` — judged-track curves for no-test classes.
- `dashboard/` — quality views, always displayed with the agreement caveat.
