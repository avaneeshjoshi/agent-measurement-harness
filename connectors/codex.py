"""Codex plugin: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

Format facts, structurally validated on this machine 2026-08-09 (ADR-0004),
across cli_version 0.99.x (2026-02) .. 0.146.x (2026-08):

- Envelope per line: {timestamp, type, payload}. Types seen: session_meta,
  turn_context, event_msg, response_item, compacted, world_state.
- A rollout FILE holds one thread but MANY session_meta records — every
  resume/restart appends a fresh session_meta with the same id. The file name
  and meta id agree; first meta wins for identity, last for cli_version.
- turn_context carries PER-TURN model + effort ('gpt-5.5', 'gpt-5.6-sol',
  'codex-auto-review', ...) — per-turn model identity exists in this format.
- event_msg token_count carries cumulative info.total_token_usage with FIVE
  buckets: input_tokens (INCLUDES cached), cached_input_tokens,
  cache_write_input_tokens, output_tokens, reasoning_output_tokens (subset of
  output). The last token_count in the file is the session total.
- event_msg task_complete carries duration_ms -> active_duration_ms.
- event_msg turn_aborted is a user-interruption signal (turn-level; noted in
  ADR-0004, not mapped to interrupted_tool_calls whose semantics are per-tool).
- session_meta.git carries branch / commit_hash / repository_url.
- session_meta.parent_thread_id marks child threads (auto-review, subthreads)
  -> parent_session_id.
- Tool calls are response_item function_call (name: exec_command, js, wait,
  ...) and custom_tool_call (name: exec, apply_patch); MCP calls surface in
  event_msg mcp_tool_call_end with invocation.server/.tool.
- patch_apply_end events list files changed in stdout ('A path' / 'M path'
  lines) -> files_touched + languages, content-free. Line counts are NOT
  recoverable without reading patch content, so lines_added/removed are absent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .base import CONNECTOR_VERSION, Emission, RawArtifact, SourcePlugin, sha256_file
from .util import (
    iso_utc,
    languages_from_paths,
    ms_between,
    now_iso,
    project_ref,
    prune,
)


class CodexPlugin(SourcePlugin):
    name = "codex"
    log_format = "codex_jsonl"

    def __init__(self, root: Path | None = None, salt: str = "") -> None:
        super().__init__()
        self.root = Path(root) if root else Path.home() / ".codex" / "sessions"
        self.salt = salt

    def discover(self) -> list[RawArtifact]:
        if not self.root.is_dir():
            return []
        return [RawArtifact(path=f, kind="rollout_jsonl")
                for f in sorted(self.root.glob("*/*/*/rollout-*.jsonl"))]

    def read(self, artifact: RawArtifact) -> Iterator[dict]:
        with open(artifact.path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    self.skip(f"{artifact.path}:{i + 1}", "malformed JSON line")

    def emit(self, artifact: RawArtifact, include_content: bool = False) -> list[Emission]:
        first_meta: dict | None = None
        last_meta: dict | None = None
        meta_count = 0
        timestamps: list[str] = []
        user_msgs = agent_msgs = 0
        tool_counts: dict[str, int] = {}
        model_meta: dict[str, dict] = {}
        current_model: str | None = None
        last_token_info: dict | None = None
        active_ms = 0
        saw_duration = False
        turn_aborts = 0
        patched_files: set[str] = set()
        content_rows: list[dict] = []

        for rec in self.read(artifact):
            ts = rec.get("timestamp")
            if ts:
                timestamps.append(ts)
            rtype = rec.get("type")
            payload = rec.get("payload") or {}

            if rtype == "session_meta":
                meta_count += 1
                last_meta = payload
                if first_meta is None:
                    first_meta = payload

            elif rtype == "turn_context":
                model = payload.get("model")
                if model:
                    current_model = model
                    meta = model_meta.setdefault(model, {
                        "assistant_messages": 0, "effort": None,
                    })
                    if meta["effort"] is None and payload.get("effort"):
                        meta["effort"] = payload["effort"]

            elif rtype == "event_msg":
                etype = payload.get("type")
                if etype == "user_message":
                    user_msgs += 1
                    if include_content and payload.get("message"):
                        content_rows.append({
                            "role": "user_prompt",
                            "timestamp": ts,
                            "text": payload["message"],
                        })
                elif etype == "agent_message":
                    agent_msgs += 1
                    if current_model:
                        model_meta[current_model]["assistant_messages"] += 1
                elif etype == "token_count":
                    info = payload.get("info") or {}
                    total = info.get("total_token_usage")
                    if total:
                        last_token_info = total
                elif etype == "task_complete":
                    d = payload.get("duration_ms")
                    if isinstance(d, (int, float)):
                        active_ms += int(d)
                        saw_duration = True
                elif etype == "turn_aborted":
                    turn_aborts += 1
                elif etype == "mcp_tool_call_end":
                    inv = payload.get("invocation") or {}
                    name = f"mcp__{inv.get('server', '?')}__{inv.get('tool', '?')}"
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                elif etype == "patch_apply_end":
                    # stdout lists 'A path' / 'M path' / 'D path' lines — file
                    # paths only, no file content.
                    for line in (payload.get("stdout") or "").splitlines():
                        parts = line.split(None, 1)
                        if len(parts) == 2 and parts[0] in ("A", "M", "D"):
                            patched_files.add(parts[1].strip())

            elif rtype == "response_item":
                ptype = payload.get("type")
                if ptype in ("function_call", "custom_tool_call"):
                    name = payload.get("name") or "?"
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                elif ptype in ("web_search_call", "tool_search_call"):
                    tool_counts[ptype] = tool_counts.get(ptype, 0) + 1

        if first_meta is None:
            self.skip(artifact.path, "no session_meta record")
            return []

        session_id = first_meta.get("id") or first_meta.get("session_id") or artifact.path.stem
        cwd = first_meta.get("cwd")
        git = first_meta.get("git") or {}
        cli_version = (last_meta or first_meta).get("cli_version")

        starts = sorted(iso_utc(t) for t in timestamps if iso_utc(t))
        started_at = starts[0] if starts else None
        ended_at = starts[-1] if starts else None
        if started_at is None:
            self.skip(artifact.path, "no timestamped records")
            return []

        tokens = None
        if last_token_info:
            raw_input = int(last_token_info.get("input_tokens") or 0)
            cached = int(last_token_info.get("cached_input_tokens") or 0)
            tokens = {
                # Codex input_tokens INCLUDES cached; split to keep buckets
                # non-overlapping across sources (documented in schema 0.3.0).
                "input": max(0, raw_input - cached),
                "output": int(last_token_info.get("output_tokens") or 0),
                "cache_read": cached,
                "cache_creation": int(last_token_info.get("cache_write_input_tokens") or 0),
                "reasoning_output": int(last_token_info.get("reasoning_output_tokens") or 0),
            }

        file_hash = sha256_file(artifact.path)
        record = {
            "schema_version": "0.3.0",
            "session_id": session_id,
            "source_tool": "codex",
            "provenance": {
                "log_format": self.log_format,
                "source_format_version": cli_version,
                "connector_version": CONNECTOR_VERSION,
                "extracted_at": now_iso(),
                "content_hash": file_hash,
                "source_artifacts": [
                    {"path": str(artifact.path), "sha256": file_hash,
                     "note": f"{meta_count} session_meta records (resumes)" if meta_count > 1 else None}
                ],
            },
            "project_ref": project_ref(self.salt, cwd) if cwd else None,
            "git_branch": git.get("branch"),
            "started_at": started_at,
            "ended_at": ended_at,
            "end_observed": False,  # rollout files are appended across resumes
            "wall_clock_ms": ms_between(started_at, ended_at),
            "active_duration_ms": active_ms if saw_duration else None,
            "turns": {
                "user_messages": user_msgs,
                "assistant_messages": agent_msgs,
                "tool_calls": sum(tool_counts.values()),
            },
            "tool_call_pattern": [
                {"tool_name": k, "count": v} for k, v in sorted(tool_counts.items())
            ],
            "models": [
                prune({"model_id": mid,
                       "assistant_messages": meta["assistant_messages"] or None,
                       "effort": meta["effort"]})
                for mid, meta in sorted(model_meta.items())
            ],
            "tokens": tokens,
            "diff_stats": {
                "files_touched": len(patched_files),
            } if patched_files else None,
            "languages": languages_from_paths(patched_files) or None,
            "parent_session_id": first_meta.get("parent_thread_id"),
        }
        record = prune(record)

        for row in content_rows:
            row.update({"source_tool": "codex", "session_id": session_id})
        return [Emission(record=record, content_rows=content_rows)]
