# 0020. Context-compilation measurement: prompt-side size signals first

Date: 2026-09-01
Status: accepted

## Context

Caliper's measurement surface has been blind to the context a prompt *arrives
with*. No field anywhere recorded prompt size — no character count, no
paste/attachment signal — and the claude_code connector saw `"attachment"`
records and skipped them as bookkeeping. Meanwhile the working hypothesis from
the user's industry conversations is that **compiling context efficiently is
the loudest pain in enterprise agent workflows**, which are context pipelines
(design artifact / ticket → internal wiki → agent → tests → prod) with the
agent in the middle and the human doing the compilation upstream.

Evidence discipline for that claim: as of this ADR it rests on **one recalled
conversation set, not yet re-verified against its recordings**. The count — N
of M interviewees raising it, unprompted vs prompted — will be stated here in
a postscript once the recordings pass is done; if it turns out to be one
emphatic voice, this section will say so and any surface framing weakens
accordingly. The fields below do not depend on that outcome: a measurement
surface that cannot see prompt size is a gap regardless of how loud the pain
was.

Two design hazards taken as constraints:

- **The inversion hazard.** An in-session, tool-call-based "assembly" metric
  sees only the gathering the *agent* performs. Where a human compiled the
  context upstream and pasted it in, tool calls report LOW assembly cost
  exactly where human cost is highest. So the pre-compiled-context signal must
  come from the **prompt side**, and any tool-call partition must be labeled
  *agent-performed assembly*, never total compilation cost.
- **The iteration loop.** Supervised work is multi-pass — context is drip-fed
  across prompts as failures surface — so size signals must live **per prompt
  unit**, making the profile (front-loaded dump vs incremental drip) visible.

## Decision

**Landed with this ADR — `prompt_unit` 0.1.1 → 0.2.0 (widening):**

- `prompt_chars` (integer|null, observed): character length of the
  user-authored prompt text. claude_code: the prompt turn's text content;
  codex: the `user_message` payload's `message` string. A size, never the
  text — records stay content-free. Verified in real logs before marking
  observed: 135 organic claude_code prompts surveyed on this machine —
  median 229 chars, p90 5,724, max 109,236. That max is the signal this field
  exists for: a hundred-kilobyte prompt is pasted context, not typing.
- `image_pastes` (integer|null, observed): count of images attached to the
  prompt where the log records them (claude_code `imagePasteIds`; codex
  `images` + `local_images`). **null is "not recorded", never zero** — older
  log versions omit the key entirely, and absent is not zero.
- cursor emits no prompt units (ADR-0004); its absence stays stated, not
  imputed.

**Surveyed and deliberately NOT counted: attachment records.** The live
attachment stream on this machine (2,272 records over the newest 8 sessions)
is almost entirely harness bookkeeping — `total_tokens_reminder` 1,498,
`batching_reminder_sent` 382, `bash_output_audience_note` 116,
`edited_text_file` 53 — not user-supplied context. Counting attachment records
as "compiled context" would measure harness chatter and re-create the
inversion hazard one layer down. If a future log version distinguishes
user-added attachments, that gets its own postscript here.

**Designed here, landing in follow-up changes (each referencing this ADR):**

1. **Iteration profile (passes-per-task):** prompts per session/segment,
   interrupt rate, gap structure, and — with `prompt_chars` — context added
   per pass. Derived from existing prompt-unit fields plus the segmenter; no
   new schema.
2. **Agent-performed assembly partition:** a versioned rule table mapping tool
   families to gather / produce / verify, applied to `window.tool_counts`
   (session `tool_call_pattern` fallback for unit-less sessions, mirroring the
   classifier's fallback). Output labeled *agent-performed assembly* wherever
   it renders.
3. **Surface:** a compilation panel in report+serve through the shared
   `summarize()` layer — size distribution beside assembly share, each with
   its n, cohorts never pooled, and the un-observed upstream human gathering
   named in words on the panel as a limitation.
4. **One-shot replay caveat:** wherever replay eval rates render, a caveat
   travels beside ADR-0007's contamination caveat: replay measures
   single-prompt completion; the real supervised workflow is multi-pass with a
   human steering, so replay rates are a lower bound on the supervised
   workflow (and the closest analogue to autonomous ticket-completion
   traffic).

## Consequences

- The pre-compiled-context profile becomes measurable per prompt, per
  session, per cohort — content-free, from data the extractor already reads.
- Old prompt-unit records stay at 0.1.1 on disk; the store re-emits at 0.2.0
  as sources are re-processed (watermarked runs touch changed files; the
  daily full pass heals the rest). Aggregates over the field must treat
  0.1.1-record absence as null, not zero.
- The upstream human compilation cost itself (time in Figma/Glean/wikis)
  remains unobservable to Caliper and is stated as such wherever the panel
  renders — measuring its *artifact* (how much context arrived pre-compiled)
  is the honest proxy, not a substitute.
