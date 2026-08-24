# ADR-0013: Classifier 0.2.0 — neighborhood flow features, pre-registered

**Date:** 2026-08-24 · **Status:** accepted · **Delivers:** the "neighborhood features" follow-up ADR-0009 ranked first

## Context

ADR-0009 named rules-0.1.x's clearest structural blindness: **flow context is
invisible at prompt grain**. The human definition of `ui_verification_loop`
is an edit-and-check *flow*, and the check often lands a few prompts after
the edit it verifies — so windows humans labeled uvl from surrounding context
were honest misses for any single-window rule. The frozen ADR-0009 report
quantifies it: 22 human uvl windows, 16 matched, and the misses cluster
exactly where flow context would help.

Two side findings land here as well (they came from the same working
session): the drift counters' unknown-type triage, and the corpus switch-on.

## Decision 1: record-type triage (from the ADR-0011 drift counters)

The five claude_code shapes the counters surfaced, examined against live
logs:

- **`agent-name` — real signal, content-level.** A work-describing session
  title (e.g. "retention-model-fix-fork-netting"). Same nature as Cursor's
  composer names, which ADR-0004 classified content-level — so it goes ONLY
  to the content sidecar (`role: "session_title"`), never into session
  records. It is near-ideal weak-label material for the teacher-labeling
  corpus.
- **`file-history-delta` — moderate signal, deferred.** Per-edit file path +
  timestamp; overlaps the structuredPatch-derived edit extraction. Candidate
  for edit detection where patches are absent; not worth connector surface
  now. Recorded, not built.
- **`queue-operation`** — enqueue records carry FULL PROMPT TEXT (a second
  place prompt content lives in the raw logs; noted as a boundary hazard).
  No metadata value: queued prompts surface as normal user turns when
  dequeued.
- **`atis-latch`** (empty latch) and **`frame-link`** (artifact-preview
  bookkeeping, rare) — noise; stay known-ignored.

Corpus note: `include_content` was switched on for this machine on
2026-08-24 (the ADR-0011 decision-5 opt-in, exercised); sidecars accumulate
forward from that date and include session titles.

## Decision 2: neighborhood features (rules-0.2.0)

**Design, fixed before any validation run:**

- **Neighborhood** = the other prompt windows of the unit's
  **segmenter-0.1.0 segment**, at turn distance ≤ `NEIGHBORHOOD_RADIUS = 3`.
  Segments are already the flow unit; reusing them inherits the 30-minute
  gap / branch / file-set boundaries instead of inventing a second flow
  definition.
- **Features:** `nbr_browser` (browser-family calls across the neighborhood,
  same `_tool_family` detector as R01/R01b) and `nbr_edits` (files edited
  across the neighborhood). Prompt grain only — segment and session grains
  aggregate whole flows already, and pass no neighborhood, so the new rules
  are structurally unable to fire there.
- **Rules:**
  - `R01c-neighborhood-browser` (after R01b): edit-bearing window, zero
    in-window browser, `nbr_browser ≥ 1` → ui_verification_loop, 0.5.
  - `R01d-flow-sandwich` (before R06/R07/R08): no-edit window,
    `nbr_browser ≥ 2` **and** `nbr_edits ≥ 1` → ui_verification_loop, 0.45.
    Zero edits demands stronger flow evidence, hence the higher bar.
- Version: `rules-0.2.0`. Thresholds and precedence are the contract of this
  ADR; changing them requires a new ADR round, not iteration.

## Decision 3: the one-shot measurement, disclosed

ADR-0009 froze rules-0.1.1 with the rule that adjustments require new
labels, not re-tuning against the 81. This ADR takes the one sanctioned
follow-up measurement ADR-0009 itself named — under pre-registration
discipline, mirroring ADR-0007's predictions file:

- This design and the predictions below are **committed before the
  validation run**; the run happens once; the numbers are reported as
  findings whatever they show; no post-hoc threshold adjustment. This is the
  **second and final** measurement against these 81 labels — further rule
  work waits for new labels (the corpus now accumulating, or enterprise
  raters per ADR-0002).
- `caliper classify --validate` wires the previously caller-less
  `validation.validate()` so the run is reproducible instead of ad hoc; the
  report writes home-side, and the citable copy is frozen under
  `data/evidence/adr-0013/` by a deliberate git action.

**Pre-registered predictions (from the frozen 0.1.1 report, before running):**

1. Seven windows flip to the human uvl label — `208e4ab7` turns 0, 1, 2, 4;
   `25b2e1c2` turns 17, 18; `082b86fa` turn 8. Expected uvl recall
   16/22 → up to 23/23-equivalent (≤ 22 matched; some of the seven may sit
   outside their neighbors' segments and not flip).
2. Prompt accuracy rises from 53.1% by roughly the net flips over n=81
   (each true flip ≈ +1.2 points), **minus regressions**: windows 0.1.1 got
   right that sit near browser activity and now get pulled into uvl —
   most exposed are exploratory_qa windows inside verification-heavy
   segments (R07 → R01d requires nbr_edits too, which should limit this).
   Honest expectation: net +4 to +8 points with 0–3 regressions.
3. Segment- and session-grain numbers are byte-identical to 0.1.1 (no
   neighborhood at those grains) — any change there is a bug, not drift.

## Results (one run, 2026-08-24; frozen at `data/evidence/adr-0013/`) — HYPOTHESIS REJECTED

Prompt grain: **50.6% / κ 0.365** vs 0.1.1's 53.1% / κ 0.412 — a net loss of
2 matches out of 81. Against the pre-registered predictions:

1. **1 of 7 predicted flips landed** — `082b86fa/8`, the R01d sandwich (the
   single case the design was built from). The other six did **not** flip,
   and the pair-level diff shows why: their neighborhoods contain **zero
   recorded browser activity** within the segment at any adjacent turn. The
   humans labeled those windows uvl from *narrative* context — the session
   is about verifying UI behavior — not from tool-call adjacency. **The
   signal is not in the tool metadata at any radius.** That is a stronger
   finding than ADR-0009's "flow context is invisible at single-window
   grain": for most of these misses, flow context is invisible at *flow*
   grain too.
2. **3 regressions, exactly the predicted failure mode**: two exploratory_qa
   windows (`25b2e1c2/34`, `79bae53e/3`) and one feature window
   (`79bae53e/1`) inside verification-heavy segments were pulled into uvl by
   R01d/R01c. uvl recall stayed 16/22 while precision fell 0.71 → 0.53.
3. **Prediction 3 held**: segment and session grains byte-identical to 0.1.1.

**Decision: the 0.2.0 rules are WITHDRAWN** — a go/no-go on the measured
result, not tuning. `CLASSIFIER_VERSION` returns to `rules-0.1.1` (version
identity follows behavior); the neighborhood machinery
(`features.neighborhood_features`, the inert `nbr_*` features) stays in the
tree, tested, for future label rounds; a regression test asserts the
withdrawn rules cannot influence verdicts. Per the one-shot discipline there
was no second run and no threshold adjustment — this ADR and the frozen
report are the complete record of the attempt.

## Consequences

- The 53.1% / κ 0.41 figures stand as the production classifier's numbers.
- uvl's remaining misses are now known to need **content**, not cleverer
  metadata rules — which makes the corpus (Decision 1) the classifier's
  critical path, exactly as ADR-0009's follow-up ranking guessed and this
  experiment confirms.
- `caliper classify --validate` remains: agreement runs are now one command,
  reproducible, with reports versioned home-side per classifier version.
- The 81 labels are spent as an adjustment target — twice is the limit this
  ADR sets for itself. Next label money goes to teacher-labeling over the
  sidecar corpus (accumulating since 2026-08-24) and, eventually,
  multi-rater enterprise labels (ADR-0002 gate).
