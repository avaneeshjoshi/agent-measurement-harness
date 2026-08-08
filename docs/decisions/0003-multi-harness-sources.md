# ADR-0003: First-class agent sources and the harness extension path

**Date:** 2026-08-07 · **Status:** accepted

## Context

Caliper measures coding-agent traffic across harnesses. Session schema 0.1.0 hard-coded the two sources whose log formats were structurally validated in ADR-0001 (`claude_code`, `cursor`) plus `other`. Codex is a target source, and more harnesses will appear faster than we can validate them. Without a stated growth policy, new tools either block on schema changes or pool invisibly into `other` forever — both bad.

## Decision

1. **Three first-class sources**: `source_tool` is `claude_code | cursor | codex | other` (session schema 0.2.0); `provenance.log_format` gains `codex_jsonl` and `other`.
2. **`codex` is enum-level support only.** No Codex logs have been structurally inspected; the session schema's `x-provenance` annotations are claims about Claude Code and Cursor logs only. Before a Codex connector ships, its log format gets the same structural-validation treatment as ADR-0001, recorded in an ADR. `codex_jsonl` is a placeholder name for that format until then.
3. **Extension path for future harnesses.** A new harness enters as `source_tool: "other"` with the new nullable `source_tool_other` field carrying its raw name and `provenance.source_format_version` identifying its log format. It is promoted to a first-class enum value when (a) a connector exists and (b) its log format has been structurally validated in an ADR. `other` traffic is reported disaggregated by `source_tool_other`, never dropped or pooled silently.

## Consequences

- Session schema bumps 0.1.0 → 0.2.0. Widening change: every 0.1.0-valid record is 0.2.0-valid. No session records exist yet under 0.1.0, and the committed task_class calibration records are unaffected.
- Adding a harness is now a bounded, repeatable operation: one connector, one grounding ADR, one enum value. Nothing downstream may key on the tool list beyond this enum — classifier/replay/signals/trace consume normalized session records and stay harness-agnostic.
- Risk accepted: `codex_jsonl` may prove to be the wrong shape (Codex may need a DB-style connector like Cursor's, or its logs may lack fields the schema marks observed). The validation ADR will correct this; until then no code may assume Codex field presence.
