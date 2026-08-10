"""Claude Code plugin: ~/.claude/projects/**/*.jsonl (+ nested subagent transcripts).

Format facts this parser is grounded in (ADR-0001, re-verified 2026-08-09, log
format `version` 2.x):

- One JSONL file per session, named <session-id>.jsonl, under a per-project dir.
  Subagent transcripts live at <project>/<session-id>/subagents/agent-*.jsonl
  and carry the PARENT's sessionId plus their own agentId.
- Record types observed: user / assistant / system (subtype turn_duration) plus
  bookkeeping (mode, permission-mode, bridge-session, file-history-snapshot,
  attachment, ai-title, last-prompt, ...). Bookkeeping types are ignored.
- Assistant records DUPLICATE message.id (one record per content block, same
  usage object, observed up to 8x). Token sums and message counts MUST be
  deduplicated by message.id or they inflate severalfold.
- Sessions have no end marker; files are appended across resumes. Forked /
  resumed sessions re-write identical records (same uuid) into a new file
  (ADR-0002 finding 4) — handled in finalize() via first-prompt-uuid grouping.
- toolUseResult on user records carries structuredPatch / userModified /
  interrupted; these are the diff and friction signals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from .base import CONNECTOR_VERSION, SESSION_SCHEMA_VERSION, Emission, RawArtifact, SourcePlugin, sha256_file
from .util import (
    iso_utc,
    languages_from_paths,
    ms_between,
    now_iso,
    project_ref,
    prune,
)

_BOOKKEEPING_TYPES = {
    "mode", "permission-mode", "bridge-session", "file-history-snapshot",
    "attachment", "ai-title", "last-prompt", "summary", "queued-prompt",
}

_INTERRUPT_MARKERS = ("[Request interrupted by user", "[Request cancelled",)


def _user_prompt_text(rec: dict) -> str | None:
    """Return the user-authored text of a prompt turn, or None if this user
    record is not a prompt turn (tool result, meta, bookkeeping) — the
    conventions.md definition of a user prompt turn."""
    if rec.get("type") != "user" or rec.get("isMeta"):
        return None
    msg = rec.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        if not parts:
            return None
        text = "\n".join(parts)
    else:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    # command/attachment bookkeeping and interruption markers are not prompts
    if stripped.startswith("<command-name>") or stripped.startswith("<local-command"):
        return None
    if any(stripped.startswith(m) for m in _INTERRUPT_MARKERS):
        return None
    return text


def build_prompt_units(recs: list[dict], session_id: str, salt: str) -> list[dict]:
    """Content-free prompt-unit records (prompt_unit.schema 0.1.0).

    Turn indexing per conventions.md AND the ADR-0002 calibration convention:
    user prompt turns exclude tool results, meta, command/attachment
    bookkeeping, interruption markers, and task-notification records
    (origin.kind == 'task-notification')."""
    from .util import file_refs, path_flags

    conv = [r for r in recs if r.get("type") not in _BOOKKEEPING_TYPES]
    prompt_idx = []
    for i, rec in enumerate(conv):
        text = _user_prompt_text(rec)
        if text is None:
            continue
        origin = rec.get("origin") or {}
        if isinstance(origin, dict) and origin.get("kind") == "task-notification":
            continue
        prompt_idx.append(i)

    units = []
    for n, i in enumerate(prompt_idx):
        rec = conv[i]
        end = prompt_idx[n + 1] if n + 1 < len(prompt_idx) else len(conv)
        window = conv[i + 1:end]
        prev_ts = next((conv[j].get("timestamp") for j in range(i - 1, -1, -1)
                        if conv[j].get("timestamp")), None)
        ts = rec.get("timestamp")
        gap = None
        if prev_ts and ts:
            from .util import iso_utc, ms_between
            gap = ms_between(iso_utc(prev_ts), iso_utc(ts))

        msg_ids, tool_counts, models = set(), {}, set()
        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        saw_usage = interrupted = interrupt_marker = False
        active_ms = None
        files: dict[str, dict] = {}
        la = lr = 0
        last_ts = ts
        for w in window:
            if w.get("timestamp"):
                last_ts = w["timestamp"]
            wtype = w.get("type")
            if wtype == "assistant":
                msg = w.get("message") or {}
                mid = msg.get("id") or w.get("uuid")
                if mid not in msg_ids:
                    msg_ids.add(mid)
                    if msg.get("model"):
                        models.add(msg["model"])
                    u = msg.get("usage") or {}
                    if u:
                        saw_usage = True
                        tokens["input"] += int(u.get("input_tokens") or 0)
                        tokens["output"] += int(u.get("output_tokens") or 0)
                        tokens["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
                        tokens["cache_creation"] += int(u.get("cache_creation_input_tokens") or 0)
                for b in (msg.get("content") or []):
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tn = b.get("name", "?")
                        tool_counts[tn] = tool_counts.get(tn, 0) + 1
            elif wtype == "user":
                tur = w.get("toolUseResult")
                if isinstance(tur, dict):
                    if tur.get("interrupted"):
                        interrupted = True
                    patch = tur.get("structuredPatch")
                    fp = tur.get("filePath")
                    if isinstance(patch, list) and patch and fp:
                        if fp not in files:
                            entry = {**file_refs(salt, fp), **path_flags(fp)}
                            entry["is_new_file"] = tur.get("type") == "create" \
                                if "type" in tur else None
                            files[fp] = entry
                        for hunk in patch:
                            if isinstance(hunk, dict):
                                for hl in hunk.get("lines", []):
                                    if isinstance(hl, str):
                                        if hl.startswith("+"): la += 1
                                        elif hl.startswith("-"): lr += 1
                # interruption marker records are user records too
                msg = w.get("message") or {}
                c = msg.get("content")
                marker = c if isinstance(c, str) else ""
                if isinstance(c, list):
                    marker = " ".join(b.get("text", "") for b in c
                                      if isinstance(b, dict) and b.get("type") == "text")
                if any(marker.strip().startswith(m) for m in _INTERRUPT_MARKERS):
                    interrupt_marker = True
            elif wtype == "system" and w.get("subtype") == "turn_duration":
                d = w.get("durationMs")
                if isinstance(d, (int, float)):
                    active_ms = (active_ms or 0) + int(d)

        from .util import iso_utc as _iso
        units.append({
            "schema_version": "0.1.1",
            "session_id": session_id,
            "source_tool": "claude_code",
            "turn_index": n,
            "started_at": _iso(ts),
            "window_ended_at": _iso(last_ts),
            "gap_ms_before": gap,
            "git_branch": rec.get("gitBranch"),
            "prompt_source": rec.get("promptSource"),
            "origin_kind": (rec.get("origin") or {}).get("kind")
                if isinstance(rec.get("origin"), dict) else None,
            "window": {
                "assistant_messages": len(msg_ids),
                "tool_calls": sum(tool_counts.values()),
                "tool_counts": tool_counts,
                "interrupted": interrupted,
                "interrupt_marker": interrupt_marker,
                "active_ms": active_ms,
                "tokens": tokens if saw_usage else None,
                "models": sorted(models),
                "files_edited": list(files.values()),
                "lines_added": la,
                "lines_removed": lr,
            },
        })
    return units


class ClaudeCodePlugin(SourcePlugin):
    name = "claude_code"
    log_format = "claude_code_jsonl"

    def __init__(self, root: Path | None = None, salt: str = "") -> None:
        super().__init__()
        self.root = Path(root) if root else Path.home() / ".claude" / "projects"
        self.salt = salt

    def discover(self) -> list[RawArtifact]:
        artifacts: list[RawArtifact] = []
        if not self.root.is_dir():
            return artifacts
        for project_dir in sorted(self.root.iterdir()):
            if not project_dir.is_dir():
                continue
            for f in sorted(project_dir.glob("*.jsonl")):
                sub_dir = project_dir / f.stem / "subagents"
                sub_files = sorted(sub_dir.glob("agent-*.jsonl")) if sub_dir.is_dir() else []
                artifacts.append(RawArtifact(
                    path=f, kind="session_jsonl",
                    extra={"subagent_count": len(sub_files)},
                ))
                for sf in sub_files:
                    artifacts.append(RawArtifact(
                        path=sf, kind="subagent_jsonl",
                        extra={"parent_session_id": f.stem},
                    ))
        return artifacts

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
        recs = list(self.read(artifact))
        if not recs:
            self.skip(artifact.path, "empty file")
            return []

        session_id: str | None = None
        cwd = git_branch = source_version = None
        timestamps: list[str] = []
        active_ms = 0
        saw_turn_duration = False
        prompt_turns = 0
        prompt_source_counts: dict[str, int] = {}
        first_prompt_uuid: str | None = None
        interrupted_tools = 0
        tool_counts: dict[str, int] = {}
        # message.id -> (model, usage) — dedupe (records repeat per content block)
        messages_by_id: dict[str, dict] = {}
        model_meta: dict[str, dict] = {}
        diff_files: set[str] = set()
        lines_added = lines_removed = hunks = user_modified = 0
        is_sidechain = False
        content_rows: list[dict] = []

        for rec in recs:
            rtype = rec.get("type")
            if rtype in _BOOKKEEPING_TYPES:
                continue
            ts = rec.get("timestamp")
            if ts:
                timestamps.append(ts)
            if session_id is None and rec.get("sessionId"):
                session_id = rec["sessionId"]
            if cwd is None and rec.get("cwd"):
                cwd = rec["cwd"]
            if git_branch is None and rec.get("gitBranch"):
                git_branch = rec["gitBranch"]
            if source_version is None and rec.get("version"):
                source_version = rec["version"]
            if rec.get("isSidechain"):
                is_sidechain = True

            if rtype == "system" and rec.get("subtype") == "turn_duration":
                d = rec.get("durationMs")
                if isinstance(d, (int, float)):
                    active_ms += int(d)
                    saw_turn_duration = True

            elif rtype == "user":
                text = _user_prompt_text(rec)
                if text is not None:
                    if first_prompt_uuid is None:
                        first_prompt_uuid = rec.get("uuid")
                    prompt_turns += 1
                    ps = rec.get("promptSource")
                    if ps:
                        prompt_source_counts[ps] = prompt_source_counts.get(ps, 0) + 1
                    origin = rec.get("origin")
                    if isinstance(origin, dict) and origin.get("kind"):
                        k = "origin_" + str(origin["kind"])
                        prompt_source_counts[k] = prompt_source_counts.get(k, 0) + 1
                    if include_content:
                        content_rows.append({
                            "role": "user_prompt",
                            "turn_uuid": rec.get("uuid"),
                            "timestamp": ts,
                            "text": text,
                        })
                tur = rec.get("toolUseResult")
                if isinstance(tur, dict):
                    if tur.get("interrupted"):
                        interrupted_tools += 1
                    patch = tur.get("structuredPatch")
                    fp = tur.get("filePath")
                    if isinstance(patch, list) and patch:
                        if fp:
                            diff_files.add(fp)
                        for hunk in patch:
                            if not isinstance(hunk, dict):
                                continue
                            hunks += 1
                            for hl in hunk.get("lines", []):
                                if isinstance(hl, str):
                                    if hl.startswith("+"):
                                        lines_added += 1
                                    elif hl.startswith("-"):
                                        lines_removed += 1
                        if tur.get("userModified"):
                            user_modified += 1

            elif rtype == "assistant":
                msg = rec.get("message") or {}
                mid = msg.get("id") or rec.get("uuid")
                model = msg.get("model")
                if mid not in messages_by_id:
                    messages_by_id[mid] = {"model": model, "usage": msg.get("usage") or {}}
                    if model:
                        usage = msg.get("usage") or {}
                        meta = model_meta.setdefault(model, {
                            "assistant_messages": 0, "effort": None,
                            "speed": None, "service_tier": None,
                        })
                        meta["assistant_messages"] += 1
                        for key, src in (("effort", rec.get("effort") or usage.get("effort")),
                                         ("speed", usage.get("speed")),
                                         ("service_tier", usage.get("service_tier"))):
                            if meta[key] is None and src:
                                meta[key] = src
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tn = block.get("name", "?")
                            tool_counts[tn] = tool_counts.get(tn, 0) + 1

        if session_id is None:
            session_id = artifact.path.stem
        if artifact.kind == "subagent_jsonl":
            # subagent files carry the parent's sessionId; namespace by agent file
            session_id = f"{artifact.extra['parent_session_id']}/{artifact.path.stem}"

        tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
        saw_usage = False
        for m in messages_by_id.values():
            u = m["usage"]
            if not u:
                continue
            saw_usage = True
            tokens["input"] += int(u.get("input_tokens") or 0)
            tokens["output"] += int(u.get("output_tokens") or 0)
            tokens["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
            tokens["cache_creation"] += int(u.get("cache_creation_input_tokens") or 0)

        starts = sorted(iso_utc(t) for t in timestamps if iso_utc(t))
        started_at = starts[0] if starts else None
        ended_at = starts[-1] if starts else None
        if started_at is None:
            self.skip(artifact.path, "no timestamped records")
            return []

        file_hash = sha256_file(artifact.path)
        record = {
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": session_id,
            "source_tool": "claude_code",
            "provenance": {
                "log_format": self.log_format,
                "source_format_version": source_version,
                "connector_version": CONNECTOR_VERSION,
                "extracted_at": now_iso(),
                "content_hash": file_hash,
                "source_artifacts": [
                    {"path": str(artifact.path), "sha256": file_hash}
                ],
            },
            "project_ref": project_ref(self.salt, cwd) if cwd else None,
            "git_branch": git_branch,
            "started_at": started_at,
            "ended_at": ended_at,
            "end_observed": False,  # no end marker exists in this format
            "wall_clock_ms": ms_between(started_at, ended_at),
            "active_duration_ms": active_ms if saw_turn_duration else None,
            "turns": {
                "user_messages": prompt_turns,
                "assistant_messages": len(messages_by_id),
                "tool_calls": sum(tool_counts.values()),
                "interrupted_tool_calls": interrupted_tools,
            },
            "tool_call_pattern": [
                {"tool_name": k, "count": v} for k, v in sorted(tool_counts.items())
            ],
            "models": [
                prune({"model_id": mid, **meta})
                for mid, meta in sorted(model_meta.items())
            ],
            "tokens": tokens if saw_usage else None,
            "diff_stats": {
                "files_touched": len(diff_files),
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "hunks": hunks,
                "user_modified_edits": user_modified,
            } if diff_files or hunks else None,
            "languages": languages_from_paths(diff_files) or None,
            "prompt_source_counts": prompt_source_counts or None,
            "subagents": {
                "count": artifact.extra.get("subagent_count", 0),
                "is_sidechain": is_sidechain,
            } if artifact.kind == "session_jsonl" else {"is_sidechain": is_sidechain},
            "parent_session_id": artifact.extra.get("parent_session_id"),
            # subagent transcripts are agent-spawned by construction; for main
            # sessions no session-level marker exists (prompt_source_counts
            # carries the per-prompt origin mix) -> absent.
            "automated": True if artifact.kind == "subagent_jsonl" else None,
        }
        record = prune(record)
        # models[] items with assistant_messages=0 can't occur (added on first sight)
        record["_fork_key"] = first_prompt_uuid  # stripped in finalize()

        for row in content_rows:
            row.update({"source_tool": "claude_code", "session_id": session_id})
        units = build_prompt_units(recs, session_id, self.salt)
        return [Emission(record=record, content_rows=content_rows,
                         prompt_units=units)]

    def finalize(self, emissions: list[Emission]) -> list[Emission]:
        """Fork/resume detection (ADR-0002 finding 4): sessions sharing the
        same first user-prompt record uuid are one fork family. The earliest-
        started member is the original; later members get fork_of set to it."""
        families: dict[str, list[dict]] = {}
        for e in emissions:
            key = e.record.pop("_fork_key", None)
            if key:
                families.setdefault(key, []).append(e.record)
        for members in families.values():
            members.sort(key=lambda r: (r.get("started_at") or "", r["session_id"]))
            original = members[0]
            original["fork_of"] = None
            for later in members[1:]:
                later["fork_of"] = original["session_id"]
        for e in emissions:
            e.record.setdefault("fork_of", None)
        return emissions
