# ADR-0009: Classifier v0 — content-free agreement with human labels, and what metadata cannot see

**Date:** 2026-08-10 · **Status:** accepted · **Artifacts:** `harness/classifier/` (rules-0.1.1, segmenter 0.1.0), `data/derived/classes/` (1446 task_class records, validation + traffic reports) *(reports relocated to `data/evidence/adr-0009/`; the live task_classes file is user data under ~/.caliper — ADR-0012. The 1,446-record input snapshot behind these numbers is pinned at commit `a2dddd7` — full sha `a2dddd77bd29aad21ea53236e23e94f1d3e95cd6` — retrievable with `git show a2dddd7:data/derived/classes/task_classes.jsonl`, so the agreement figures are recomputable, not archaeological)*

## The experiment

The ADR-0002 calibration labels were assigned by reading prompt text. The classifier
must reproduce them from CONTENT-FREE metadata only (tool patterns, diff shapes,
path-derived flags, timings — enforced by tests that verify content sidecars are never
opened). The agreement gap *is* the measurement.

## Infrastructure findings first (they gate everything)

1. **Source logs are ephemeral — continuous extraction is a product requirement, not
   an optimization.** A raw log behind the Aug-7 calibration set was gone by Aug-10
   (observed retention ≈ days — corrected to ~30 in the Postscript below). Its 2 prompt + 1 segment labels are permanently
   unvalidatable; content-free records cannot reconstruct labels that needed prompt
   text. The surviving calibration raw logs are snapshotted outside the retention
   path. Backfill is lossy by construction.
2. **Turn indexing and segmentation reproduce the calibration exactly** where sources
   survive: extracted prompt-unit counts match calibration turn ranges on 7/7
   surviving sessions, and segmenter 0.1.0 reproduces **13/13 validatable segments**
   byte-exactly. One divergence found and resolved: conventions.md names interruption
   *markers* as an interrupt signal, but the calibration reference fired interrupt ×0 —
   0.1.0 therefore splits on interrupted tool results only; marker-based splitting is
   a versioned 0.2.0 candidate (prompt_unit 0.1.1 carries both signals separately).

## Agreement vs human labels (n=81 prompt, 13 segment validatable)

| unit | accuracy | Cohen's κ | strongest classes (F1) |
|---|---|---|---|
| prompt | **53.1%** | **0.412** | exploratory_qa 0.78 · ui_verification_loop 0.71 · multi_file_refactor 0.67 |
| segment | 38.5% | 0.235 | ui_verification_loop 0.57 · feature_implementation 0.50 |

One disclosed post-validation adjustment round produced rules-0.1.1 (44.4%→53.1%):
a path-marker bug fix (generic `/memory/`, `/skills/` misflagged product work as
agent_meta_work) and one definitional rule (R01b: ui_verification_loop is an
edit-and-check *flow*, so browser presence — not dominance — marks it at prompt
grain). No threshold-chasing beyond that; the numbers below stand as findings.

## Classes that resist metadata-only classification (findings, not bugs)

- **`other` is structurally unreachable** (0/4): "doesn't fit the taxonomy" is a
  judgment about intent that metadata cannot express. A rules classifier will never
  emit it; recurring `other` detection needs content or a human loop.
- **config_infra (0/4) and documentation (0/2)**: the human labeled *intent* ("set up
  CI"); the sessions touch config AND code files, so file-type purity rules miss
  them. Needed signal: which file was the *point* vs incidental — invisible without
  content or at least file-level edit ordering weights.
- **single_file_bug_fix (0/2)**: bug-fix vs small feature is intent, not shape; a
  one-file small diff looks identical in both. (Externally corroborated: on the 202
  eval-harness sessions below, where ground truth IS bug-fixing, the same rule
  recovers it at 71% — the shape works when the traffic really is bug-fix-shaped;
  it cannot *distinguish* on shape alone.)
- **agent_meta_work over-fires on this repo specifically** (4 residual FPs): when the
  product being built is agent tooling, "editing CLAUDE.md/agent config" and "doing
  product work" are the same file touches. The class boundary is ill-defined for
  agent-tooling repos — an interview question, not a rule fix.
- **Zero-edit shell windows (R08) are honestly unclassified** and are the largest
  unclassified contributor: exploration vs ops vs verification cannot be separated
  from call counts. 5 of them were human-labeled exploratory_qa.
- **Flow context is invisible at prompt grain**: 4 ui_verification_loop windows with
  zero browser calls in-window were labeled by the human from surrounding context.
  Neighborhood features (adjacent-window signals) are the obvious 0.2.0 candidate.

## Real-traffic mix (this machine, extracted 2026-08-10)

287 sessions / 864 prompt units / 295 segments. Unclassified share: 17% prompt /
14% segment / 11% session — reported, never dropped.

- **Cohorts matter**: 202 of 213 claude_code sessions are eval-harness replay runs
  (identified content-free via provenance paths). Classified blind, they come out
  **71% single_file_bug_fix** — an accidental end-to-end sanity check, since that's
  what they actually were. Reported separately from organic traffic throughout.
- **Organic prompt mix, claude_code (n=113)**: exploratory_qa 27%, feature 22%,
  unclassified 21%, ui_verification_loop 18%, agent_meta 8% — directionally matching
  the ADR-0002 hand-label distribution (30/23/27), which is weak-but-real evidence
  the content-free instrument tracks the content-informed one at mix level even
  when per-label agreement is 53%.
- **Codex organic (n=549 prompts)**: exploratory_qa 46%, feature 31% — Codex traffic
  on this machine skews conversational/exploratory vs Claude Code's edit-heavier mix.
- **Cursor**: session-grain only (no per-message data exists; ADR-0004) — 60%
  exploratory_qa, 37% feature at session grain.
- **Automated flag changes the mix dramatically**: organic automated sessions
  (subagents, auto-review) are 86% exploratory_qa vs 51% for unmarked/human sessions
  — agent-spawned work is read/explore-dominated. Any usage report that pools
  automated with human traffic overstates exploration share.

## The weak-validation statement (per instruction, in plain words)

83 prompt labels (81 validatable) from ONE solo developer's greenfield sessions,
labeled by the same person who built the classifier, is a weak validation set. The
per-class numbers above have single-digit support for 7 of 10 classes; κ=0.41 is
"moderate agreement" on a set this small and this homogeneous. These numbers license
exactly one claim: content-free classification is partially viable (strong on
exploratory_qa and browser-verification, blind to intent distinctions) — they do not
license mix-level claims about anyone else's traffic. Enterprise labels from
multiple engineers are the promotion gate, as ADR-0002 already said.

## Decisions

- rules-0.1.1 frozen; adjustments beyond the disclosed round require new labels, not
  re-tuning against these 81.
- Segmenter 0.1.0 = calibration reference behavior (tool-result interrupts only);
  conventions.md annotated.
- prompt_unit schema (0.1.1) added to the contracts; connectors emit units for
  claude_code + codex; cursor documented as session-grain only.
- Follow-ups, in value order: neighborhood features for flow context (0.2.0),
  enterprise/multi-rater labels, LLM-judged labeling of a larger local sample to
  widen n before any learned classifier (conventions gate).

## Postscript (2026-08-23)

Infrastructure finding 1's "observed retention ≈ days" was an n=1
over-generalization: the vanished log had crossed Claude Code's ~30-day
`cleanupPeriodDays` boundary, not a 3-day window. Measurement and corrected
per-source retention model in the ADR-0011 postscript. The structural
conclusion stands — logs do rotate and continuous extraction remains a
product requirement — but the window is ~10x wider than this finding
implied.
