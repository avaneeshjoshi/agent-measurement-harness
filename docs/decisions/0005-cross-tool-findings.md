# ADR-0005: Cross-tool findings from the first extractor run — normalization rules they force

**Date:** 2026-08-09 · **Status:** accepted · **Supplements:** ADR-0004 (which records per-format facts; this ADR records what emerged only from comparing tools)

## Context

The first real `caliper extract` run put Claude Code, Cursor, and Codex records side by
side for the first time (21 / 43 / 21 sessions on one machine). Five findings only exist
at the comparison level, and two forced changes (session schema 0.4.0, connector 0.2.0).
Recorded now, while the evidence is reproducible from the run manifests.

## 1. Token accounting is incompatible across vendors

**Codex `input_tokens` INCLUDES `cached_input_tokens`; Anthropic's `input_tokens`
EXCLUDES cache reads.** The same field name, different semantics. On this machine's
traffic, naive cross-tool summing of `input_tokens` would double-count ~95% of Codex
input (25.2M raw input of which 527M-adjacent cache traffic dominates; observed
cached/input ratio ≈ 0.95 across sessions).

**Normalization rule (implemented in the Codex connector, documented in the schema):**
`tokens.input = input_tokens − cached_input_tokens`, `tokens.cache_read =
cached_input_tokens`, `tokens.cache_creation = cache_write_input_tokens`. The invariant
every connector must maintain: **the four token buckets are non-overlapping everywhere;
`input` always means non-cached input.** `reasoning_output` is a subset of `output`
(Codex-only), never additive. Any future connector must state which convention its
vendor uses and normalize to this one.

## 2. Automated agent-to-agent traffic is real, billed, and separable

In THIS machine's logs, 10/21 Codex threads were auto-review children
(`parent_thread_id` + `thread_source: subagent`, model `codex-auto-review`).
**Caveat, stated plainly: that ratio reflects one developer's personal auto-review hook
setup, not a tool default, and generalizes to nothing.** The generalizable findings are:

- automated traffic exists in real logs and consumes billed tokens like human work;
- it is cleanly separable WITHOUT content, from structural markers
  (`thread_source`, parent linkage, subagent file layout, `isSubagent`);
- any usage distribution that doesn't separate it conflates tool overhead with
  human demand.

**Change: session schema 0.4.0 adds nullable `automated`**, emitted from observed
markers only — Codex `thread_source` ('user' → false, other recorded values → true,
absent → absent), Claude Code subagent transcripts → true, Cursor `isSubagent`
composers → true. Distribution on this machine's traffic: codex 10 true / 10 false /
1 absent (pre-2026-05 meta lacks the field); claude_code 10 true (all subagent
transcripts) / 11 absent; cursor 2 true / 41 absent. `parent_session_id` was already
emitted (ADR-0004). No marker → absent, never inferred from behavior.

## 3. The cross-tool join key works on real data

Cursor and Claude Code sessions from the same workspace produce the **same salted
`project_ref`** (Cursor hashes `workspaceIdentifier.fsPath`, Claude Code hashes `cwd`
— when the workspace root is the session cwd these coincide, and on this machine they
do for the shared projects). Validated on real records, not by construction: the trace
layer's session→repo join key is `project_ref`, and it holds across vendors. Codex
`cwd` joins the same way. Known limit: sessions started in a subdirectory of the repo
hash differently than the workspace root — repo-root canonicalization is future
connector work and will be needed before join rates can be trusted at scale.

## 4. Format drift is now a two-vendor observation

ADR-0001 documented fields appearing between Claude Code CLI versions within weeks
(`promptSource`). The Codex validation found the same phenomenon in the opposite
direction: the `session_meta.git` block (branch/commit/repo URL) is present through
cli ~0.142 and **absent from the newest 2026-08 metas**; `thread_source` appears
~2026-05. Implication, now policy: **`source_format_version` handling is permanent
connector maintenance, not a v0 crutch.** Connectors treat every absent field as
"unrecorded for this version", parsers key on observed structure rather than assumed
presence, and each format change discovered lands in the plugin docstring + an ADR
note. No connector is ever "done".

## 5. Coverage asymmetries to remember when comparing tools

From the field-coverage matrix (full table in ADR-0004):

- `active_duration_ms`: Codex 20/21 vs Claude Code 9/21 (turn_duration records only
  exist in newer CLI versions) vs Cursor 0. Duration comparisons across tools are
  version-gated, not tool-gated.
- `git_branch`: Claude Code 21/21, Codex 17/21 (drift, §4), Cursor 2/43 (only
  single-repo single-branch composers, by the conservative emission rule).
  Branch-based trace joins will be Claude-heavy until Cursor linkage improves.
- Diff granularity is three different things: Claude Code has line-level hunks +
  `user_modified_edits`; Cursor has conversation-level line totals; Codex has file
  paths only. `diff_stats` sub-fields are comparable only where both sides populate
  them — aggregations must not treat absent as zero (conventions.md already forbids it).

## Consequences

- Session schema 0.3.0 → 0.4.0 (widening: nullable `automated`). Connector 0.2.0.
- The store's "unchanged" rule now includes schema+connector version, so contract
  bumps re-emit records even when source content is unchanged — idempotency holds
  within a contract version.
- Cross-tool reports must always (a) use normalized token buckets, (b) split by
  `automated` where present, (c) treat absent fields as unrecorded, never zero.
