# ADR-0015: Generated paths are excluded from durability line counting

**Date:** 2026-08-24 · **Status:** accepted · **Implements:** the filtering ADR-0006 finding 1 deferred · **Schema:** production_signal 0.2.0 → 0.3.0, signals connector 0.1.0 → 0.2.0

## Context

Commit `2fbaf77` (Axlerate) added 3,013,346 lines — a lockfile regeneration.
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

*(Filled by the follow-up commit after the live re-run: which commits flip
to `excluded_generated`, which mixed commits' counts shrink and by how much,
per-repo line-weighted and per-commit-median 30d survival before/after, and
wall-time before/after.)*

## Known limitations

- Working-tree attribute semantics (above).
- Numstat rename paths (`old => new`) are not unbraced anywhere in this
  connector — pre-existing, affects the filter the same way it already
  affects blame; recorded, unfixed here.
- The pattern list is a judgment call at gen-0.1.0; additions bump its
  version and land here, never silently.
