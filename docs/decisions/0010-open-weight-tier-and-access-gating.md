# ADR-0010: Open-weight tier and access-gated routing

Status: accepted · 2026-08-13

## Context

The tier taxonomy used by routing policies and the eval slice was
`frontier / mid / small` — implicitly all closed, vendor-hosted models. Two
gaps:

1. Open-weight models (DeepSeek, Qwen, Llama, Kimi, GLM, gpt-oss, …) are a
   real routing option for some users and don't fit any existing tier. Their
   economics are categorically different (self-hostable, multiple hosted
   providers, sometimes no per-token price at all).
2. Nothing stopped a routing recommendation from naming a tier the user
   cannot actually run. A policy that says "route to X" where the user has
   no access to X is not actionable advice; it's a hypothetical.

## Decision

### One tier: `open_weight` (open-source folds in)

"Open weight" = the weights are downloadable and runnable outside the
vendor, regardless of license restrictions or whether training data/code is
published. "Open source" (OLMo-style: weights + code + data + permissive
license) is a strict subset. For everything Caliper measures — quality on
replayed tasks, cost, routing viability — the two behave identically, so
they share one tier. Splitting them would create two near-empty categories
whose distinction is about licensing philosophy, not routing. The stricter
provenance can become a model-level attribute later if a compliance use
case needs it; it is not a tier.

Taxonomy is now `frontier / mid / small / open_weight`, expressed as prefix
mappings in `cli/policy.py:TIER_OF_MODEL`. The routing_policy schema keeps
`model_tier` as a free string, so no schema bump.

### Access is proven by traffic, not declared

A tier may appear in a routing recommendation **iff the user provably has
access to it**. v0 proof: a model of that tier appears in the user's own
extracted sessions (`accessible_tiers()`). This is the same epistemic rule
as the rest of Caliper — measured, not asserted. Planned extension:
`caliper connect`, where linking a provider account proves access to models
not yet present in traffic. The CLI labels this path "(future)".

### Unmeasured tiers stay visible

The quality-per-tier view renders every tier in the taxonomy, never just
the measured ones:

- measured → the normal quality/cost rows;
- access proven but not evaluated → "quality not measured · excluded from
  the recommendation until evaluated";
- no access proven → "no access proven in your traffic — excluded from
  routing".

Silent absence would read as "doesn't exist"; the absent ≠ zero convention
applies to tiers exactly as it applies to costs.

## Consequences

- Recommendations can never name a tier without both proven access and
  eval evidence. Today that means open_weight is visible but ineligible
  for every user, including this repo's own traffic.
- Adding an open-weight tier to the quality curve requires a harness that
  can drive those models through the replay pipeline — deferred until
  either open-weight traffic appears in an extraction or a user asks the
  routing question directly.
- Local inference has no per-token price; if open-weight traffic appears
  from a local runtime, its sessions are "not priced" (correct under
  ADR-0006's absent ≠ zero rule) until a cost model for self-hosting
  ($/GPU-hour) is designed. Hosted open-weight traffic prices normally via
  the LiteLLM snapshot once its keys are mapped.
