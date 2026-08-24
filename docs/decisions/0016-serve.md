# ADR-0016: caliper serve — the local interactive view

**Date:** 2026-08-24 · **Status:** accepted · **Surface:** shipped (`caliper serve`) · **Depends:** the report data layer (ADR-0012 paths, ADR-0015 filter)

## Context

The static report is the artifact a user sends someone else; serve is the
surface they explore themselves. It must not weaken any promise the trust
screen makes, and it must never disagree with the report — a serve page
showing a different number than a report the user already mailed out is the
worst possible bug in a measurement product.

## Decisions

1. **Local-only, read-only, nothing else.** `http.server.ThreadingHTTPServer`
   bound to `127.0.0.1` on an ephemeral port (`--port` to pin), stdlib only —
   no new dependency joins the pinned `jsonschema`. No accounts, no network
   calls, no external assets (one inline stylesheet, one inline sort
   script), no telemetry, no writes: `tests/test_serve.py` walks every route
   and asserts the data tree byte-identical after.

2. **One data layer, by construction.** `collect()` was split into
   `load_data()` + `summarize()` (both surfaces call exactly these; the
   report's `collect` is now their composition, signature unchanged). An
   identity test pins `collect(...) == summarize(load_data(...))`, and a
   figure test asserts serve's overview renders the collect-derived
   headline numbers.

3. **Freshness: re-read per request through an mtime-keyed cache.** The
   scheduled collector writes hourly, so serve must never show stale data as
   current — but a full parse per click stops being sub-second at the
   3,000-session scale the backfill benchmark already used. The bundle is
   cached against the source files' `(path, mtime_ns, size)` signature plus
   the active filters (8 entries, oldest evicted): any source change makes
   the next request parse fresh; an unchanged click re-parses nothing.
   Every page footer states when its bundle was loaded.

4. **Filters are URL state.** `?from=&to=&tool=` parsed server-side,
   applied in `load_data` before any aggregation (sessions by started_at
   date and tool; commits by authored_at date — a tool filter does not
   apply to git history), carried on every internal link. No cookies, no
   client-side storage; the server holds nothing per-request beyond the
   cached bundles. An active filter is stated in words on the page.

5. **Four views, no policy.** Overview (the report's content, live, every
   table sortable), repo detail (commits × survival/rework/attribution/
   generated-exclusion beside the sessions that referenced the repo — the
   join nothing else produces), session detail, coverage-and-honesty
   (always in the nav). Policy stays gated on the user's own eval evidence
   (ADR-0014); there is no policy route and the test asserts the 404.

6. **Temporal proximity is labeled by the fragment builder, not the page.**
   The only place commits appear beside a session is
   `views._nearby_commits`, which renders the heading "Commits nearby in
   time — temporal proximity, not attribution" and the trace-layer
   disclaimer unconditionally — a caller cannot produce the table without
   the label. **The ±24h window is an unvalidated display choice made for
   readability, not a measured commit-latency figure.** It is constant
   `PROXIMITY_HOURS`, stated as unvalidated on the page itself, and the
   honest value comes from the trace layer once session→commit latency is
   actually measured. Recorded explicitly because the retention constant
   (ADR-0011 postscript) was exactly this pattern — an unmeasured display
   number quietly hardening into a claimed one, 10x wrong from n=1 — and it
   does not repeat silently.

7. **Sorting is client-side and user-initiated.** ~30 lines of inline JS
   reorder rows on header click over server-rendered `data-s` sort keys.
   Nothing sorts, animates, or draws on load (DESIGN.md prohibited
   pattern 15). Absences sort below every measured value.

## The token conflict, reported and resolved

`render.py`'s stylesheet predates DESIGN.md and disagreed with it
wholesale — names (`--page/--card/--ink/--acc` vs
`--bg/--surface-1/--text-1/--accent`), values (`#f9f9f7` vs `#FAF9F6`;
ink `#0b0b0b` vs `#26241F`), and semantics: render's accent was **blue
`#2a78d6`** where DESIGN mandates the single deep-green authority hue
`#1F4A38`, and the semantic `--measured/--provisional/--absent/--danger`
tokens did not exist in render at all. Serve was built on DESIGN.md's
tokens exactly, and — per review of this ADR's draft — the report's
stylesheet is restyled to the same tokens in this change rather than
shipping two visually different products (before/after screenshots with
the commit). DESIGN.md is the authority by its own header; the old palette
survives nowhere.

## Empty and partial states

Every view survives: no sessions (one sentence + `caliper extract`),
sessions without signals ("No signals yet. Run caliper signals."),
signals without classifications, any subset of the three tools (absent
tools render their absence words in the coverage table, never zero-rows
silently dropped), and a filter that matches nothing. All asserted in
`tests/test_serve.py`.

## Postscript (same day): what the two walkthroughs caught

The live walkthrough — every view on this machine's real data, then every
view on an empty HOME — found four defects the test suite had not:

1. **`caliper serve` did not run at all.** `main()`'s command whitelist (the
   dev-gate boundary) predates serve; the command fell through to
   `print_help()` and exit 1 despite the parser and handler both existing.
   Fixed; pinned by a dispatch test that drives `main()` itself. The unit
   tests all passed while the command was unlaunchable — surface-level
   walkthroughs are not optional.
2. **Serve wrote to an empty home.** A missing name map made the data layer
   build and persist it, and `load_salt` created `.salt` as a side effect.
   The read-only test had a pre-built map, so it proved read-only only on a
   populated home. Fixed with `readonly=True` loads (in-memory map build;
   `{}` on a salt-less home); a new test walks every route over a bare home
   and asserts not one file appears.
3. **Cursor rendered as zeros.** The by-tool spend table showed
   `0 sessions` and four zero buckets for a tool whose 52 sessions all lack
   tokens — the absent-is-never-zero rule violated by omission. Now: the
   session count includes them with "(52 log no tokens)" and the buckets
   read `not recorded`. The static report's own by-tool table has the same
   presentation gap (its banner discloses it in prose); recorded here,
   unfixed there.
4. **Borders inside borders.** The proximity block (bordered) contained a
   bordered table — DESIGN.md prohibited pattern 12. The nested table now
   drops its own border.

Both walkthroughs then completed clean: real data — overview, coverage,
repo detail (139 commits), session detail (classification rule + rationale,
files, 3 nearby commits labeled), filtered variants, 404s; empty HOME —
every view one sentence + one action, zero files written, `/policy` 404.

## Known limitations

- The repo↔session join is the display-name proxy (approximate, labeled on
  every surface that uses it); the measured join rates remain ADR-0006's.
- `webbrowser.open` on a headless machine is a no-op; the URL is printed
  either way.
- The sort script is the product's first client-side JavaScript; it touches
  only row order, never data.
- The mtime signature covers the record files serve reads; a source
  replaced within the same nanosecond mtime and byte size would be missed —
  accepted as unreachable in practice.
