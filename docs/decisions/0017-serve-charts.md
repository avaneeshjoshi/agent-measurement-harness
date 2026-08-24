# ADR-0017: Charts in serve, the chart-category tokens, and the range selector

**Date:** 2026-08-24 · **Status:** accepted · **Extends:** ADR-0016 (serve), DESIGN.md (token table + chart component entry — this is the rule-19 sanction)

## Context

Serve rendered tables only. DESIGN.md permits charts and forbids dashboard
furniture; the line between them is that a chart must show something a table
cannot, carry its n, render absence as absence, and keep its record — the
table — on the same page. Four charts clear that bar; a reference screenshot
of a token-spend dashboard contributed exactly two ideas (the persistent
range selector and the savings framing sentence) and one explicit rejection
(its row of four headline stat tiles — prohibited pattern 14; serve keeps
one headline figure with its basis at metadata beneath).

## Decision 1: the four charts, and why each earns its place

1. **Spend over time** (daily stacked columns, split by tool with a
   `?split=model` toggle) — a trend is the one thing the date-sorted table
   cannot show. Days without sessions are gaps, never zero-height bars — a
   quiet day renders as ground. Unpriced sessions cannot stack in dollars,
   so they are excluded from the chart and the exclusion is stated in the
   chart's own n; the tables beneath keep every session.
2. **Task mix** (one stacked proportion bar per cohort, per grain) —
   composition at a glance; cohorts stay unpooled, `unclassified` is always
   a visible segment in the absent gray.
3. **Cost × survival per repo** (scatter, x = session list-$ on a √ scale,
   y = per-commit median 30d survival, point size = √commits) — the join
   nothing else produces, buried in a table. Repos that cannot be plotted
   are never omitted and never plotted at zero: a labeled band beneath the
   plot lists them with their absence words, as links.
4. **Token buckets per model** (horizontal stacked bars, absolute scale) —
   cache-read dominance becomes something you see rather than compute.

No fifth chart without a new reason recorded here. Specifically NOT built:
the reference's cumulative spend line (the daily columns plus the headline
total carry the same information) and its stat-tile row.

## Decision 2: chart-category tokens (the DESIGN.md extension)

Task-mix segments need a categorical palette and DESIGN.md had none —
inventing hexes inline fails review by DESIGN's own rule 9/19. Following the
precedent of the report's bucket aliases (ADR-0016), DESIGN.md's token table
now carries `--cat-1`…`--cat-10`: muted, similar-saturation, warm-leaning
hues with token-for-token dark variants, restricted to chart categories.
Rules that ride the tokens:

- Assignment is by fixed order (task types in taxonomy order, chart groups
  by rank) so a category keeps its color within a page.
- **`unclassified` never takes a category color** — it renders in
  `--absent`'s color, because it is the instrument's own absence and must
  look like it everywhere absence appears.
- `other` renders in `--text-3`.
- Color never carries a category alone: a legend of words accompanies every
  chart, and the paired table is always beneath.

The bucket chart reuses the existing `--in/--out/--cr/--cw` aliases, now
present in serve's stylesheet as well as the report's.

## Decision 3: implementation is server-side SVG, interaction is native

`caliper/harness/report/charts.py` — pure data→SVG functions, no chart
library, no CDN, no external assets: serve stays offline-capable and
dependency-free. Hover is native SVG `<title>` (the exact underlying
figures, no tooltip script); click is an SVG `<a>` wrapper navigating where
a destination exists — a day column filters to that day, a scatter point
opens its repo. Mix segments and bucket bars have no destination (no class
or model filter exists), so hover and the paired table are the way in.
Nothing animates on load, nothing draws itself, no number counts up. The
sortable-tables script is untouched; the charts added zero JavaScript.

## Decision 4: the range selector and the reframed headline

- `?range=1d|7d|30d|90d|all` joins the URL state. It resolves to an
  absolute from-date server-side per request — links stay relative ("last
  7 days") while the cache key holds the resolved date, so a cached 7d
  bundle expires naturally at midnight. An explicit date pair wins over a
  range. It drives every chart and table because it resolves into the same
  pre-aggregation filter (ADR-0016's load_data) — nothing computes twice.
- The headline's lead line is now the framing most subscription users
  actually need: *"The total price of everything you ran, at pay-as-you-go
  API rates — if a subscription covered it, that is what you saved."* The
  counts stay at metadata beneath; the caveat block keeps its traveling
  list-price sentence — the framing states what the number is, the caveat
  still states what it cannot support.

## Verification

`tests/test_serve.py`: gap-not-zero (a fabricated home with two sessions
three days apart yields exactly two day columns), n on every chart
fragment, the scatter band carrying unplottable repos with absence words
and no origin circles, day columns linking `from=to=` and points linking
`/repo/<ref>`, range resolution and link preservation, the framing
sentence, unclassified present as a mix segment, and the empty-home
overview rendering no chart frame. Live walkthrough on real data plus an
empty-HOME pass, per the ADR-0016 procedure (its walkthrough caught four
defects the unit tests missed; findings land in a postscript here).

## Postscript (same day): walkthrough findings

The live walkthrough (real data, 313 sessions / 9 repos, then an empty
HOME) found two defects, both fixed before this shipped:

1. **The dollar chart silently dropped the 53 token-less Cursor sessions.**
   Its n named priced and unpriced-with-tokens sessions but not the
   sessions that log no tokens at all — the same absence the by-tool table
   was fixed for in ADR-0016's walkthrough, resurfacing in a new surface.
   The caption now states "· 53 sessions log no tokens (Cursor) and cannot
   appear in a dollar chart".
2. **The scatter's label collision was not hypothetical.** All five
   plottable repos sit at 99–100% survival on this dataset and three labels
   rendered on top of each other — the "revisit if a real dataset makes the
   corner unreadable" clause fired on the first real dataset. Labels now
   stagger downward until they stop overlapping (collision-aware placement
   in `charts.scatter`); the figure stays beside its mark, readably.

Verified live after the fixes: gaps render on quiet days (19 active
columns over a 195-day axis), `?range=30d` recomputes every figure
($1,343.23 / 13 active days / "Filtered: last 30d (since 2026-07-25)" in
words), the bucket bars make cache-read dominance visible at a glance and
agree with the by-model table, the band lists 4 unplottable repos with
their absence words, and the empty HOME renders no chart frame and writes
zero files.

## Known limitations

- Scatter labels can collide when repos cluster at high survival; the
  labels stay (the figure must ride the mark) and hover disambiguates.
  Revisit if a real dataset makes the corner unreadable.
- The spend chart's day resolution renders a year of history at ~2px per
  column; the range selector is the intended lens.
- Category colors cycle past ten groups (model-split with >10 models);
  the legend words remain the identity.
