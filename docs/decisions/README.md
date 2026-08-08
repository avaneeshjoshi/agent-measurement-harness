# docs/decisions/

The decision log — the concrete artifact behind "glass box by default." Every classification rule, scoring rubric, threshold, and routing recommendation gets a numbered entry here **at the time the decision is made**, so an auditor (or a customer's platform team) can reconstruct not just what the system does but why.

## What goes here

One markdown file per decision, named `NNNN-short-title.md` (e.g. `0003-judge-provider-selection.md`), in lightweight ADR format:

```markdown
# NNNN. Title
Date: YYYY-MM-DD
Status: proposed | accepted | superseded by NNNN

## Context
What question forced a decision, and what constraints applied.

## Decision
What was decided, precisely enough to implement.

## Consequences
What this makes easier, harder, or riskier. What would trigger revisiting it.
```

## How it communicates with the rest

Components reference decisions by number: a routing recommendation emitted by `harness/routing` carries the IDs of the decisions its rationale rests on, and rubric changes in `harness/judge` must point at the ADR that authorized them. Nothing here is executed — but nothing elsewhere should be unexplained here.
