# ADR-0018: Serve visual system v2 — the reference design language, adopted

**Date:** 2026-08-24 · **Status:** accepted · **Amends:** DESIGN.md prohibited-pattern 14 and the typography section · **Extends:** ADR-0016/0017

## Context

After three revision rounds on serve's charts, the user supplied the full
source of the reference dashboard as the target design language. Its two
core elements collided with DESIGN.md rules the user had themselves
ratified — the stat-tile headline row (prohibited pattern 14, reaffirmed
twice) and monospace-everywhere typography (DESIGN mandates Inter for UI
text). Asked directly, the user chose to adopt both. This ADR records the
adoption and the amendments — the glass-box alternative to letting a
pasted reference quietly override the design authority.

## Decision 1: the amendments

- **Rule 14** now permits a **stats strip**: one bordered row of tiles per
  surface, every tile carrying its basis line (what the figure covers, at
  the metadata step), at most the first tile inverted as the lead. A
  naked-number tile remains prohibited — the `tiles()` builder raises on a
  missing basis line, so the amendment's condition is enforced in code,
  not left to review. Donuts, gauges, and free-standing sparklines remain
  prohibited.
- **Typography** gains a serve variant: mono-everywhere (`ui-monospace`,
  13px/1.5, 14px ≥1700px), uppercase letterspaced micro-labels, 2px
  structural borders, squared buttons with inverted-ink pressed states.
  The report keeps the Inter system until its own design pass — the two
  surfaces intentionally diverge until then, stated here.

## Decision 2: the adopted system

- **Shell**: 1760px max width; masthead (uppercase wordmark + the
  loaded-at stamp as the status line); one control bar of squared
  `aria-pressed` buttons — view nav, filter form, range selector — all
  still server-rendered links and forms, URL state unchanged.
- **Stats strip** on the overview: Total spend (lead, exact to the cent —
  the identity with `caliper report` is a test) · Per active day ·
  Tokens · Heaviest day. The savings framing sentence stays as the
  note-line beneath, now carrying the priced/unpriced/no-token counts.
- **Panels**: 2px `--edge-strong` borders, header bar (uppercase title
  left, faint note right). Charts' `figure/figcaption` markup is styled
  identically — panels and charts are one system.
- **Independent-packing columns** (`.cols`): two flex columns whose last
  panels stretch, so short panels don't strand whitespace under tall
  neighbors.
- **Rank rows** for by-model, by-tool, and by-project spend: swatch + name
  left, amount + share right, full-width track beneath, faint sub-line
  with the n. The by-tool and by-project seven-column tables are retired;
  the rank rows carry the same dollars, shares, and session counts, and
  Cursor's row renders its absence words with **no track — an absence
  never becomes a bar of any length**.
- **Tokens-by-type tiles**: the four buckets as tiles (compact figure,
  share, track, exact count) — the aggregate the per-model bucket bars
  don't show.
- **Daily table**: newest first (stated), sticky header in a capped scroll
  container, true zeros dimmed via `.zero` (still the digit 0 — the six
  absence words are untouched and still render as words).
- **Tooltip**: 2px ink border, uppercase title, 80ms opacity fade (inside
  DESIGN's motion scale), `prefers-reduced-motion` collapse; the instant
  `data-tip` engine and server-authored payloads are unchanged.
- Charts re-proportioned for the width (spend 1400×340, scatter 1400×400).

## Not adopted, and why

- **The cumulative spend line** — still declined (ADR-0017): the daily
  columns plus the running total carry the same information.
- **Client-side tabs** — serve has real pages; the nav is styled as the
  reference's buttons but navigates.
- **The live-poll status machinery** — serve re-reads per request through
  the mtime cache (ADR-0016); a poller would add moving parts to solve a
  problem serve doesn't have.
- **The reference's palette values** — DESIGN's tokens already cover the
  roles; series colors remain `--cat-1…10` (ADR-0017 postscript 2).

## What did not change

The measurements. Absence words, uncertainty pairs, evidence lines, the
caveat block on every measuring surface, cohorts never pooled, the
proximity label, read-only, no policy view — all intact and still under
test. This ADR is presentation and two sanctioned rule changes, nothing
else.
