# ADR-0015: Generated paths are excluded from durability line counting

**Date:** 2026-08-24 · **Status:** accepted · **Implements:** the filtering ADR-0006 finding 1 deferred · **Schema:** production_signal 0.2.0 → 0.3.0, signals connector 0.1.0 → 0.2.0

## Context

Commit `2fbaf77` (Axlerate) added 3,013,346 lines — an entire Python virtualenv committed into the repo (`venv/lib/python3.12/site-packages/…`; caught by the `venv` path-segment rule, not a lockfile pattern).
It is a real diff, so nothing diff-based or size-based distinguishes it; it
dominated its repo's line-weighted survival absolutely (ADR-0006 finding 1
read 6.5% overall because of exactly this class of commit) and it is not
work anyone did. With serve about to render these numbers, the deferral is
implemented: known-generated paths are excluded from line counting, and the
exclusion is stated rather than silently decided.

## Decision

1. **A versioned pattern list** (`caliper/connectors/generated.py`,
   `GENERATED_PATTERNS_VERSION = "gen-0.1.0"`), stated here in full and
   named in the report's caveat block:
   - Lockfiles: package-lock.json, yarn.lock, pnpm-lock.yaml, bun.lockb,
     Cargo.lock, poetry.lock, uv.lock, Pipfile.lock, Gemfile.lock,
     composer.lock, go.sum, Podfile.lock, flake.lock, packages.lock.json,
     gradle.lockfile
   - Minified/derived: `*.min.js`, `*.min.css`, `*.js.map`, `*.css.map`
   - Build/vendor path segments: node_modules, dist, build, out, target,
     .next, vendor, \_\_pycache\_\_, venv, .venv
   - Codegen markers: `*.pb.go`, `*_pb2.py`, `*_pb2_grpc.py`, `*.generated.*`
2. **The repo's own declaration wins, both directions.**
   `.gitattributes linguist-generated` marks a file generated regardless of
   patterns; an explicit `-linguist-generated` rescues a pattern-matched
   path — the escape hatch for over-broad segments like `build/` in
   ecosystems where they are real source. Attributes are read from the
   **working tree** (`git check-attr`), not per-commit history — a file
   marked generated today filters historical commits too; recorded as a
   limitation.
3. **Both numbers, one record.** `change_ref.lines_added/lines_deleted` are
   now the filtered WORK counts (what renders); the required `generated`
   block carries `{patterns_version, files_excluded, lines_added_excluded,
   lines_deleted_excluded}` — the unfiltered totals are the sum, the delta
   is first-class, and the report states it per repo where nonzero.
4. **A sixth absence word: `excluded_generated`.** A commit touching only
   generated files is measurable but deliberately outside the work-survival
   question — it is not `unmeasurable` and it is never 0%. Added to the
   survival and rework status enums and to DESIGN.md's absence list (this
   ADR is the rule-19 sanction). Ordering: generated-only is decided before
   the zero-lines check, so a pure deletion still reads `unmeasurable`.
5. **Blame runs only on work files** — the 3M-line blame disappears, a
   material speedup measured in the re-run below.
6. In passing, per ADR-0006 postscript 2's note: rework's dead no-snapshot
   branch now yields `rework: null` instead of assuming all lines survived.

## Verification

- Known-answer fixture: K6 (a 50,000-line lockfile commit) flipped from
  pinning "no filter exists" to asserting `excluded_generated` ×3 horizons,
  the exact `generated` block, and the restated skew fact — line-weighted
  16/27 vs per-commit mean 2.6/5 over the measured set, the same story
  instead of the lockfile's. New known-answers: a mixed commit (code +
  lockfile → work-only counts, delta recorded, survival over work lines),
  and `.gitattributes` overrides in both directions.
- Records validate at 0.3.0; the version bumps re-emit every signal record
  on the next run (the idempotency triple — the intended clean cutover,
  ADR-0005 precedent).

## Re-run against the real repos (before/after)

Run 2026-08-24 (pre-filter records snapshotted first; 234 → 245 records —
the 11 extra are commits landed since the previous day's run, ordinary
drift). **Wall time: ~6 minutes → 36 seconds** (blame no longer runs on
generated monsters).

- **Flipped to `excluded_generated`: 1 commit** — Axlerate `8c8d654`
  (1,994 generated lines, nothing else).
- **Mixed commits with work counts shrunk: 16**, led by Axlerate `2fbaf77`:
  lines_added **3,013,346 → 9** (3,013,337 excluded — the committed-virtualenv commit that
  motivated this ADR turns out to contain nine lines of actual work),
  Axlerate `2dca7f5` 12,806 → 889, AvaneeshJoshi-Portfolio `83ee91a`
  18,598 → 7,872, echo-web `f904f27` 8,411 → 1,651, and so on down.
- **Per-repo 30d survival, line-weighted / per-commit-median (n):**

| repo | before | after |
|---|---|---|
| Axlerate | **0.0571** / 0.992 (19) | **0.9974** / 0.985 (19) |
| Echo | 0.9423 / 0.996 (18) | 0.9292 / 0.996 (18) |
| Personal-Portfolio-Website | 0.9591 / 1.0 (17) | 0.9467 / 0.987 (19) |
| AvaneeshJoshi-Portfolio | 0.9998 / 1.0 (7) | 0.9996 / 1.0 (7) |
| Cyrano | 0.9999 / 1.0 (4) | 0.9998 / 1.0 (4) |
| ci-autofix, echo-web | 1.0 / 1.0 (1) | 1.0 / 1.0 (1) |

The ADR-0006 pathology is resolved where it lived: Axlerate's line-weighted
figure was 94 points below its own median because of one lockfile; under
gen-0.1.0 the two views tell the same story. Where line-weighted moved
*down* slightly (Echo, PPW), that is the filter removing high-surviving
generated bulk — the honest direction.

## Known limitations

- Working-tree attribute semantics (above).
- Numstat rename paths (`old => new`) are not unbraced anywhere in this
  connector — pre-existing, affects the filter the same way it already
  affects blame; recorded, unfixed here.
- The pattern list is a judgment call at gen-0.1.0; additions bump its
  version and land here, never silently.
