"""Extractor tests: schema validity, idempotency, content boundary, and one
format test per source plugin — all through the real extract() pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import REPO, SCHEMA, read_sessions

CLAUDE_MARKER = "FIXTURE_SECRET_PROMPT"
CODEX_MARKER = "CODEX_SECRET_PROMPT"
CURSOR_MARKER = "CURSOR_SECRET_TITLE"
ALL_MARKERS = (CLAUDE_MARKER, CODEX_MARKER, CURSOR_MARKER)


# ---------------------------------------------------------------- validation

def test_all_emitted_records_validate(run_extract):
    manifest, data_dir = run_extract()
    validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
    total = 0
    for tool in ("claude_code", "cursor", "codex"):
        assert manifest["sources"][tool]["records"]["invalid"] == 0
        for rec in read_sessions(data_dir, tool):
            validator.validate(rec)
            total += 1
    assert total >= 7  # 3 claude (2 emitted + fork) + 2 cursor + 2 codex


def test_manifest_written_per_run(run_extract):
    manifest, data_dir = run_extract()
    path = data_dir / "manifests" / f"{manifest['run_id']}.json"
    assert path.exists()
    on_disk = json.loads(path.read_text())
    assert on_disk["sources"].keys() == manifest["sources"].keys()
    # skips are recorded with reasons, never fatal: the malformed line in
    # session 3333... is logged
    reasons = [s["reason"] for s in on_disk["sources"]["claude_code"]["skipped"]]
    assert any("malformed" in r for r in reasons)


# --------------------------------------------------------------- idempotency

def test_rerun_is_byte_identical(run_extract):
    m1, data_dir = run_extract()
    files1 = {t: (data_dir / t / "sessions.jsonl").read_bytes()
              for t in ("claude_code", "cursor", "codex")}
    m2, _ = run_extract()
    files2 = {t: (data_dir / t / "sessions.jsonl").read_bytes()
              for t in ("claude_code", "cursor", "codex")}
    assert files1 == files2
    for tool in files1:
        counts = m2["sources"][tool]["records"]
        assert counts["new"] == 0 and counts["updated"] == 0
        assert counts["unchanged"] == counts["emitted"]


# ----------------------------------------------------------- content boundary

def test_no_content_without_flag(run_extract):
    _, data_dir = run_extract(include_content=False)
    for path in data_dir.rglob("*"):
        if path.is_file():
            blob = path.read_text(errors="replace")
            for marker in ALL_MARKERS:
                assert marker not in blob, f"{marker} leaked into {path}"
    assert not list(data_dir.rglob("content.jsonl"))


def test_content_flag_writes_sidecar_only(run_extract):
    _, data_dir = run_extract(include_content=True)
    # prompt text appears in the sidecar...
    claude_sidecar = (data_dir / "claude_code" / "content.jsonl").read_text()
    codex_sidecar = (data_dir / "codex" / "content.jsonl").read_text()
    assert CLAUDE_MARKER in claude_sidecar
    assert CODEX_MARKER in codex_sidecar
    # ...and still never inside session records
    for tool in ("claude_code", "cursor", "codex"):
        blob = (data_dir / tool / "sessions.jsonl").read_text()
        for marker in ALL_MARKERS:
            assert marker not in blob
    # cursor content (composer names/summaries) is never extracted at all
    assert not (data_dir / "cursor" / "content.jsonl").exists()


# ------------------------------------------------------- claude_code format

def test_claude_code_session_shape(run_extract):
    _, data_dir = run_extract()
    recs = {r["session_id"]: r for r in read_sessions(data_dir, "claude_code")}
    r = recs["11111111-1111-1111-1111-111111111111"]

    # usage deduped by message.id: msg_001 appears on two records but counts once
    assert r["tokens"] == {"input": 15, "output": 70,
                           "cache_read": 2200, "cache_creation": 200}
    assert r["turns"] == {"user_messages": 1, "assistant_messages": 2,
                          "tool_calls": 2, "interrupted_tool_calls": 1}
    # tool-result / isMeta user records are not prompt turns
    assert r["prompt_source_counts"] == {"typed": 1, "origin_human": 1}
    assert r["diff_stats"] == {"files_touched": 1, "lines_added": 2,
                               "lines_removed": 1, "hunks": 1,
                               "user_modified_edits": 0}
    assert r["languages"] == ["python"]
    assert r["models"][0]["model_id"] == "claude-fable-5"
    assert r["models"][0]["assistant_messages"] == 2
    assert r["active_duration_ms"] == 9000
    assert r["end_observed"] is False
    assert r["git_branch"] == "main"
    assert r["provenance"]["source_format_version"] == "2.1.100"
    assert r["provenance"]["content_hash"].startswith("sha256:")
    assert r["provenance"]["source_artifacts"][0]["path"].endswith(".jsonl")
    # raw cwd never appears; project_ref is opaque
    assert r["project_ref"].startswith("p_")
    assert "/Users/test/proja" not in json.dumps(r)


def test_claude_code_fork_detection(run_extract):
    _, data_dir = run_extract()
    recs = {r["session_id"]: r for r in read_sessions(data_dir, "claude_code")}
    original = recs["11111111-1111-1111-1111-111111111111"]
    fork = recs["22222222-2222-2222-2222-222222222222"]
    unrelated = recs["33333333-3333-3333-3333-333333333333"]
    # sessions 1111 and 2222 share their first prompt uuid (u-prompt-1):
    # the earlier-started one is the original
    assert original["fork_of"] is None
    assert fork["fork_of"] == "11111111-1111-1111-1111-111111111111"
    assert unrelated["fork_of"] is None


# ------------------------------------------------------------- codex format

def test_codex_session_shape(run_extract):
    _, data_dir = run_extract()
    recs = {r["session_id"]: r for r in read_sessions(data_dir, "codex")}
    r = recs["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]

    # buckets from the LAST cumulative token_count; input excludes cached
    assert r["tokens"] == {"input": 3000, "output": 700, "cache_read": 6000,
                           "cache_creation": 100, "reasoning_output": 220}
    # per-turn model identity: both models present with per-model message counts
    models = {m["model_id"]: m for m in r["models"]}
    assert models["gpt-5.5"]["assistant_messages"] == 1
    assert models["gpt-5.5"]["effort"] == "high"
    assert models["gpt-5.6-sol"]["assistant_messages"] == 1
    assert models["gpt-5.6-sol"]["effort"] == "medium"
    assert r["turns"] == {"user_messages": 2, "assistant_messages": 2, "tool_calls": 3}
    tools = {t["tool_name"]: t["count"] for t in r["tool_call_pattern"]}
    assert tools == {"exec_command": 1, "apply_patch": 1, "mcp__node_repl__js": 1}
    assert r["active_duration_ms"] == 15000
    assert r["git_branch"] == "feature/x"
    # files from patch_apply_end stdout; line counts are NOT recoverable -> absent
    assert r["diff_stats"] == {"files_touched": 2}
    assert sorted(r["languages"]) == ["python"]
    # resume appended a second session_meta; last cli_version wins
    assert r["provenance"]["source_format_version"] == "0.141.0"
    assert "resumes" in (r["provenance"]["source_artifacts"][0].get("note") or "")


def test_codex_child_thread_parent_link(run_extract):
    _, data_dir = run_extract()
    recs = {r["session_id"]: r for r in read_sessions(data_dir, "codex")}
    child = recs["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]
    assert child["parent_session_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    # a session with no user_message events reports zero, not absence — the
    # log observed the absence of prompts
    assert child["turns"]["user_messages"] == 0


# ------------------------------------------------------------ cursor format

def test_cursor_partial_records(run_extract):
    _, data_dir = run_extract()
    recs = {r["session_id"]: r for r in read_sessions(data_dir, "cursor")}
    r = recs["cccccccc-1111"]

    # Cursor cannot provide turns or tokens: ABSENT, not defaulted
    assert "turns" not in r and "tokens" not in r
    assert r["diff_stats"] == {"files_touched": 3, "lines_added": 120,
                               "lines_removed": 30}
    # models from attribution rows: composer/tab sources with non-empty model
    assert r["models"] == [{"model_id": "grok-4.5"}]
    assert r["git_branch"] == "main"
    assert r["subagents"] == {"count": 1}
    assert sorted(r["languages"]) == ["python", "typescript"]
    assert r["project_ref"].startswith("p_")
    assert r["started_at"].startswith("2026-01-05")  # epoch ms converted
    two = r["provenance"]["source_artifacts"]
    assert {a["note"] for a in two} == {"composerHeaders", "ai_code_hashes"}

    # orphan conversation: tracking-db rows only, still emitted
    orphan = recs["dddddddd-2222"]
    assert orphan["provenance"]["log_format"] == "cursor_tracking_db"
    assert orphan["models"] == [{"model_id": "default"}]
    assert "diff_stats" not in orphan


def test_cursor_reads_snapshot_not_live_db(run_extract, cursor_dbs, monkeypatch):
    """The live DB paths must never be opened by sqlite directly."""
    import sqlite3 as sql
    import connectors.cursor as cursor_mod

    live = {str(cursor_dbs["tracking"]), str(cursor_dbs["state"])}
    real_connect = sql.connect

    def guarded(path, *a, **kw):
        p = str(path).replace("file:", "").split("?")[0]
        assert p not in live, f"live DB opened directly: {p}"
        return real_connect(path, *a, **kw)

    monkeypatch.setattr(cursor_mod.sqlite3, "connect", guarded)
    run_extract(sources=("cursor",))
