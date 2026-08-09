# ADR-0004: Extractor v0 — Codex structural validation, Cursor state DB, session schema 0.3.0

**Date:** 2026-08-09 · **Status:** accepted · **Delivers:** the validation ADR required by ADR-0003 §2 before a Codex connector ships

## Context

Caliper's first shipping component is the log extractor: a `caliper extract` CLI over
source plugins (`connectors/`), emitting session records to `data/extracted/`. Building
it forced three things this ADR records: the structural validation of real Codex logs
(the ADR-0001 treatment, which ADR-0003 made a precondition for the `codex` connector),
a structural read of Cursor's global state DB (deferred in ADR-0001), and a schema bump
to 0.3.0 where reality disagreed with 0.2.0.

## Codex: structural validation (rollout JSONL)

Validated against everything on this machine: 21 rollout files under
`~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`, 2026-02 → 2026-08,
`cli_version` 0.99.0-alpha → 0.146.0-alpha, ~25k records. `codex_jsonl` is now a real
format name, not a placeholder.

1. **Envelope, not flat records.** Every line is `{timestamp, type, payload}`; types
   observed: `session_meta`, `turn_context`, `event_msg`, `response_item`, `compacted`,
   `world_state`. Unknown types are ignorable by construction — the envelope makes the
   format forward-tolerant.
2. **One file ≠ one meta.** A rollout file holds one thread but MANY `session_meta`
   records — every resume appends a fresh one with the same id (381 metas across 21
   files). First meta wins for identity; last for `cli_version`. No end marker exists,
   same as Claude Code.
3. **Per-turn model identity exists.** `turn_context` carries `model` + `effort` per
   turn. Real sessions genuinely mix models (one observed session served by both
   `gpt-5.5` at xhigh and `gpt-5.6-sol` at medium). The session schema's `models[]`
   array design is confirmed from a second vendor.
4. **Five token buckets, cumulative.** `event_msg/token_count` carries
   `info.total_token_usage`: `input_tokens`, `cached_input_tokens`,
   `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`. Two semantic
   traps: Codex `input_tokens` INCLUDES cached tokens (Anthropic's excludes them) — the
   connector stores `input - cached` so buckets stay non-overlapping across sources;
   `reasoning_output_tokens` is a subset of `output_tokens`, never additive. The last
   `token_count` in the file is the session total.
5. **Active duration is first-class**: `task_complete.duration_ms` per turn. Also
   `turn_aborted` events (user interruption at turn level) — a friction signal with no
   schema slot yet, since `interrupted_tool_calls` is per-tool; recorded here as a gap,
   not silently shoehorned.
6. **Git context drifts.** `session_meta.git` (branch, commit_hash, repository_url)
   is present through ~0.142 and ABSENT from the newest 2026-08 metas — the same
   fields-appear-and-disappear drift ADR-0001 found in Claude Code logs. 17/21 sessions
   have a branch; the 4 without are the newest. `source_format_version` stays load-bearing.
7. **Automated traffic is structurally marked.** `session_meta.parent_thread_id` links
   child threads; on this machine 10/21 rollout files are `codex-auto-review` runs
   (model id `codex-auto-review`, effort low) spawned off user threads → mapped to
   `parent_session_id`. Nearly half the local Codex "sessions" are automation, cleanly
   separable without content.
8. **Diff evidence is path-level only.** `patch_apply_end.stdout` lists `A/M/D path`
   lines → `files_touched` and `languages` are derivable content-free; line counts are
   not recoverable without reading patch bodies, so `lines_added/removed` are absent for
   Codex rather than approximated.
9. Also present, not extracted: `~/.codex/session_index.jsonl` (`thread_name` is
   content-level), `world_state`/`compacted` records, rate-limit and plan metadata
   inside `token_count` (candidate cost/quota signals for a later version).

## Cursor: global state DB (deferred in ADR-0001, now read)

`~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` has a
`composerHeaders` table (one row per conversation) whose header JSON is content-free
session shape: `createdAt`/`lastUpdatedAt`, `totalLinesAdded/Removed`,
`filesChangedCount`, `unifiedMode`, `isSubagent`, `numSubComposers`, `trackedGitRepos`
(repo path + branch names), `workspaceIdentifier` (workspace path → `project_ref`).
`name`/`subtitle`/`latestConversationSummary` in the same JSON are content-level and are
never extracted; full conversation bodies live in `cursorDiskKV` blobs and are never read.
`conversationId` in `ai-code-tracking.db` equals `composerId` — the join key between
attribution rows and session shape. Per-workspace `state.vscdb` files add nothing the
global DB lacks for v0 and are not read.

Cursor emission is deliberately partial: no turns, no tokens — those fields are absent,
never faked. `scored_commits` is commit-level material for `harness/signals`, counted in
the run manifest but not emitted as sessions.

## Session schema 0.2.0 → 0.3.0

1. **`provenance.content_hash` + `provenance.source_artifacts` (required).** Every
   record carries the source file path(s), row counts where applicable, and a sha256
   over exactly the content it was derived from. This is the extractor's idempotency
   key (unchanged hash → record not rewritten) and the audit chain from any number back
   to a file on disk. Row-scoped hashing for DB sources — whole-DB hashes churn with
   unrelated activity.
2. **`models[].assistant_messages` no longer required.** Cursor attributes lines to a
   model, not messages; forcing a message count would fabricate data. Claude Code and
   Codex still populate it (24/24 and 21/22 model entries in the first real run).
3. **`tokens.reasoning_output` added** (Codex observation), documented as a subset of
   `output`.
4. **`fork_of` added** (nullable, derived). ADR-0002 finding 4: fork/resume writes
   identical records into multiple session files. Detection: sessions sharing their
   first user-prompt record UUID form a fork family; the earliest-started member is the
   original, later members point at it. This makes the double-counting hazard visible
   in the data instead of a footnote.

Widening changes only; no records existed under 0.2.0.

## Extractor decisions

- **Read-only, snapshot-copied.** Originals are never mutated or locked; SQLite files
  (plus `-wal`/`-shm`) are copied to a temp dir and opened read-only there — enforced by
  a test that intercepts `sqlite3.connect`.
- **Content boundary at emission.** Prompt text/file contents are dropped by default.
  `--include-content` writes them to a separate `content.jsonl` sidecar; session records
  are content-free in both modes (the schema forbids content fields either way).
- **Idempotent by content hash.** Re-runs over unchanged sources produce byte-identical
  output, including preserved `extracted_at` on unchanged records. Verified on real
  data: only the session file being appended to by the live session re-extracts.
- **Malformed input is logged, never fatal** — per-line JSON errors, empty files, and
  timestampless files land in the run manifest's `skipped` list with reasons.
- Output: `data/extracted/<source_tool>/sessions.jsonl` + `data/extracted/manifests/<run_id>.json`
  per run. `data/extracted/` is gitignored — local traffic never enters the repo.

## First real run (2026-08-09, this machine)

21 Claude Code sessions (2026-07-09→08-09), 43 Cursor composers (2025-12-16→2026-08-04),
21 Codex threads (2026-02-11→2026-08-03); 0 validation failures. Notables: cache reads
dominate both token-reporting sources (Claude 188.7M cache-read vs 22.7k fresh input;
Codex 527M vs 25.2M) — any cost model ignoring cache is off by orders of magnitude;
`active_duration_ms` exists for only 9/21 Claude sessions (turn_duration records appear
mid-July 2026) but 20/21 Codex sessions; `prompt_source_counts` is Claude-only (10/21,
newer CLI versions); `subagents` is unpopulatable for Codex (child threads are separate
files, linked by parent, with no parent-side count). Fields only one tool can populate:
`prompt_source_counts` (Claude), `tokens.reasoning_output` (Codex), line-level
`diff_stats` with `user_modified_edits` (Claude; Cursor gives totals, Codex only files).
