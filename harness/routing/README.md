# harness/routing/

The action layer: turns everything upstream into a per-class routing policy the data justifies. Deliberately last and deliberately thin — flipping the switches (Cursor admin panel, Claude Code model defaults, skill attachments) is cheap; this package produces the *evidence* for which switches to flip.

## What goes here

- Curve assembly: quality-per-tier and cost-per-tier by task class, from both eval tracks, with confidence intervals.
- Task-mix weighting: curves weighted by the real usage distribution to produce a projected routing ROI at the org's actual model lineup and prices.
- Risk overrides: policy is a function of task class **and** the work's priority/criticality from `harness/trace` — a routine-looking change on a production-critical path doesn't get down-tiered just because its class curve says it could.
- Skill recommendations: where the with-skill curve holds quality a tier lower, the policy says so — as a measured yes/no, not an opinion.
- Verification mode: comparing an auto-router's actual choices (Cursor Auto, etc.) against what the measured curves would have chosen, on sampled traffic.

## Inputs

- `eval_result` records (objective + judged tracks) from `data/`.
- Task-mix distribution from `harness/classifier`.
- Priority/risk context from `harness/trace`.
- Model lineup and pricing config.

## Outputs

- `routing_policy` records — per-class recommendations, each carrying its evidence and the `docs/decisions/` ADR IDs its rationale rests on — written to `data/`.

## Consumed by

- `dashboard/` — the ROI projection and policy views.
- Ultimately, a human with admin access: **this package recommends; it never routes live traffic itself.**
