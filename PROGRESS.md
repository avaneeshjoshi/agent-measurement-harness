**Purpose:** The single honest statement of what Caliper can and cannot do right now.
**Authoritative for:** Current capability status, the evidence behind every status claim, known gaps, build order, and what is blocked.
**Not authoritative for:** Design rationale (`docs/decisions/`), record shapes (`schemas/`), data and schema rules (`docs/conventions.md`), working rules for agents (`CLAUDE.md`).
**Update when:** Any capability changes state — in the same commit that changes it — or a number cited here changes, or a gap opens or closes.
**Last reviewed:** 2026-08-23

# Caliper — current state

## Current milestone

On one machine, the measurement loop runs end to end: `caliper setup` extracts sessions from local Claude Code, Cursor, and Codex logs into schema-valid, content-free records; `caliper signals` computes git outcome signals (survival, rework, reverts, attribution) for the repos those sessions reference; `caliper classify` labels the traffic without reading content; `caliper replay` has produced a real three-tier quality/cost curve on 30 mined bug-fix tasks; and `caliper policy` presents the first draft routing policy (rp-0001) against the user's own traffic and records an accept/decline decision. Everything downstream of that decision — actually changing agent configs, the trace layer, the judged eval track, the dashboard — is stubbed and labeled as such on screen. All of it has run on exactly one machine: the developer's own.

## Working today

Every entry here is implemented and has produced real numbers. A capability without an evidence line does not belong in this section.

**Log extractor (`caliper extract`, `caliper setup`)** — three source connectors (Claude Code JSONL, Cursor state/tracking DBs, Codex rollout JSONL) plus per-prompt units for the two sources that have them. Read-only over sources (SQLite snapshot-copied, enforced by test), content-free by default, idempotent by content hash.
*Evidence:* ADR-0004 (Codex structural validation, first run 2026-08-09: 21/43/21 sessions, 0 validation failures), ADR-0005 (cross-tool normalization). Current local tree: 227 claude_code + 45 cursor + 23 codex session records (session schema 0.4.0), 969 prompt units (prompt_unit 0.1.1). Extractor tests in the suite cover read-only sources, idempotency, and the content boundary (all passing; the suite runs on every push and PR via `.github/workflows/ci.yml`). Extracted data lives outside the repo at `~/.caliper/extracted/` (user data, not repo data — ADR-0011); a populated legacy `data/extracted/` tree is migrated automatically, salt-preserving (`tests/test_paths.py`).

**Git-history production signals (`caliper signals`)** — blame-based survival at 30/60/90d horizons, 14-day rework, marker-only revert detection, evidence-only AI attribution, for exactly the repos the extracted sessions reference.
*Evidence:* ADR-0006 — first run 2026-08-09: 7 repos, 88 commits, 0 validation failures (production_signal 0.2.0, on disk). Session→repo join rates: claude_code 95% (20/21), codex 81% (17/21), cursor 60% (26/43).
*Note on join rates:* the first-look report's coverage table shows different, higher figures (claude_code 100%, codex 91%, cursor 80%). Both are on disk; they are different instruments over different session sets. ADR-0006's numbers come from the actual session→git-toplevel join (`session_join_stats`) on the 2026-08-09 snapshot and are the citable join-rate measurement. The report column is a weaker proxy (does the session's project have a display-name mapping — self-described as approximate) computed over the current session set, which is now dominated by Caliper's own eval-harness sessions that all live in one repo. Cite ADR-0006, not the report, for join rates.

**Task mining + replay eval (`caliper replay mine|run`)** — mines historically-validated bug-fix tasks (hidden tests fail pre-fix, pass at fix) and replays them headless across model tiers under a locked config.
*Evidence:* ADR-0007 — 30 commons-lang tasks × 3 tiers, 90 eval_result records (0.3.0, on disk): fable-5 20/30 solved ($38.19), sonnet-5 19/30 ($15.85 list; $10.57 at billed intro rate per the ADR-0007 postscript), haiku-4.5 11/30 ($4.46). Total spend $61.08 including pilot. Caveat that travels with every use: commons-lang is in training data — tier-to-tier gaps are meaningful, absolute rates are not.

**Variance run (n_runs=3)** — the follow-up ADR-0007 gated any routing policy on.
*Evidence:* ADR-0008 — 10 tasks × 3 tiers × 3 reps, 90 records on disk ($73.49 list-equivalent). The fable/sonnet gap does not survive (p=0.645); the sonnet/haiku cliff does (p=0.026). 26/30 cells deterministic; ~7% of n=1 cells flipped outright.

**Classifier v0 (`caliper classify`)** — content-free rules classifier + observable-boundary segmenter, validated against the hand-labeled calibration set.
*Evidence:* ADR-0009 — prompt-grain agreement 53.1% (κ 0.41) against 81 human labels; segment-grain 38.5% (κ 0.24); segmenter reproduces 13/13 validatable calibration segments byte-exactly (validation report on disk at `data/derived/classes/validation_report.json`). Current output: 1,571 task_class records (0.1.0) across three unit grains. (ADR-0009 cites 1,446 — that was the count at its run date; the committed jsonl has since been regenerated over newer extractions and is the current figure.)

**First-look report (`caliper report`)** — self-contained HTML: spend by tool/model/project/day at list-price equivalents, task mix by cohort, git outcomes, coverage-and-honesty table.
*Evidence:* generated from current records at `~/.caliper/extracted/report/first_look.html` (295 sessions); absent data renders "not recorded", never zero (enforced by test in `tests/test_report.py`).

**Policy conversation (`caliper policy`, end of `caliper setup`)** — scans classified traffic against rp-0001, shows the overspend verdict, the quality/cost-per-tier charts with CIs, tier access status, and asks the apply question.
*Evidence:* rp-0001 on disk (routing_policy 0.1.0, status **draft**, router_version `manual-adr-0008` — see Stubbed). Tier access gating per ADR-0010: tiers appear in recommendations only when proven by extracted traffic; unmeasured tiers render their access status instead of disappearing. See Known gaps for what the overspend number currently measures.

**Versioned pricing (`caliper pricing update`)** — dated price sheets with a LiteLLM cross-check; billed-rate-at-run-date convention.
*Evidence:* ADR-0007 postscript (caught the sonnet-5 intro-rate mispricing; records not rewritten, restated in citation); snapshots in `harness/replay/pricing_snapshots/`.

## Stubbed

Each of these is deliberately fake or absent today, and each fake is labeled as such on the screen where it appears.

- **Router** — there is no routing engine. `harness/routing/` contains only a design README. The one routing_policy record (rp-0001) was hand-written against the schema (`router_version: manual-adr-0008`), not produced by code.
- **Apply** — `caliper policy apply` writes a local decision log (`~/.caliper/extracted/.policy_decisions.jsonl`, outside the repo) and touches no agent configuration. The screen says so: "the apply engine (native config writes) is future work; no agent config was modified."
- **Trace layer** — `trace_event.schema.json` exists as a contract; `harness/trace/` is a README; zero trace records exist anywhere.
- **Judge track** — `harness/judge/` is a README. No judge code, no rubrics, no calibration set.
- **Dashboard** — `dashboard/` is a README; no Next.js app exists. The CLI's dashboard link is labeled "(preview — dashboard not live yet)".
- **`caliper connect`** — not a subcommand; named on screen as the future path for proving model access (ADR-0010), labeled "(future)".

## Known gaps

- **Extraction is manual against ~3-day log retention.** A raw log present on Aug 7 was gone by Aug 10 (ADR-0009); anything not extracted inside the window is permanently lost, and backfill is lossy by construction. The CLI now warns loudly on every invocation once collection lapses past the window, naming the may-be-lost period (`cli/health.py`, `RETENTION_OBSERVED_DAYS`, ADR-0011; `tests/test_health.py` — and the warning's first live firing caught a real 5-day gap on this machine, 2026-08-23). The daemon itself is still pending; until it ships, the warning is the mitigation.
- **Never run off this machine.** Every number in this file is one solo developer's traffic on one laptop. It validates the instruments, not anyone else's usage.
- **The overspend verdict is currently measuring Caliper's own eval runs.** As of this review, all 46 frontier sessions the policy flow flags as overspend ($49.07 at list) are replay-harness traffic; organic overspend on this machine is ~$0. The screen discloses it ("46 of 46 are Caliper's own eval runs"), but the headline number is meaningless until organic frontier bug-fix traffic exists.
- **Costs are list-price counterfactuals, not real spend.** No agent log contains dollars (ADR-0001), and this machine's traffic is on subscription. Every dollar figure is "what this would have cost at API list rates," clearly labeled — but it has never been validated against a real invoice.
- **Cursor logs carry no tokens and no turns** (ADR-0004) — Cursor sessions are shape-only, unpriceable, and classified at session grain only.
- **The classifier's 53% agreement is the downstream bottleneck.** Task-mix numbers, the policy flow's in-scope selection, and any future mix-weighted routing all inherit it. Strong on exploratory_qa and browser-verification, structurally blind to intent distinctions (bug-fix vs small feature, config vs code) — ADR-0009.
- **Format drift degrades coverage silently.** `additionalProperties: false` catches *new* fields loudly, but when a vendor *removes* a field (Codex dropped its git block in 2026-08 builds, ADR-0005) extraction continues correctly with absent fields and nothing alerts — coverage just sinks. First mitigation shipped: connectors now count unrecognized record shapes per run into the manifest (`notes.unknown_record_types`, ADR-0011; `tests/test_extractor.py`) — the counter's first survey found five undocumented claude_code record types already in live logs. Alarming on jumps is still pending.
- **`session` and `task_class` schemas are still flagged REVIEW REQUIRED** (since ADR-0001). Everything downstream is built on provisionally-shaped records and a `0.1.0-provisional` taxonomy.

## Build order

Synthesized from the ADR follow-up lists; sequence is the current intent, not a commitment.

1. **Field-by-field review of `session` and `task_class`** — open since ADR-0001; everything downstream inherits their provisional shapes.
2. **Continuous extraction** — the retention finding (ADR-0009) makes this the highest-leverage product gap; manual runs lose data permanently.
3. **Classifier 0.2.0** — neighborhood features for flow context, then wider label sets (LLM-judged labeling of a larger local sample) before any learned classifier.
4. **Uncontaminated task source** — JIRA-enriched problem statements, re-run of the 7 all-fail tasks (ADR-0007 finding 4), then a non-public-repo mining source so absolute rates mean something.
5. **Apply engine v0** — native config writes with one-command revert, consuming the decision log the flow already writes.
6. **Trace layer v0** — session→commit joins with commit-time slack after session end (ADR-0006 finding 5), on the `project_ref` join key already validated in both directions.
7. **Web demo of the setup flow** (`docs/setup-demo-web-spec.md`), then the dashboard proper from the report's data model.

The judge track intentionally trails: its calibration set needs human raters (see Blocked).

## Blocked — needs a real team, not this machine

- **Taxonomy and unit-choice validation**: enterprise labels from multiple engineers are the promotion gate (ADR-0002, ADR-0009); solo self-labeled data cannot go further.
- **Segmenter's non-gap rules**: `branch_change` and `file_set_jump` have fired zero times on solo single-branch data (ADR-0002) — they need real branching and multi-module repos to be tested at all.
- **Review friction and revert linkage**: structurally invisible in solo direct-push repos — zero PRs, zero reverts across all 7 local repos (ADR-0006).
- **Judge calibration**: the 100–200 task human-rated set requires practicing engineers (~1hr each).
- **rp-0001 promotion draft→proposed**: requires uncontaminated or enterprise task sources, a classifier-derived mix weight, and production-signal triangulation (ADR-0008).
- **Cost validation**: list-price estimates need at least one org with API billing to compare against invoices.
- **Managed-org mode**: the setup flow's org-policy branch needs an actual managed org (Cursor Teams / Claude Code enterprise) to exist against.
