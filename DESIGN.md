**Purpose:** Defines the Caliper visual and interaction system: how the product must feel, the complete token system, layout, primitives, composition rules, state presentation, and the patterns that are prohibited. This document must be concrete enough to reject an unattractive implementation in review.
**Authoritative for:** product feeling, visual references, design tokens, typography, layout, primitive components, composition rules, signature elements, information architecture of the three surfaces, state presentation (of states defined in PRODUCT.md and the schemas), interaction, accessibility, keyboard behavior, responsive and overflow behavior, prohibited patterns.
**Not authoritative for:** what states mean (PRODUCT.md and `schemas/` — this document presents their state names verbatim and may not add, rename, or merge states), system mechanics (ARCHITECTURE.md), status (PROGRESS.md), why a rule exists (`docs/decisions/`).
**Update when:** a state is added or renamed upstream (same change); a token, primitive, or rule is added or changed — token and primitive changes require an ADR in `docs/decisions/`.
**Last reviewed:** 2026-08-23

# Design

This document governs every surface Caliper renders. Until it is changed — and changing it means an ADR, not a preference — an implementation that contradicts it fails review, and "it looked better this way" is not an argument that survives the check.

## Product feeling

Caliper must feel: calm, precise, premium, quietly technical, comfortable during long sessions, trustworthy, purposeful, unhurried.

It must not feel: like a generic AI dashboard, like an admin template, like a vendor analytics product, theatrical, persuasive, decorative, cheap, like every surface came from a separate prompt.

The resolving rule — every surface is checked against it: **rigor in the data, generosity in the frame, restraint in the claim.**

And the standing correction: **quiet, plain, and few.** What a serious measurement instrument would ship — one ground, one weight of edge, generous space, numbers doing the work. No glow, no gradient, no stacked panels inside one box, no control that announces itself, no color that flatters a result. If a treatment exists to make something *look* designed rather than to make a number readable or its uncertainty visible, it is wrong here. Concretely, and checkable in review: every rate on screen sits beside its `n`; nothing inside a bordered container carries a second border; no figure is emphasized because it is favorable.

- *Structure is technical*: dense rows, tabular numerals, monospace for shas, paths, model ids, commands, and every measured figure; precise 1px separators; keyboard-first affordances in the CLI.
- *Frame is generous*: real outer margins even when rows are dense, warm neutrals rather than clinical white, soft radii on anything interactive, nothing crowded against an edge, gentle motion where motion exists at all.
- *Voice is restrained*: the caveat sits beside the number, never in a footnote. No adjective the data has not earned. Where the instrument is uncertain the copy says so in the same sentence as the finding, and where it cannot know it says "not recorded" rather than nothing.

The third clause is the one that is Caliper's alone. Every other measurement product on the market renders a confident number. This one renders the number and its doubt in the same breath, and that is the whole differentiation — expressed visually, not just in the methodology.

## Visual references

Structural study only — never copy branding, layout pixel-for-pixel, wording, or decorative identity.

- **A laboratory notebook.** The reference posture for the report: a dense record on warm paper, in which the measurement, the conditions, and the doubt are recorded together and none is styled to outrank the others. Borrow: warm ground, tight tabular structure, marginal notes as first-class, the absence of persuasion.
- **An oscilloscope readout.** The reference posture for the CLI: a monospace instrument face where the trace is the subject and the chrome is a frame around it. Borrow: monospace primacy, one accent, motion only where something is genuinely happening.
- **A financial statement.** The reference posture for cost surfaces: figures right-aligned in tabular numerals, every total decomposed into its parts, every number traceable to a line item. Borrow: arithmetic that reads straight down a column, footnote discipline, no figure without its basis.
- **What is deliberately not a reference:** engineering-analytics dashboards, observability products, and every AI-usage tool currently shipping. They render scores. Caliper renders measurements with their uncertainty attached, and a surface that could be mistaken for one of those has failed.

Caliper's own signature is none of these: it is the uncertainty pair, the absence rendering, the evidence line, the caveat that travels, and disagreement reported rather than resolved (see [Signature elements](#signature-elements)).

## Tokens

Every visual value in the product comes from this section. A literal hex, px shadow, one-off radius, or unlisted type size in component or CSS code fails review.

Two themes exist: **light is the default and the reference**; dark is a token-for-token override. Light is the deliberate choice, not an oversight — a measurement record reads as paper, and dark is what every AI product already is. Components never branch on theme; they consume tokens only.

### Color

Warm, restrained, light system. No decorative gradients, no neon, no glow, no glassmorphism, no large colored panels. **Color is semantic or absent**, and in this product one of the semantics is absence itself.

| Token | Value | Meaning |
| --- | --- | --- |
| `--bg` | `#FAF9F6` | Application background — warm paper, never pure white |
| `--surface-1` | `#FFFFFF` | Primary surfaces: cards, the report's sections |
| `--surface-2` | `#F2F0EC` | Recessed surfaces: table header rows, caveat blocks, code blocks |
| `--edge` | `#000000` at 10% | Default border; 16% hover |
| `--edge-strong` | `#C9C5BE` | Structural lines that must be seen at a glance: a table's header rule, a section boundary |
| `--text-1` | `#26241F` | Primary text (warm ink) |
| `--text-2` | `#5D594F` | Secondary text (warm gray): metadata, labels, units |
| `--text-3` | `#8B867D` | Faint: timestamps, disabled — never the sole carrier of information |
| `--accent` | `#1F4A38` | Deep green: focus, the active state, the one emphasis. Authority is a single dark hue, never a bright one |
| `--measured` | `#4F7A4A` | **Verified measurement only** — a value that cleared its gate, on the evidence it actually has. Never "good", never "success" |
| `--provisional` | `#A15F28` | Attention, incomplete verification, a claim above its evidence, a gap or drift warning |
| `--absent` | `#8B867D` on `--surface-2` at 40% | **"Not recorded" and nothing else.** Absence is a first-class state in this product and it gets its own token so it can never be mistaken for a value. Rendered in italic small-caps, never as a dash, never as a blank cell, never as zero |
| `--danger` | `#A8443A` | Failure, a broken guarantee, a destructive action. Never a low score |
| `--diff-add` / `--diff-del` | `#1A7F37` / `#CF222E` | Code diffs only, as 12%/10% washes with a 2px inset edge — identification of change, never judgment of it. Nowhere else |
| `--cat-1` … `--cat-10` | `#4A6B8A` `#8A5A44` `#5E7D54` `#7A5E80` `#9A7B3F` `#4F7D7B` `#8A4F5E` `#6B6B5E` `#5A5F8C` `#7D6B4F` | **Chart categories only** (ADR-0017): muted, similar-saturation hues that identify a series in a chart, never judge it. Assignment is by fixed order (task types in taxonomy order; chart groups by rank), so a category keeps its color within a page. `unclassified` never takes one — it renders in `--absent`'s color because it is the instrument's own absence; `other` renders in `--text-3`. Color never carries a category alone: the legend word and the paired table always do |

**Semantic lock:** a token may not be used outside its meaning. `--measured` on a passing count that has not cleared its agreement gate fails review exactly like a raw hex does. `--measured` on anything that is not a measurement — a UI success state, a completed download — fails the same way. Anything not covered by a semantic token renders in neutrals.

**The green rule.** `--measured` appears only where a measurement is both taken and qualified: a survival figure with its `n`, a solve rate with its sample, a check that ran and passed at the current revision. A rate without an `n` beside it may not be green under any circumstance, because the color would be claiming a confidence the figure has not earned. This is the single most-violated rule in practice and the first thing a reviewer checks.

Dark theme overrides: `--bg #0F0F0E` · `--surface-1 #191917` · `--surface-2 #232320` · `--edge` white 11% (18% hover) · `--edge-strong #4A4843` · `--text-1 #F7F5F2` · `--text-2 #B6B1A8` · `--text-3 #8B867D` · `--accent #8FBFA4` · `--measured #8FAE8B` · `--provisional #D9A47E` · `--absent` `#8B867D` on `--surface-2` at 40% · `--danger #C97B6F` · `--cat-1…10` `#8FB0CC` `#C49A83` `#9DBA92` `#B79ABD` `#CDB075` `#8FB5B3` `#C48D9C` `#A8A895` `#9FA3C9` `#B3A183` (ADR-0017). Same contrast obligations as light.

Interaction states: row hover `#000000` at 4%; selected `#000000` at 6% (a background wash only — no accent bar, no outline); pressed 6%. Disabled controls: 40% opacity, no hover response, default cursor.

#### Terminal palette

The CLI renders inside a terminal it does not own. Three obligations, and they are not optional:

- **Truecolor is pinned, not inherited.** The palette above is emitted as explicit 24-bit sequences so a user's terminal theme cannot recolor a semantic. A `--measured` green that becomes the user's "success" color has stopped meaning what this document says it means.
- **256-color fallback** maps each semantic to its nearest cube entry, and the mapping is recorded in `cli/style.py`, not chosen at render time.
- **`NO_COLOR` is honored absolutely.** With color gone, every semantic must still be legible: a measured figure keeps its `n`, an absent value still reads "not recorded", a warning still reads as a warning in words. If removing color removes information, the surface was relying on color alone and fails review.

### Typography

- UI family: **Inter** (fallback: system-ui). Mono: **JetBrains Mono** — and in this product mono carries more than usual: every measured figure, every sha, path, model id, p-value, token count, and command renders mono. A number in a proportional face reads as prose about a number rather than the number itself.
- Complete scale (size/line-height, weight). No other sizes exist.

| Step | Use |
| --- | --- |
| 11/16, 500, tracking +0.06em, uppercase | Micro labels: section eyebrows, column headers, unit labels |
| 12/18, 400 | Metadata, timestamps, provenance lines, the `n` beside a rate |
| 13/20, 400 | Dense rows: tables, task-mix rows, per-repo outcomes |
| 14/22, 400 | Body prose, caveat text, method description |
| 16/24, 600 | Section headings |
| 20/28, 600 | Surface titles |
| 32/38, 600 | **The headline figure** — one per surface at most: the total, or the finding the surface exists to state. Nothing else uses this step |
| 48/54, 650 | **Display** — the website hero alone. Nothing inside the CLI or the report ever uses it |

- Weights available: 400, 500, 600. Nothing bolder.
- **Tabular numerals everywhere a number appears.** Not "wherever numbers align" — everywhere. A column of rates that does not align is a column a reader cannot scan.
- Hierarchy floor: every surface uses ≥3 distinct steps. Secondary and faint text are limited to metadata and labels; any sentence a reader must act on is `--text-1`.

### Spacing, grid, measure

- Spacing scale (px): 4, 8, 12, 16, 24, 32, 48, 64. No other values.
- Grid: 8px base; table rows 32–36px; pointer targets ≥32px.
- Measure: prose caps at 680px. Tables are unconstrained but scroll horizontally inside their own container. Report outer margins 32–48px. The report's own content column is centered.
- CLI: content wraps at 80 columns where the terminal allows, and never renders a bar chart wider than the narrowest terminal it supports.

### Radii

6px — inputs, rows, small controls, buttons (squarish, never pill-adjacent) · 10px — contained cards and the report's sections · 14px — dialogs and the caveat block · full — never, in any surface. Radii come only from this list.

### Elevation

- Level 0: none (default; separation by spacing and 1px edges). This is the overwhelming majority of the product.
- Level 1: `0 1px 2px rgb(0 0 0 / 0.06)` — sticky headers, popovers.
- Level 2: `0 8px 24px rgb(0 0 0 / 0.10)` — dialogs only.
- No colored shadows, no text-shadow, no blur >24px.

### Focus

A 1px `--accent` ring at 2px offset, on `:focus-visible` only — never removed. A text field shows focus on its own edge rather than wearing a second one. In the CLI, focus is the selected row's wash plus its `⬢` marker; there is no second indicator.

### Motion

- Durations: 120ms (hover/press), 180ms (reveal/collapse), 240ms (overlays). Easing: `cubic-bezier(0.3, 0.7, 0.3, 1)`.
- Motion only on state change. No entrance animations, no parallax, nothing animates unprompted, no number counts up.
- Exactly one element may loop: the working indicator while a long operation runs (extraction, a replay batch, a signals pass) — a 1500ms opacity cycle, the only looping duration in the product.
- Respect `prefers-reduced-motion`: all motion drops to opacity-only.
- **A chart never animates in.** A measurement that draws itself is theater, and the reader cannot tell a slow render from a slow measurement.

### Icons and marks

- One approved set (stroke style, 1.5px stroke, 16px default). No icon without adjacent text.
- **The hex bullet is the CLI's one mark**: `⬢` filled for a completed or active step, `⬡` hollow for a pending one. It is the only glyph that carries meaning without words, and it carries only that meaning.
- **Bar charts are eighth-block characters** (`▏▎▍▌▋▊▉█`) in `--accent`, one row per item, the value and its unit as text at the row's end. A bar is never the only carrier of a value — the number is always beside it.
- No emoji anywhere in chrome, states, output, or documentation headers.

### Status semantics

**Status is stated in words, never as a pill, never as a dot, never by color alone.** "measured", "not yet measurable", "not recorded", "draft", "turn-capped", "unclassified" — the word is the signal. Where a state deserves emphasis it takes weight (500) or a semantic text color within its meaning, never a decorative mark.

The one sanctioned use of color on a bare number is arithmetic that already states its own direction: `+142` / `−87` in a diff, where the sign says which way it goes and the color agrees with the sign rather than replacing it.

## Signature elements

Five elements make a surface recognizably Caliper. They are the only permitted uses of their respective treatments, and they render identically on the CLI, the report, and the website.

**1. The uncertainty pair.** No rate, percentage, or aggregate appears anywhere without its sample size adjacent to it, in the same visual unit, at the metadata step. `67% (n=30)`. `99% survival (n=19 commits)`. `53.1% agreement (n=81, κ=0.41)`. Where a comparison has been tested, its p-value travels the same way: `no detectable difference (p=0.645)`. This is not a footnote convention and it is not optional on small surfaces — a figure that appears without its `n` is a figure claiming more than it knows, and it fails review wherever it appears. In the CLI the pair is `--text-1` for the figure and `--text-2` for the `n`; in the report the same; on the website the same. One rule, three surfaces, no exceptions.

**2. The absence rendering.** A value the instrument does not have renders as `not recorded` in `--absent`, italic, at the metadata step — never as `0`, never as `—`, never as an empty cell, never omitted from the row. Absence is a finding: Cursor logs carry no tokens, so Cursor spend is not recorded and never zero; a commit younger than its horizon is `not yet measurable` and never 0% survival; a model absent from the price sheet is `not priced` and never $0.00. Each of these has its own word and the words are not interchangeable. A reader must be able to tell "we looked and there was nothing" from "we could not look" from "the answer is zero" at a glance, and the tokens exist so they can.

**3. The evidence line.** Every claim carries, in the metadata step beneath or beside it, what it rests on: the record file, the test name, the ADR, the run id, or the date of the price sheet. `source: data/extracted/*/sessions.jsonl → tokens, models[]`. `ADR-0007 · 90 runs · 2026-08-10`. This is the glass-box principle made visible, and it is what separates a Caliper surface from a dashboard: a reader who does not believe a number can find the thing that produced it without asking anyone.

**4. The caveat that travels.** Caveats render in the same view as the numbers they qualify, in a `--surface-2` block with a `--provisional` left edge, at the body step — never collapsed, never a modal, never a link to a methodology page. The block states what the numbers cannot support, in plain sentences, and it appears at the foot of every surface that renders measurements. On a surface where the caveats would not fit, the numbers do not fit either. Contamination, solo-data limits, classifier agreement, retention loss, sample size — each travels with the surface that inherits it.

**5. Disagreement reported, never resolved.** Where two measurement tracks address the same question and differ, both render, adjacent, with the disagreement stated in words. There is no averaged figure anywhere in the product because there is no field in the schemas that can hold one. A surface that shows a single reconciled number where two tracks disagreed has fabricated it, and that is the failure this element exists to prevent.

## Information architecture

Caliper renders three surfaces. They are different media with one visual system, and a reader who sees two of them must recognize the same product.

### 1. The CLI

The primary surface, and the one most users will see most often. Staged, sequential, never a dashboard rendered in text.

- **The command is the navigation.** `setup`, `extract`, `signals`, `classify`, `report`, `replay`, `policy`, `pricing`, `schedule`. Each prints what it did and stops. There is no menu, no persistent chrome, and no interactive shell.
- **A step is `⬢` plus its name plus its facts**, one line, the facts in `--text-2`. Steps that are pending in a staged flow render `⬡`. A step that produced numbers renders them as an indented block beneath it, never inline in the step line.
- **The staged flow (`caliper setup`)** is: trust screen → collection choice → per-source backfill → classification → signals → report → highlights → policy question. Each stage completes visibly before the next begins. A stage that is skipped says why in one line rather than disappearing.
- **The trust screen is prose, not a list of features.** It states exactly what Caliper reads, exactly what it never reads, and where what it writes will live. It is the one surface in the product allowed more than four lines of continuous prose, because it is asking for permission and permission needs a reason.
- **Highlights are bar charts with their figures**: spend by tool, spend by model, work mix, outcomes. Bars are share-of-total so their lengths mean the same thing across charts, and the total is stated in the section header so the parts are visibly parts.
- **Warnings interrupt; information does not.** A collection gap or a drift alarm renders as a bordered block in `--provisional` before the command's own output. Everything else renders in flow.
- **Long operations show one working indicator and a count**, never a percentage the instrument cannot compute honestly and never an ETA.

### 2. The report

One self-contained HTML file, no network, no build step, regenerable by one command. It is the artifact a user sends to someone else, and it must look like the product that produced it.

Order is fixed, because it is an argument: **headline band → spend → task mix → outcomes → coverage and honesty.**

- **The headline band** carries the total, the session count, the date range, and the coverage percentage. One `32/38` figure, the rest at metadata. It answers "how much, over what, how completely" before a reader scrolls.
- **Spend** decomposes that total: by model, by tool, by project, by day. Every table is share-of-total with the figure and the percentage. Token buckets are always four and always separate — input, output, cache read, cache write — because cache traffic dominates real usage and a view that hides it misprices everything (ADR-0005).
- **Task mix** renders by cohort, never pooled. Automated and human traffic mix differently enough that pooling distorts the result (ADR-0009), so they render as separate rows with their `n`. Unclassified is a column, always visible, never dropped.
- **Outcomes beside cost** is the section nothing else in the market produces, and it is the report's center of gravity: one row per repo carrying commits, survival with its `n`, rework, attribution as known/partial/unknown, and that repo's cost. It renders at full table density with no chart, because the join is the point and a chart would obscure it.
- **Coverage and honesty** closes the document: per-tool session counts, join rates, what has tokens and what does not, date ranges, and the caveat block. It is not an appendix. A reader who stops before it has read half the document.

Every table states its source beneath it. Every rate carries its `n`. Every absent value renders as absent.

### 3. The website

One page, one decision, one artifact.

Order: **hero → the evidence artifact → what works today → privacy and trust → limits and roadmap → method → conversation.**

- The hero states one decision a reader is facing, in one sentence at the display step, and nothing else competes with it.
- The evidence artifact is a real measurement with its real caveats, rendered in the report's own visual language so a visitor sees the product before they read about it.
- Limits render at the same weight as capabilities. A roadmap item is marked as roadmap in the same line that describes it, never in a footnote a scanner will miss.
- There is no testimonial, no logo wall, no metric without its measurement, and no claim the repository cannot support.

## Layout

- Each surface declares one **primary region** occupying ≥55% of its width. No two regions may have equal visual weight.
- **Machinery is subordinate**: run ids, schema versions, salted refs, connector versions render at the 11–12px steps in `--text-2/3`, in provenance lines and coverage tables — never in a headline, never beside a figure it does not qualify.
- Prose lives in caveat blocks, method sections, and the trust screen. Everywhere else, rows and figures.

### Density

Dense where data is (tables, mix rows, per-repo outcomes: 32–36px rows, 13/20 type); relaxed where frame is (32–48px outer margins, 24–32px section gaps). Density never comes from shrinking type below the scale, and generosity never comes from inflating rows.

### Overflow

Wide tables scroll horizontally inside their own container, never by making the page wide. Long tables truncate to their top rows with a stated count of what is not shown — `+ 4 more models · $1.21 · 0%` — never with an unlabeled cutoff.

### Responsive

The report and website reflow to a single column below 900px. Tables become scrollable in place; nothing that carries a number is hidden. The CLI adapts to terminal width by narrowing bars, never by dropping the figures beside them.

### Accessibility

Text contrast ≥4.5:1 for every text token on every surface it may appear on. `--text-3` and `--absent` stay restricted to metadata and absence, and are never the sole carrier of information. **Status is never conveyed by color alone** — the word is always present, which also means the product survives `NO_COLOR` and monochrome printing intact. Full keyboard operability in the CLI's selectors; visible focus everywhere; `prefers-reduced-motion` honored.

### Keyboard (CLI)

Arrow keys move a selection, `Enter` confirms, `Esc` declines and is always equivalent to the conservative choice. A prompt with no TTY takes the conservative default and prints what it chose and how to change it — a non-interactive run never silently installs, enables, or opts in.

## Primitives

These are the only primitives. Feature code composes them; it never invents local styling and never adds an arbitrary color, radius, shadow, gradient, type size, or spacing value.

`Figure` · `FigurePair` · `Absent` · `Table` · `Row` · `Bar` · `Step` · `Section` · `Separator` · `CaveatBlock` · `EvidenceLine` · `Warning` · `Button` · `Select` · `Dialog` · `CodeBlock`

Composition rules:

- **`Figure` may not render alone.** It composes into `FigurePair` — the value and its `n` — everywhere a rate, percentage, or aggregate is shown. A bare `Figure` is legal only for a raw count that is not a rate (a session count, a commit count, a dollar total).
- **`Absent` is a primitive, not a string.** Rendering "not recorded" by hand fails review; the primitive carries the token, the italic, and the semantic so absence looks identical everywhere it appears.
- **`EvidenceLine` is required beneath every `Table` and every `Section` that renders measurements.** A section without one is a section making an unattributed claim.
- **`CaveatBlock` appears at the foot of every surface that renders measurements.** It is never collapsed and never behind a link.
- Exactly one primary Button per surface state. Every button variant is the same height and padding.
- Maximum one border level per region: a bordered container never contains another bordered container. Nesting is spacing and type, never a second border.
- New primitives require an ADR.

## Component behavior

**The figure pair.** The value in mono at its step, the `n` in `--text-2` at the metadata step, adjacent on the same line, in parentheses. Where a confidence interval exists it follows the `n`. Where a p-value exists it follows the comparison, not the figure. The pair never wraps such that the value and its `n` land on different lines — if the container is too narrow, the container is wrong.

**The absence.** `not recorded` · `not yet measurable` · `not priced` · `unclassified` · `unmeasurable` · `excluded_generated` (ADR-0015: the commit touched only generated files — measurable, but deliberately outside the work-survival question; renders with the pattern-list version nearby). Six distinct words for six distinct absences, each carrying its own meaning and none substitutable for another. They render in `--absent`, italic, metadata step. A table cell that would be empty carries one of them instead; a row is never dropped because its value is missing, because the absence is the row's finding.

**The evidence line.** Metadata step, `--text-2`, beneath the thing it qualifies, prefixed `source:` in the micro-label style. It names a file path, a test, an ADR number, a run id, or a price-sheet date — something a reader can open. A prose description of where a number came from is not an evidence line.

**The caveat block.** `--surface-2` ground, 3px `--provisional` left edge, 14px radius, body step, one sentence per caveat, sentence-case, never bulleted with decorative marks. The heading is one line at the micro-label step: `Caveats that travel with these numbers`. It states what the numbers cannot support, and where a caveat has an ADR the ADR is named in the sentence.

**The table.** Header row on `--surface-2` at the micro-label step, uppercase, `--text-2`. Body rows 32–36px, 13/20. Figures right-aligned and tabular; text left-aligned. A `--edge-strong` rule beneath the header and nowhere else — no zebra striping, no vertical rules, no cell borders. Sort order is stated when it is not obvious, and chronological data sorts chronologically even when another order would look better.

**The bar.** Eighth-block characters in the CLI, a 1px-radius div in the report. Always share-of-total within its chart so lengths compare. The figure and its unit render at the row's end as text; the bar is never the sole carrier. Zero-length bars render as zero-length, and absent values render no bar at all with the absence word in the figure position.

**The step (CLI).** `⬢` or `⬡`, one space, the step name at `--text-1`, the facts at `--text-2` separated by ` · `. Facts, not sentences. A step that produced numbers indents them beneath it by two spaces.

**The warning (CLI).** A bordered block, `--provisional` edge, rendered before the command's own output rather than after it. It names what happened, what it means for the data, and what the reader can do — three sentences maximum. A gap warning and a drift alarm are visually identical in structure and distinguishable only by their words, because they are the same kind of event: the instrument telling the truth about itself.

**The policy presentation.** The overspend verdict, the quality-per-tier chart with its CIs, the cost-per-tier chart, the tier access status, the recommendation, and its caveats — in that fixed order, ending in the apply question. Every tier that was measured renders with its `n`; every tier that was not renders its access status rather than disappearing (ADR-0010). The recommendation renders at the body step in `--text-1`, and it is a sentence, not a badge.

**The chart (ADR-0017).** A chart exists only where it shows something a table cannot — a trend, a composition, a join — and its underlying table stays on the same page beneath it: the chart is the shape, the table is the record. Every chart states its n on or beside it; a chart without its sample size does not render. Absence is a gap (a quiet day on a time axis) or a labeled band (an unplottable point, listed with its absence word), never a zero-height bar and never a point at the origin. The figure rides the mark — row bars carry their value at the row's end, scatter points carry their label and pair beside them; a dense time series carries its figures in the paired table and in hover, which shows the exact underlying numbers. Clicking a mark navigates into the data where a destination exists (a day, a repo); where none exists the hover and the table are the way in. Colors are the chart-category tokens (or the bucket aliases) within their semantics; a legend of words always accompanies them. Nothing animates on load, no chart draws itself, and there are no donuts, gauges, or free-standing sparklines — those remain prohibited pattern 14.

**The replay grid.** One cell per (task × tier), filling in as runs land. `solved` in `--measured`, `failed` in `--text-2`, `turn-capped` in `--provisional` with the word. The grid is the only surface in the product that updates while the reader watches, and it updates by replacing cells rather than animating them.

## State presentation

Keyed verbatim to the schemas and PRODUCT.md. These names may not be renamed, merged, or replaced with friendlier words.

**Survival — `measured`.** The fraction with its `n` in commits, `--measured` only when the sample is stated. Per-commit median is the default presentation; line-weighted appears only beside it and never alone, because one generated artifact makes a line-weighted figure meaningless (ADR-0006).

**Survival — `not_yet_measurable`.** The words, in `--absent`. Never 0%, never omitted from the row. The horizon is named: `not yet measurable (30d horizon, commit is 12d old)`.

**Survival — `unmeasurable`.** The words, in `--absent`, with the reason: `unmeasurable — commit added no lines`.

**Attribution — `known` / `partial` / `unknown`.** Rendered as a triple in that fixed order — `1k / 19p / 10u` — never as a single percentage and never with `unknown` dropped. `known` never renders in `--measured`, because known attribution is symmetric: a fully-scored commit may be known-human. The reader is told what the evidence covers, not what the code was.

**Classification — `unclassified`.** A column in every mix table, always present, never zero-suppressed. Its share is a finding about the instrument, and hiding it would be the instrument flattering itself.

**Classification — `ambiguous`.** The primary label with its alternative named: `single_file_bug_fix (or feature_implementation)`. The classifier admits when two classes are not separable from metadata and the surface admits it too.

**Eval — `solved` / `failed` / `turn_capped`.** Three words, three renderings. `turn_capped` is scored as failed and rendered as `turn-capped` in `--provisional`, because a run that flailed to its ceiling is different information from a run that produced a wrong answer, and collapsing them loses the flailing signal.

**Policy — `draft`.** The word beside the policy id, in `--provisional`, with its promotion bar stated in one sentence beneath. A draft policy renders its full evidence exactly as an adopted one would; the difference is the word and the sentence, not the presentation.

**Policy — `proposed` / `adopted` / `superseded`.** The word, `--text-1`, with the date. A superseded policy stays in the record with its successor named.

**Collection — covered.** Nothing renders. Silence is the state; a product that announces its own normal operation is noise.

**Collection — gap.** A `--provisional` warning block before all other output, naming the source, the window, and the plain sentence that data in it may be permanently lost, plus the note that this is a known ~3-day retention limitation (ADR-0009) rather than a bug. The word "may" is load-bearing: rotation means the instrument cannot prove what existed.

**Collection — drift alarm.** The same block structure, naming the connector, what changed, and what it means for coverage. A drift alarm reads calm, because nothing has broken — a vendor changed a format and the instrument noticed.

**Pricing — `not priced`.** The words in `--absent` beside the token counts, which still render. A model without a price sheet entry still has its usage shown; only the dollar figure is absent.

**Pricing — list-price counterfactual.** Every dollar figure in the product renders beneath a standing statement that these are list-price equivalents and not charges, with the price sheet's effective date. On a subscription the figure is what the traffic would have cost, and that sentence appears on every surface that renders a dollar.

## Transient states

- **Loading.** Quiet placeholders in final layout positions. No shimmer, no spinner theater. In the CLI, one working indicator and a count of what is done.
- **Empty.** Left-aligned, one sentence, one action, no illustration. `No signals yet. Run caliper signals to mine them.` Never a decision surface over nothing: a policy view requires evidence, a comparison requires two things to compare.
- **Errors.** Inline at the failure site, `--danger` text plus a recovery action. A malformed source file is a skip with its reason, not an error — the skip is data.
- **Refusal.** Where the instrument declines to guess — a shell-only window with no edits, a class it cannot separate — it says so in words and the outcome is recorded as `unclassified`. Declining is a legal result, and the surface presents it as one rather than as a failure.

## Prohibited patterns

Each rule is testable in review; violating any one fails the review.

1. No rate, percentage, or aggregate without its `n` adjacent to it.
2. No `--measured` green on a figure that has not cleared its gate, or on any figure without its `n`.
3. No absent value rendered as `0`, `—`, or an empty cell; `Absent` is a primitive and it is the only way.
4. No chart without its sample size stated on or beside it.
5. No averaged figure where two measurement tracks disagree — both render or neither does.
6. No caveat collapsed, linked away, or placed on a surface other than the one carrying the numbers it qualifies.
7. No table or measurement section without an evidence line.
8. No CSS gradient functions anywhere.
9. No raw color values in component or CSS code; tokens only, used within their semantic.
10. No glow: shadows only from the elevation scale; no colored shadows; no text-shadow.
11. No pills, badges, or status dots. Status is words.
12. No cards in cards; maximum one border level per region.
13. No surface with fewer than three type-scale steps.
14. No dashboard furniture: no stat tiles, no donut charts, no gauges, no sparklines standing alone. Counts are text in rows.
15. No number that counts up, no chart that draws itself, no entrance animation, no unprompted motion; nothing loops but the working indicator.
16. No machinery — run ids, schema versions, salted refs — beside a headline figure.
17. No emoji anywhere in chrome, output, or documentation.
18. No color-only status: removing color must remove no information, and `NO_COLOR` output is checked as part of review.
19. No new primitive, token, or state word without a DESIGN.md change and an ADR.
20. No library-default palette values leaking through (`blue-500` and kin fail review).
21. No claim in copy that the repository cannot support, on any surface, including the website.

**Review procedure:** any change touching a rendered surface attaches a screenshot — and for the CLI, a `NO_COLOR` capture alongside the colored one. The reviewer checks both against this list and the composition rules. Text rules alone do not catch composition failures, and color rules alone do not catch a surface that falls apart without color.