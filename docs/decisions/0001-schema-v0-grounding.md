# ADR-0001: Schema v0 grounded in real session-log structure

**Date:** 2026-08-07 · **Status:** proposed (awaiting field-by-field review of `session` and `task_class`)

## Context

Before drafting the six v0 schemas, we structurally validated against real data on this machine:

- **Claude Code**: 20 JSONL session files under `~/.claude/projects/` (5 projects, Jul–Aug 2026, log format `version` 2.x), including nested subagent transcripts (`<session-id>/subagents/agent-*.jsonl`). ~2,300 conversational records analyzed for record types, key sets, and value distributions.
- **Cursor**: `~/.cursor/ai-tracking/ai-code-tracking.db` (SQLite): `ai_code_hashes` (2,598 rows; source ∈ {composer, tab, human}, model, conversationId), `scored_commits` (72 rows; per-commit line counts split tab/composer/human/blank + v1/v2 aiPercentage), `conversation_summaries` (content-level; **not ingested**). Per-workspace chat state in `state.vscdb` exists but was not parsed for v0.

**Scope limit (stated by the project owner):** these logs validate *structure only* — what the formats record. They are one solo developer's greenfield sessions and are **not** evidence about enterprise task distributions. Taxonomy claims below are flagged accordingly.

## What real data settled (structure)

1. **Sessions have no end marker.** Files are appended across resumes; observed sessions span up to 5 days of wall clock. → `end_observed: false`, `wall_clock_ms` vs `active_duration_ms` (from per-turn `turn_duration.durationMs` records) kept separate.
2. **Cost is not in any log.** Tokens are (including dominant cache read/creation counts); dollars are not. → `cost_usd` is aspirational and must carry `pricing_source`.
3. **Log formats drift within weeks.** `promptSource`/`origin` present in Aug-2026 sessions, null in Jul-2026 ones; `effort`/`speed` usage keys likewise. → `source_format_version` is required; absent = "unrecorded", never defaulted.
4. **Diff size is derivable, content-free.** Edit/Write results carry `structuredPatch` hunks; also `userModified` (human edited the AI's patch) and `interrupted` (user cancelled) flags — both kept as first-class friction/attribution signals.
5. **Vendor AI attribution exists and is *partially populated*.** Cursor scores commits with per-source line counts — and only 11 of 72 scored_commits rows had counts filled in. → `known | partial | unknown` with `partial` as a normal state is not a design nicety; it matches the best available vendor data.
6. **Sessions mix models** (primary + fallback + `<synthetic>` bookkeeping records) → `models[]` array, not a scalar; connectors must label synthetic records.
7. **Subagents are real and separate** → parent stats exclude them; `parent_session_id` links them.

## Field provenance summary (session schema)

- **Observed**: session_id, git_branch, model ids, token/cache counts, effort/speed/service_tier, tool names, interrupted, userModified, subagent structure, prompt source (newer logs only), log version.
- **Derived**: start/end timestamps, wall-clock and active durations, turn/tool counts, diff stats, languages (extension-only), project_ref (hashed cwd).
- **Aspirational**: cost_usd, team_ref, patches_accepted/rejected (in *neither* source — Cursor tracks line origin, not accept events), segments.

## Where the draft taxonomy failed against real sessions

These are interview questions, not conclusions — local data is unrepresentative (solo, greenfield, no tickets/reviews/tests):

1. **Session ≠ task.** Observed sessions run days and change task mid-stream (one session: explore repo → Q&A → schema drafting). The classification *unit* is unsettled → `segments` (aspirational) in the session schema; `subject.segment_id` in task_class. *Enterprise data needed: whether engineers' sessions are similarly multi-task, and what boundary (idle gap? new ticket?) matches their mental model.*
2. **Verification-loop work has no slot.** A 12MB session dominated by browser-automation tool calls (iterating on UI behavior; huge session, modest diff) fits none of the eight types → provisional `ui_verification_loop`. *Interview: is "watch the agent verify its own work" a recognized work category in enterprise?*
3. **Agent-meta work has no slot.** Sessions spent configuring/orchestrating the agent tooling itself → provisional `agent_meta_work`. *Interview: how much enterprise traffic is tool-tending overhead?*
4. **Risk axes are unvalidatable locally.** Zero observed projects have test suites; nothing local distinguishes production-critical from tooling. Axes kept, with `unknown`, on theory alone. *Enterprise data needed to confirm they're even detectable from metadata.*
5. **cross_repo is nearly invisible** in per-cwd logs. Under-detection is structural until multi-repo telemetry exists.
6. **Distribution claims deferred.** Local mix (heavy feature/scaffolding, zero test_authoring on legacy code, zero review-driven rework) says nothing about the target population and was not used to weight or prune the taxonomy.

## Decisions

- Six self-contained v0 schemas (`0.1.0`), conventions in `docs/conventions.md`, `x-provenance` annotations on session fields.
- `session` + `task_class` flagged REVIEW REQUIRED in their descriptions; the other four are plumbing drafted on stated assumptions (see their descriptions).
- Cursor ingestion path for v0 is the tracking DB (structural attribution), not `state.vscdb` chat parsing; `conversation_summaries` is content-level and stays out.
