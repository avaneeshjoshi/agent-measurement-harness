# harness/signals/

The production-signals track: what actually happened to agent-written code after it landed, computed retrospectively from Git and PR history. This is the track that catches what acceptance rate can't — acceptance measures plausibility, not correctness, so this package deliberately doesn't lean on it.

## What goes here

Computation of the signals that survive scrutiny:

- **Survival** — how much agent-written code is still present unmodified at 30, 60, and 90 days.
- **Rework** — how much is revised within two weeks of landing.
- **Review friction** — iterations to merge.
- **Revert linkage** — changes later tied to reverts or incident fixes.
- AI-attribution handling: uses whatever signal exists in history (tool trailers, PR tags); where instrumentation is absent, attribution is reported as **unknown or partial, never inferred from code style**.

## Inputs

- Normalized Git/PR history from `data/` (written by `connectors/github`) — public OSS repos in fall, eBay's history in spring.

## Outputs

- `production_signal` records per change, with attribution confidence, written to `data/`.

## Consumed by

- `dashboard/` — rework/survival views by task class.
- `notebooks/` — triangulation against replay/judge results; disagreements between tracks are surfaced, not averaged.
