**Purpose:** Working rules for any agent implementing in this repo.
**Authoritative for:** Where truth lives, the inviolable rules, schema-change procedure, commit discipline, and the evidence standard.
**Not authoritative for:** Current capability status (`PROGRESS.md`), design rationale (`docs/decisions/`), record shapes (`schemas/`), the detailed data conventions (`docs/conventions.md`).
**Update when:** A rule changes — which itself requires an ADR — or a truth-source file is added, moved, or retired.
**Last reviewed:** 2026-08-23

# CLAUDE.md — how to work in this repo

## Where truth lives

| File | Owns |
|---|---|
| `README.md` | What Caliper is, the architecture, the intended product experience, the repo map. Not status. |
| `PROGRESS.md` | What works right now, with evidence; what is stubbed; gaps; build order. The only status document. |
| `docs/conventions.md` | Schema and data rules: versioning, uncertainty vocabulary, segmentation, provenance, privacy, field style. |
| `docs/decisions/` | Why — one numbered ADR per decision. Nothing elsewhere may be unexplained here. |
| `schemas/` | Record shapes. The contracts every component communicates through; components never import across layers. |

**Rule: no new root-level markdown files without an ADR.** The root set is README.md, PROGRESS.md, CLAUDE.md (plus LICENSE). Anything else goes under `docs/` or justifies itself in `docs/decisions/` first.

## Rules that may not be violated

Each rule names where it is established. If you think a task requires breaking one, stop and say so instead.

- **Absent is not zero.** Missing evidence is encoded (`unknown`, `not_yet_measurable`, `null`, "not recorded"), never defaulted or dropped. Why: the moment absence collapses to zero, every aggregate silently lies — the 6.5%-vs-99.3% survival finding (ADR-0006) only stayed honest because the two were kept distinct. (`docs/conventions.md` — Uncertainty vocabulary; enforced in report rendering tests.)
- **Content-free by default.** Session and unit records carry no prompts, code, file contents, or command output; content sidecars exist only under `--include-content`, are local-only, and `data/extracted/` is gitignored — all three enforced by tests. Why: Caliper's trust story is that it can measure without reading anyone's work; one leaked prompt ends that. (`docs/conventions.md` — Content and privacy.)
- **Uncertainty travels with every number.** Every aggregate carries `n`; CIs where n supports one; judged scores may not circulate without their calibration block; disagreeing measurement tracks stay disagreeing — there is deliberately no field that can average them. Why: a number stripped of its uncertainty gets quoted as a capability claim (ADR-0007's contamination caveat exists precisely because of this). (`docs/conventions.md` — Uncertainty vocabulary.)
- **Team-level only. No individual rankings, ever.** Per-change attribution exists as evidence and is aggregated before any surface renders it. Why: the instant Caliper ranks engineers it becomes surveillance, engineers route around it, and the data corrupts. (`docs/conventions.md` — Content and privacy; `README.md` governing principle.)
- **Read-only over sources.** Connectors never mutate or lock originals; SQLite is snapshot-copied and opened read-only — enforced by a test that intercepts `sqlite3.connect`. Why: a measurement tool that can corrupt the logs it measures is disqualified on sight. (ADR-0004; `cli/main.py` docstring; `tests/test_extractor.py`.)
- **Glass box.** Every classification rule, threshold, rubric, and routing recommendation is versioned and carries its rationale in a numbered ADR; policy records carry `adr_refs`. Why: the product's differentiation is auditability — an unexplained number is a vendor dashboard. (`README.md`; `docs/decisions/README.md`.)
- **No router in the request path.** Caliper writes native configuration the harnesses already respect; it never proxies traffic or runs its own router. Why: sitting in the request path makes Caliper a latency/availability liability and turns observation into interference. (`README.md` — Apply.)
- **Findings get recorded, not tuned away.** Instrument weaknesses become documented limitations or ADR findings; adjusting rules to chase a validation number requires new labels and a disclosed ADR note (the one adjustment round in ADR-0009 is the template — disclosed, bounded, then frozen). Why: a self-tuned instrument measures itself. (`docs/conventions.md` — Segmentation "not bugs to silently tune away"; ADR-0006 "deferred, not silently patched".)

## Schema changes

- Any shape change bumps the schema's version and lands with an ADR note in the same change. Widening changes bump minor; nothing is ever quietly edited in place.
- **Old records are never rewritten to a new version.** Re-runs write new artifacts; corrections are restatements in ADRs (see the ADR-0007 pricing postscript — records kept, citation corrected).
- `additionalProperties: false` everywhere — unknown fields are a validation error; that is how format drift gets noticed instead of silently ignored.
- The three version axes are independent (schema / taxonomy / producer versions); bumping one never implies bumping another. Fields carry `x-provenance` (`observed` / `derived` / `aspirational`); do not mark a field observed you have not seen in a real log.
- Full detail: `docs/conventions.md`.

## Commit discipline

- **Maximum honest granularity.** One coherent change per commit, committed as the work happens — no mega-commits, no retroactive splitting into a fake-tidy sequence.
- **Every commit is green and independently revertable.** Run the tests before committing; a commit that only works alongside its neighbor is one commit, not two.
- **Push continuously.** Local-only history is unshared state; the remote is the record.
- **History is append-only.** Never amend or force-push over pushed history; fix forward with a new commit.
- **No Claude co-author trailers.** Plain commit messages describing the change; no `Co-Authored-By` lines, no tool attribution.

## Evidence

- A `PROGRESS.md` status claim without an evidence line — a test, a run with figures on disk, or an ADR — **is not a status claim** and must not be added. If the evidence doesn't exist yet, the capability goes under Stubbed or not at all.
- **Update `PROGRESS.md` in the same commit that changes a capability.** A capability change that leaves PROGRESS.md stale is an incomplete change; that coupling is what keeps the status file from rotting the way status-in-README did.
- Numbers cited in docs come from the repo (records, manifests, test runs, ADRs) — never from memory. Where two on-disk sources disagree, say which is current and why (see the join-rate note in PROGRESS.md for the pattern).
