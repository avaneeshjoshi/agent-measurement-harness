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
- The upstream human compilation cost itself (time in design files, the internal search tool, wikis)
  remains unobservable to Caliper and is stated as such wherever the panel
  renders — measuring its *artifact* (how much context arrived pre-compiled)
  is the honest proxy, not a substitute.

## Postscript (2026-11-05): the recordings pass — context-compilation pain is concentrated, not universal

**Source.** Six engineer interviews were held on 2026-09-01 at a large
enterprise engineering organization; **five have transcripts, so every
denominator below is 5**, indexed I1–I5 (one interview has no transcript and
is not counted). Plus one buyer-side call (2026-08) with an engineering
leader at the same organization. All transcripts were read in full for this
postscript; they are private material kept outside the repository, and
nothing identifying — people, employer, sector, internal product names —
appears here. Internal tools are named by function only. The interviewer led
several threads; "unprompted" below means the engineer introduced the topic
before being asked.

**The count this ADR promised.**

- Raised context compilation / discovery as a **major** cost, unprompted:
  **2 of 5** (I4, I5). I4 — the one engineer on rotating assignments across
  systems he does not own — put roughly **70–80% of his token spend** on
  discovery: understanding unfamiliar architectures, generating sequence
  flows, comparing design approaches. He volunteered that this makes him
  the exception ("I don't know if anyone said this") and that domain owners
  are inverted: once they know what to do, implementation is fast. I5
  called context management "the major challenge people face" and is
  engineering around it (graph + vector code indexing, a pre-model hook
  that strips redundant tool output before it reaches the LLM, both
  explicitly "to save tokens").
- Raised it unprompted as a **bounded** cost: **1 of 5** (I1). Feeding
  context for a brand-new feature is iterative design work; for an
  enhancement the context already exists in repos, PRDs and prior design
  docs, and design is fast.
- Did **not** raise it as a pain: **2 of 5** (I2, I3). I2, when the
  interviewer proposed it, agreed that the speedup comes from the agent
  assembling context across systems — context assembly as the *gain*, not
  the cost. I3 treats requirements gathering as a routine phase (spike
  ticket → internal search → implementation plan).
- Only one interviewee attached a share to it (I4's 70–80%). No one else
  quantified.

**Reading: concentrated, not universal.** Per this ADR's own clause, the
surface framing weakens accordingly: the compilation panel (follow-up 3)
renders as a **per-cohort, per-task-class measurement, never a headline**,
and must be able to show a cohort where compilation cost is small. The
`prompt_chars` signal itself stands — it measures what arrived pre-compiled
regardless of who paid to compile it, and I4's profile is exactly what it
exists to make visible.

**Findings this ADR lacked, supported by the transcripts.**

1. **Context is not one thing; it differs by work type.** Feature work
   compiles ticket/PRD or design-file + design-system library + prior
   decisions (I1–I4). Bug work compiles **monitoring signals, production
   traffic, logs, and the up/downstream service dependency graph** — I5's
   load-bearing example is an API that looked broken in the code and was
   simply receiving no production traffic; "no bug ticket comes as 'code
   has a problem'". Design *intent* (why a decision was made) is not in the
   code and was never written for an agent to read (I5). A compilation
   metric that pools feature and bug work measures nothing; the panel
   splits by task class or does not render.
2. **The planning artifact, not the ticket, is the unit of work (4 of 5:
   I1, I3, I4, I5).** An implementation plan or ADR is produced, reviewed
   by the team, and *becomes the prompt* per PR or subagent; PR review
   cycles shrink because reviewers already know the plan (I1: PRs merge
   within ~2 hours of creation). One plan fans out into many small PRs
   (I1, I3, I4, I5) — the chunked-commit reality ADR-0019's one-edge-per-
   commit file-overlap matcher assumed, now stated independently. This
   moves the measurement boundary upstream of the session and makes
   ADR-0019's chain-rate the empirical form of the ADR-0002 unit question.
3. **Speedups, as stated:** I2 two days → two hours ("with the unit tests");
   I3 a week → a day, with a hard human-approval floor before production set
   by the organization's compliance posture ("without that, it's just
   blazing"); I1 a week → minutes for one repetitive multi-locale setup
   task once captured as a skill. I2, asked directly: failure rate
   unchanged — "not increased, not reduced; just faster".
4. **Autonomy is further along than assumed (2 of 5).** I5: a headless
   agent picks up a ticket on creation and proposes a PR (human review
   required; his bug-triage prototype's self-estimated confidence is
   ~40–50%, target 70–80%). I3: the agent merges PRs and transitions ticket
   states, gated on comments resolved + approval + passing tests, each step
   a deliberately narrow skill ("merge PR" checks only that, nothing else).
5. **Engineers route models and trim tokens themselves, unprompted.** I3:
   the mid-tier model for implementation and, given a good plan, for
   planning too; many turns of a cheaper model "probably cost the same" as
   one pass of the frontier model — the ADR-0008 shape, stated by someone
   who added he had not measured it. I5: the pre-model output-stripping
   hook and the index work above. I2 uses an indexing editor to comprehend
   an unfamiliar codebase and a different agent to implement.

**Buyer-side call (2026-08).** Three problems named: getting organizational
knowledge into models; cost and efficiency via routing ("harness
engineering"); and proving ROI on token spend to leadership, where PR and
ticket counts "don't convey anything" and what is wanted is value moved
from conception to customer. Pushback: turning codebases into skills has a
low barrier to entry and will be built in-house; what is wanted is durable
and horizontal. The third problem is this product's goal, stated by a
buyer.

**Consequences for the follow-ups.** Follow-up 3 (the compilation panel)
is per-cohort and per-task-class or it does not ship. Follow-up 1 (the
iteration profile) stands. The trace layer's chain-rate (ADR-0019) is the
measurement that reaches the planning artifact and is the priority
consumer to build. The replay caveat (follow-up 4) stands and gains I2's
"unchanged failure rate" as the kind of production-side figure replay
cannot see.
