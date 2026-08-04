# harness/

The core Python package. Six subpackages, each one stage of the pipeline; each reads schema-conforming records from `data/` and writes its results back there. No subpackage imports another's internals — shared shapes live in `schemas/`.

## Pipeline order

```
connectors → classifier → replay → judge ┐
                        └────────────────┼→ routing → dashboard
             signals  ───────────────────┤
             trace    ───────────────────┘
```

| Subpackage | One-line job | Track |
|---|---|---|
| [`classifier/`](classifier/) | Label every session with task type × context breadth × risk tier from content-free metadata | Visibility |
| [`replay/`](replay/) | Re-run sampled tasks across model tiers × (skill on/off) under identical conditions | Quality (objective) |
| [`judge/`](judge/) | Pairwise, position-swapped LLM judging where hidden tests don't exist; calibrated against human labels | Quality (judged) |
| [`signals/`](signals/) | Mine Git/PR history for survival, rework, review iterations, revert linkage | Quality (production) |
| [`trace/`](trace/) | Link session → commit/PR → ticket → deployment → outcome; keep value dimensions separate | Value |
| [`routing/`](routing/) | Turn curves + task mix + risk context into a per-class routing policy with logged rationale | Action |

## Triangulation rule

Replay/judge results and production signals measure the same question two ways. **Where they disagree, the disagreement is reported, never averaged away** — that rule is enforced at this layer, not in the dashboard.
