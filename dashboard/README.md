# dashboard/

The reporting UI — a Next.js app. This is the customer-facing surface: what a platform lead or a CTO actually looks at.

## What goes here

A Next.js (App Router, TypeScript) application whose views map to the four harness outputs:

1. **Usage map** — task-mix distribution by team, tool, and model (from classifier output).
2. **Quality curves** — per-class quality/cost per tier with confidence intervals, with-skill vs. without (from replay + judge), production signals alongside for triangulation — disagreements shown, not blended.
3. **Value view** — the decision buckets from trace: high-priority work with strong AI contribution; high AI spend on low-priority or abandoned work; AI-assisted work that reached production with low rework; classes with high review burden; classes where cheaper models held quality; classes where cheap routing created downstream rework.
4. **Routing policy** — recommendations with their evidence and ADR links, plus the projected ROI at the org's own prices.

## Inputs

- Schema-conforming artifacts from `data/derived/` — read via a thin API route layer (no direct coupling to harness internals; the schemas are the contract). An early demo can read static JSON exports; a live backend is a later decision.

## Outputs

- None. The dashboard is strictly a consumer — it computes nothing, so every number on screen is reproducible from a harness artifact.

## Rules

- **Team-level and above only. No individual rankings, no leaderboards, by design** — the instrument measures the system, not the people. This is enforced here (the data layer aggregates before render), not just promised.
