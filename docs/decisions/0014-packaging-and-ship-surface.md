# ADR-0014: Packaging, the shipped surface, and what stays a development instrument

**Date:** 2026-08-24 · **Status:** accepted · **Gate:** nothing about the classifier or trace layer matters until a stranger can install and run Caliper

## Context

Caliper only ran from an editable checkout. A wheel built from the old
pyproject shipped the code but not `schemas/` — nine read sites (including
the scheduled job, hourly) would crash `FileNotFoundError` on any real
install — and `caliper pricing` wrote into site-packages. Separately, three
explorations (the packaging read-map, an empty-machine trace, a platform/git
audit) established that several surfaces are not honest to hand a stranger
at all. This ADR records the packaging mechanics and the ship/dev split.

## Decision 1: the shipped surface

**A stranger gets: `setup`, `extract`, `signals`, `classify`, `report`,
`schedule`, `uninstall`.** Every number those render comes from the user's
own machine — a coherent product.

**Development instruments — in the tree, out of the quickstart, gated:**

- **`policy`** — the verdict math runs anywhere, but the recommendation
  rests on Caliper's own contaminated commons-lang evidence and rp-0001 is
  hand-written; no policy generation engine exists. A first-time user shown
  a routing recommendation computed from someone else's eval runs would
  conclude the tool is confused, and no label fixes that. The README's
  borrowed-evidence tier describes a recommendation that fires *after*
  Caliper has measured the user's traffic — not something handed out on
  install. Policy surfaces (the command, the post-extract nudge, the setup
  final step) gate on eval evidence from the user's own traffic; it returns
  when the router exists.
- **`replay`** — burns real API spend against the author's mined task set
  and needs a task workspace; refuses without a source checkout.
- **`pricing update`** — maintains committed reference snapshots; writing
  them belongs in a checkout, so the command refuses without one (this also
  removes the only package-relative *write* in the codebase from installed
  environments).
- **`classify --validate`** — the calibration set ships with the repo, not
  the package; refuses without a checkout.

Each gate is one plain sentence naming what the command is and why it needs
a checkout. Help text carries a "(dev: …)" suffix so `caliper --help` shows
the shipped surface plainly.

## Decision 2: distribution

```
pipx install git+https://github.com/avaneeshjoshi/agent-measurement-harness.git@v0.2.0
```

One command, no clone, an isolated venv, a PATH entry. The tag pins the
exact tree — an install today and an install next month resolve identically,
reinforced by exact dependency pins (`jsonschema==4.26.0`; the only runtime
dependency). Upgrades are explicit: `pipx install --force …@v<next>`.
`uv tool install` works identically. No PyPI account is assumed; publishing
a wheel to a GitHub Release is a compatible later step.

**The distribution version (pyproject/tag, now 0.2.0) is its own axis.** It
is independent of the session schema (0.4.0), connector (0.3.1), classifier
(rules-0.1.1), and every other producer version (conventions.md). The
store's idempotency triple does not include the package version, so a
package bump re-emits nothing — verified by the byte-identity test over
unchanged fixtures.

## Decision 3: assets travel inside the package

- Build backend: **hatchling**. The wheel force-includes the repo's
  top-level `schemas/` as `caliper/assets/schemas/` — the repo copy stays
  the single source of truth; the package carries a build-time copy.
- `caliper.cli.paths.schema_path(name)` resolves every schema read (all
  nine sites): the checkout's `schemas/` when present, else
  `importlib.resources` on `caliper.assets`. `checkout_root()` is the same
  detector the dev-command gates use.
- Pricing snapshots already ship as package files (read-only at runtime;
  `load_pricing` is package-relative). **Nothing else enters the wheel**:
  `data/evidence/` (the author's commons-lang results) stays repo-side —
  bundling it into every install is the same problem policy had;
  `data/calibration/` and `data/fixtures/` are dev/test material.
- Top-level packages renamed **before the first wheel existed**:
  `caliper.cli` / `caliper.connectors` / `caliper.harness` / `caliper.assets`
  — shipping importable top-level names like `cli` and `harness` collides in
  any shared environment, and pipx isolation only protects pipx users.
  Verified post-rename: the scheduled job kickstarted and landed a real
  extraction; re-extraction over unchanged sources stayed byte-identical
  (no record or state field derives from module paths).
- The launchd plist's `WorkingDirectory` is now the data home, not a repo
  path (nothing depends on CWD; a pipx install has no repo).
- `--version` reads the installed distribution metadata.

Verified on 2026-08-24: wheel built, installed into a bare venv, run under a
fake `HOME` with no checkout importable — `caliper --version`, a real
extraction of fixture logs (schemas resolved from the packaged copy), and
all three dev gates refusing with their sentences.

## Consequences and known limitations (register)

- A packaged install still cannot run the eval pipeline or validation —
  deliberate, stated at the gate, not discovered by traceback.
- The install command depends on the GitHub repo staying public at that URL.
- **Live finding during this work (2026-08-24): the field-coverage canary's
  first real firing was a false positive of a predictable class.** Eight
  alarms on claude_code (diff_stats.*, languages, prompt_source_counts.sdk,
  subagents.count; recent n=12 vs baseline n=215) trace to a COHORT SHIFT —
  the baseline window is dominated by eval-harness sessions (which always
  carry diffs, SDK prompt sources, subagents) while recent traffic is
  organic — not to a vendor dropping fields. The canary pools cohorts that
  the report itself refuses to pool (ADR-0009). Recorded, not tuned away:
  cohort-aware coverage windows are the designated fix, and the thresholds
  stay as ADR-0011 set them until that lands. The alarms' own wording ("a
  source format MAY have dropped the field") stays honest meanwhile.
- Known limitations carried forward from the audits (recorded, not yet
  fixed): git worktrees produce two `repo_ref`s over the same commits
  (double-counted aggregates); ancient Claude Code logs without `message.id`
  undercount assistant messages; an unreadable source root is
  indistinguishable from an absent one at `is_dir()`; `classify --validate`
  writes literal `NaN` into its JSON report when nothing matches (dev-only);
  `caliper report` shells out to `git` to build the project name map.
- DESIGN.md — the rendering authority every new user-facing string in this
  work is checked against — is adopted as the fourth root document
  (README, PROGRESS, CLAUDE, DESIGN) and committed with this ADR, which is
  the ADR the root-markdown rule requires. Its references to PRODUCT.md and
  ARCHITECTURE.md describe documents that do not exist yet; they remain
  ghosts, reported rather than invented.

## Addendum (same day): the write-validation audit (C4)

Prompt units were written with **no schema validation** — `extract()`
validated only `emission.record`, and units "rode the session's idempotency."
Foreign log shapes (a prompt record with no timestamp, observed in older
Claude Code formats) therefore wrote schema-invalid rows silently. Fixed at
the root: units now pass `prompt_unit.schema.json` at write time exactly as
session records do; invalid units are skipped and counted in the manifest
(`notes.prompt_units_invalid`).

Full audit of every other writer, for the same hole:

| Writer | Validated? | Verdict |
|---|---|---|
| session records (`extract`) | yes, at write | — |
| prompt units | **was NO — fixed by this ADR** | invalid rows skipped + counted |
| production signals (`signals`) | yes, at write | — |
| task_class records (`classify`) | yes, before write | — |
| content sidecar rows | no schema exists | deliberate: local-only, never enters records; documented |
| run manifests | no schema exists | internal bookkeeping; consumers use `.get()` throughout |
| collection state / decision log / name map | no schema | internal state; corrupt state already degrades with a printed warning |
