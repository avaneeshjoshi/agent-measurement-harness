# Caliper `setup` — web demo spec

Handoff for building an animated, fake-terminal demo of `caliper setup` on the
Caliper website. Everything below is extracted from the real CLI
(`cli/style.py`, `cli/setup_flow.py`, `cli/interactive.py`,
`cli/policy_flow.py`) so the demo matches the product exactly.

## 1. The design language (what makes it look like Caliper)

- **A staged product flow, not a log dump.** Each stage shows an animated
  spinner line while it "works", then the spinner line is *replaced in place*
  by a completed line. One blank line between every block. Nothing scrolls by
  fast; the pacing is the design.
- **Geometric hex bullets.** `⬢` (filled hex) = a completed step. `⬡` (hollow
  hex) = a child/detail item. The spinner is the two alternating: `⬡ → ⬢ → ⬡`
  at 400 ms per frame, in accent color, with dim label text.
- **Middle-dot separators.** Multi-part lines join fragments with a dim
  `·` (e.g. `⬢ Backfilled claude_code · 214 sessions · 2026-01-04 → 2026-08-15`).
- **Bordered boxes** (`┌─┐ │ │ └─┘`, dim borders) for the title panel and for
  interactive questions. Box width hugs the widest line + 1 space padding.
- **Bars with eighth-block precision** on a dim `░` track:
  `█` full cells + one of `▏▎▍▌▋▊▉` for the fractional cell, rest `░`.
  Chart rows: 4-space indent, dim left label (padded to widest), 22-cell bar,
  then right text (`bold $ · bold % · dim sessions`).
- **Restraint in color.** Background is never painted (the demo should sit on
  the site's own background). Only foregrounds: most text is either bold text
  color or muted gray. Accent (violet) is identity — hexes, bars, key
  commands. Green = good outcomes, yellow = caveats/preview warnings,
  cyan = names/labels and one bar family. Numbers that matter are bold.
- **Honesty as a design feature.** Unmeasured things are shown dim, never
  hidden: "3 unclassified — reported, never hidden", "not priced",
  "too young to measure survival — not recorded, never assumed".

## 2. Design tokens

Pinned RGB (the CLI pins exact colors so terminal themes can't remap them —
the web demo should use these verbatim as CSS variables):

| role   | dark               | light            | used for |
|--------|--------------------|------------------|----------|
| text   | `rgb(232,230,224)` | `rgb(43,43,38)`  | bold text, key numbers |
| muted  | `rgb(139,137,125)` | `rgb(128,126,116)` | all secondary text, box borders, bar tracks, `·` |
| accent | `rgb(129,129,245)` | `rgb(84,84,214)` | hexes, spinner, `[x]`, commands, one bar family |
| green  | `rgb(99,199,119)`  | `rgb(17,119,51)` | survival bars, good counts |
| yellow | `rgb(222,184,106)` | `rgb(154,103,0)` | caveats, "(preview …)" |
| red    | `rgb(224,108,117)` | `rgb(192,44,56)` | invalid/failed (rarely appears in setup) |
| cyan   | `rgb(108,178,202)` | `rgb(14,116,144)` | task-mix bars, tier "frontier" |

Font: any good monospace (the real thing is whatever terminal font the user
has; on the web use e.g. `ui-monospace, "SF Mono", "JetBrains Mono", monospace`,
~13–14 px, line-height ~1.45). "Bold" in the CLI = ANSI bold; on the web use
`font-weight: 600` in the text color.

Glyph inventory: `⬢ ⬡ · ┌ ─ ┐ │ └ ┘ █ ▏▎▍▌▋▊▉ ░ → [x] [ ]`

## 3. The flow, stage by stage (with demo data)

Play this as a timed sequence. `(spinner Ns)` means show the animated
`⬡/⬢ dim-label` line for ~N seconds, then replace it with the `⬢` line that
follows. Blank line after every block.

**3.1 Title box** (appears immediately)

```
┌────────────────────────────────────────────────────────────┐
│ caliper setup · first run · engineers do not change how    │
│ they work                                                  │
└────────────────────────────────────────────────────────────┘
```
`caliper setup` bold; the rest dim; `·` separators. (Real box is one line —
width hugs content.)

**3.2 Trust screen** (fades/types in as one block — this is the consent
moment, give it a beat before the question appears)

```
⬢ What Caliper reads

  ⬡ session metadata · timing, turn counts, tool patterns, models

  ⬡ token counts · all four buckets — spend is priced from these

  ⬡ git history · commit survival, rework, reverts — read-only

⬢ What Caliper never reads

  ⬡ prompt text & code · dropped at the extraction boundary; a test enforces the classifier can't see them

  ⬡ raw paths · salted-hashed at the connector; display names stay local-only

    everything Caliper does afterward is logged and inspectable (manifests per run, ADRs per decision)
```
Child lines: hollow hex in accent, name bold, detail dim after a dim `·`.
Last line is dim, indented 4 spaces, no bullet.

**3.3 Backfill question** — the interactive box. Options live *inside* the
box; `[x]` is accent, selected label bold; unselected rows fully dim. In the
demo, auto-animate: highlight moves down once then back to option 1, then
"Enter" confirms (or make it genuinely keyboard/click-interactive — nice
touch: ↑/↓/j/k and Enter work).

```
┌──────────────────────────────────────────────────────────────────┐
│ Question                                                         │
│                                                                  │
│ Start the backfill?                                              │
│                                                                  │
│   [x] Full backfill — sessions + git outcome signals (takes minutes) │
│   [ ] Quick backfill — sessions only, signals later              │
│   [ ] Not now                                                    │
└──────────────────────────────────────────────────────────────────┘
```
`Question` dim, prompt bold. Demo picks **Full backfill**.

**3.4 Backfill stages** (one per connector; spinner label →  completed line)

- (spinner ~2.5s) `Backfilling claude_code` →
  `⬢ Backfilled claude_code · 214 sessions · 2026-01-04 → 2026-08-15`
- (spinner ~1.5s) `Backfilling cursor` →
  `⬢ Backfilled cursor · 58 sessions · 2026-03-11 → 2026-08-14`

(`claude_code`/`cursor` bold, count plain, date span dim.)

**3.5 Classification**

- (spinner ~1.5s) `Classifying traffic (content-free)` →
  `⬢ Classified traffic · 816 labels across 3 grains · 3 unclassified — reported, never hidden`
  (count plain, caveat dim)

**3.6 Git signal mining** (full mode only)

- (spinner ~3s) `Mining git history for outcome signals (blame is slow)` →
  `⬢ Mined outcome signals · 1,982 commits across 4 repos · survival · rework · reverts · attribution`
  (tail words all dim, dot-separated)

**3.7 First look**

- (spinner ~1.5s) `Generating your first look` →
  `⬢ First look ready · 272 sessions · $1,847.30 list-equivalent · 11 not priced`
  (dollar bold, caveat dim), then dim:
  `    open it: data/extracted/report/first_look.html`

**3.8 Highlights** — four chart blocks, each: `⬢ heading` + blank + chart.

Spend by tool (bars accent, share-of-total):

```
⬢ Where the $1,847.30 went · list-equivalent · bars are share of total

    claude_code  ██████████████████▊░░░  $1,562.10 · 85% · 214 sessions
    cursor       ███▍░░░░░░░░░░░░░░░░░░  $285.20 · 15% · 58 sessions
```

Models (bars accent, top 5 + dim tail line):

```
⬢ Which models did the work

    claude-sonnet-5    ████████████▌░░░░░░░░░  $1,031.40 · 56% · 141 sessions
    claude-opus-5      ██████▏░░░░░░░░░░░░░░░  $512.61 · 28% · 44 sessions
    claude-haiku-4-5   ██▍░░░░░░░░░░░░░░░░░░░  $198.10 · 11% · 61 sessions
    composer-1         █▏░░░░░░░░░░░░░░░░░░░░  $105.19 · 6% · 26 sessions
```

Task mix (bars **cyan**, top 3, organic sessions only):

```
⬢ What the work was · organic sessions · content-free classifier

    feature work  ████████▊░░░░░░░░░░░░░  40% · 96 sessions
    debugging     ██████▏░░░░░░░░░░░░░░░  28% · 67 sessions
    refactoring   ███▌░░░░░░░░░░░░░░░░░░  16% · 39 sessions

    31 sessions look automated (CI-launched) — they answer different questions than human traffic
```

Impact (bars **green**, fraction = survival rate):

```
⬢ Did the work hold up · 1,982 commits across 4 repos · read-only git signals

    api-server     ████████████████████▏░  92% survives 30 days · median of 341 commits
    web-app        ███████████████████▎░░  88% survives 30 days · median of 512 commits
    infra-tools    █████████████████▌░░░░  80% survives 30 days · median of 122 commits

    rework: 141 of 975 measured commits (14%) were edited again within 30 days

    1 repos too young to measure survival — not recorded, never assumed
```

Dashboard pointer (dim, arrow prefix; "(preview …)" in yellow):

```
→ deeper cuts — per-repo spend, rework rates, the full mix: https://caliper.dev/dashboard (preview — dashboard not live yet)
    your first look above is that dashboard's first card
```

**3.9 Policy pivot** — a second question box:

```
┌──────────────────────────────────────────────────────────────────┐
│ Question                                                         │
│                                                                  │
│ Caliper has quality-per-tier evidence covering part of this      │
│ traffic. Draft a routing policy?                                 │
│                                                                  │
│   [x] Draft it — see the numbers before deciding anything        │
│   [ ] Not now                                                    │
└──────────────────────────────────────────────────────────────────┘
```

Demo picks "Draft it", then:

- (spinner ~2s) `Drafting policy — checking your traffic against tier evidence` →
  `⬢ Policy drafted · rp-2026-08-001 · code review` (policy id accent, scope dim)

A good place to **end the demo** (fade out or loop back to the start) — the
full policy presentation is its own flow. Optionally end with a dim
`    UX prototype: drafted from committed eval evidence — in production this stage runs the eval pipeline and takes longer`.

## 4. Implementation notes for the web

- **Structure:** a `<div class="terminal">` with `white-space: pre`,
  monospace, `overflow-x: auto`. Render each block as it "completes";
  auto-scroll the container to bottom as content appears (but stop
  auto-scrolling if the user scrolls up).
- **Chrome:** optional slim macOS-style title bar (three dots + `caliper`) —
  the CLI itself has none, so keep it minimal. Do **not** paint a pure-black
  background; use the site's dark surface. Support the site's light theme
  with the light palette above.
- **Spinner:** swap one character between `⬡` and `⬢` every 400 ms (accent),
  label dim. On completion, remove the spinner line and append the `⬢` line —
  in-place replacement, no leftover spinner lines.
- **Bars:** animate width from 0 to target over ~500 ms when the chart block
  appears. Either ease the character count (authentic, steppy) or overlay a
  CSS-width div clipped over the glyphs (smooth). The eighth-block glyph math:
  `cells = frac*22; full = floor(cells); eighth = round((cells-full)*8)` →
  `"█"*full + "▏▎▍▌▋▊▉"[eighth-1]` + `"░"` track to 22.
- **Question boxes:** make them actually interactive if cheap (↑/↓/j/k,
  number keys, Enter, click), else auto-advance after ~2 s with a visible
  selection-move animation so it reads as interactive.
- **Timing:** total run ~25–35 s. Add a subtle replay control. Respect
  `prefers-reduced-motion`: skip spinners/typing, render the final transcript
  instantly.
- **Alignment matters:** labels in a chart block are left-padded to the
  widest label; boxes are drawn to the widest content line. Compute in
  character space (everything is monospace) — don't eyeball with CSS padding.
- **Data-driven:** keep the whole transcript as a JSON script
  (array of `{type: box|step|child|spinner|chart|question|dim, ...}` events
  with durations) so copy/numbers can be tweaked without touching the player.

## 5. Sample script data (starting point)

```json
[
  {"type": "box", "lines": [["bold caliper setup", "dim first run", "dim engineers do not change how they work"]]},
  {"type": "block", "id": "trust"},
  {"type": "question", "prompt": "Start the backfill?", "options": ["Full backfill — sessions + git outcome signals (takes minutes)", "Quick backfill — sessions only, signals later", "Not now"], "picks": 0},
  {"type": "spinner", "label": "Backfilling claude_code", "ms": 2500,
   "done": ["Backfilled **claude_code**", "214 sessions", "dim 2026-01-04 → 2026-08-15"]},
  {"type": "spinner", "label": "Backfilling cursor", "ms": 1500,
   "done": ["Backfilled **cursor**", "58 sessions", "dim 2026-03-11 → 2026-08-14"]},
  {"type": "spinner", "label": "Classifying traffic (content-free)", "ms": 1500,
   "done": ["Classified traffic", "816 labels across 3 grains", "dim 3 unclassified — reported, never hidden"]},
  {"type": "spinner", "label": "Mining git history for outcome signals (blame is slow)", "ms": 3000,
   "done": ["Mined outcome signals", "1,982 commits across 4 repos", "dim survival · rework · reverts · attribution"]},
  {"type": "spinner", "label": "Generating your first look", "ms": 1500,
   "done": ["First look ready", "272 sessions", "**$1,847.30 list-equivalent**", "dim 11 not priced"]},
  {"type": "chart", "heading": "Where the $1,847.30 went · list-equivalent · bars are share of total", "color": "accent",
   "rows": [["claude_code", 0.85, "$1,562.10 · 85% · 214 sessions"],
            ["cursor", 0.15, "$285.20 · 15% · 58 sessions"]]},
  {"type": "chart", "heading": "Which models did the work", "color": "accent",
   "rows": [["claude-sonnet-5", 0.56, "$1,031.40 · 56% · 141 sessions"],
            ["claude-opus-5", 0.28, "$512.61 · 28% · 44 sessions"],
            ["claude-haiku-4-5", 0.11, "$198.10 · 11% · 61 sessions"],
            ["composer-1", 0.06, "$105.19 · 6% · 26 sessions"]]},
  {"type": "chart", "heading": "What the work was · organic sessions · content-free classifier", "color": "cyan",
   "rows": [["feature work", 0.40, "40% · 96 sessions"],
            ["debugging", 0.28, "28% · 67 sessions"],
            ["refactoring", 0.16, "16% · 39 sessions"]],
   "tail": "31 sessions look automated (CI-launched) — they answer different questions than human traffic"},
  {"type": "chart", "heading": "Did the work hold up · 1,982 commits across 4 repos · read-only git signals", "color": "green",
   "rows": [["api-server", 0.92, "92% survives 30 days · median of 341 commits"],
            ["web-app", 0.88, "88% survives 30 days · median of 512 commits"],
            ["infra-tools", 0.80, "80% survives 30 days · median of 122 commits"]],
   "tail": "rework: 141 of 975 measured commits (14%) were edited again within 30 days"},
  {"type": "dim", "text": "→ deeper cuts — per-repo spend, rework rates, the full mix: https://caliper.dev/dashboard (preview — dashboard not live yet)\n    your first look above is that dashboard's first card"},
  {"type": "question", "prompt": "Caliper has quality-per-tier evidence covering part of this traffic. Draft a routing policy?", "options": ["Draft it — see the numbers before deciding anything", "Not now"], "picks": 0},
  {"type": "spinner", "label": "Drafting policy — checking your traffic against tier evidence", "ms": 2000,
   "done": ["Policy drafted", "accent rp-2026-08-001", "dim code review"]}
]
```

All numbers above are invented demo data — do not put real extraction output
on the public site.
