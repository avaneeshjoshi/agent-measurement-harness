"""Continuous-collection runtime (ADR-0011): lock, state, activity gate,
mtime watermark, and the fork-link healing the daily full pass provides."""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from caliper.cli.collection import (WATERMARK_SLACK_S, acquire_lock, artifact_mtime,
                            load_state, mark_covered, run_scheduled,
                            save_state)
from caliper.cli.main import extract
from caliper.cli.paths import extracted_dir, state_dir
from caliper.connectors.claude_code import ClaudeCodePlugin
from tests.conftest import FIXTURES, SCHEMA

ORIGINAL = "11111111-1111-1111-1111-111111111111"
FORK = "22222222-2222-2222-2222-222222222222"


def _claude_root(tmp_path: Path) -> Path:
    root = tmp_path / "claude_code"
    shutil.copytree(FIXTURES / "claude_code", root)
    return root


def _plugin(root: Path) -> ClaudeCodePlugin:
    return ClaudeCodePlugin(root=root, salt="test-salt")


def _sessions(data_dir: Path) -> dict[str, dict]:
    path = data_dir / "claude_code" / "sessions.jsonl"
    return {r["session_id"]: r for r in
            (json.loads(l) for l in path.read_text().splitlines())}


def _utime_all(root: Path, when: float, except_stems: set[str] = frozenset()):
    for p in root.rglob("*.jsonl"):
        if p.stem not in except_stems:
            os.utime(p, (when, when))


# ---- lock ------------------------------------------------------------------

def test_lock_contention_and_release(tmp_path):
    first = acquire_lock(tmp_path)
    assert first is not None
    assert acquire_lock(tmp_path) is None
    first.close()
    second = acquire_lock(tmp_path)
    assert second is not None
    second.close()


# ---- state -----------------------------------------------------------------

def test_state_roundtrip_and_default_merge(tmp_path):
    state = load_state(tmp_path)
    assert state["include_content"] is False
    state["include_content"] = True
    state["last_covered"]["codex"] = "2026-08-23T00:00:00+00:00"
    save_state(tmp_path, state)
    again = load_state(tmp_path)
    assert again["include_content"] is True
    assert again["last_covered"]["codex"].startswith("2026-08-23")
    assert "pending_alarms" in again  # defaults merge over stored subsets


def test_mark_covered_updates_watermark_and_full_pass(tmp_path):
    now = datetime.now(timezone.utc)
    mark_covered(tmp_path, ["claude_code"], now, full=True)
    state = load_state(tmp_path)
    assert state["last_covered"]["claude_code"] == now.isoformat(timespec="seconds")
    assert state["watermark"]["claude_code"] == now.timestamp()
    assert state["last_full_pass"] is not None


# ---- watermark -------------------------------------------------------------

def test_wal_sibling_mtime_counts(tmp_path):
    db = tmp_path / "state.db"
    db.write_text("x")
    old = time.time() - 9999
    os.utime(db, (old, old))
    wal = tmp_path / "state.db-wal"
    wal.write_text("y")
    assert artifact_mtime(db) == wal.stat().st_mtime


def test_watermark_filters_stale_artifacts_and_preserves_records(tmp_path):
    root = _claude_root(tmp_path)
    data_dir = tmp_path / "extracted"
    extract(["claude_code"], data_dir, SCHEMA, include_content=False,
            plugins_override={"claude_code": _plugin(root)})
    before = (data_dir / "claude_code" / "sessions.jsonl").read_bytes()

    now = time.time()
    _utime_all(root, now - 2 * WATERMARK_SLACK_S)
    m = extract(["claude_code"], data_dir, SCHEMA, include_content=False,
                plugins_override={"claude_code": _plugin(root)},
                since={"claude_code": now}, trigger="scheduled")
    src = m["sources"]["claude_code"]
    assert src["notes"]["artifacts_filtered_by_watermark"] == \
        src["artifacts_discovered"]
    assert src["artifacts_read"] == 0
    # filtered files lose nothing: the store was never touched
    assert (data_dir / "claude_code" / "sessions.jsonl").read_bytes() == before
    assert m["trigger"] == "scheduled"
    assert m["connector_version"] and m["schema_version"]


def test_fork_link_healed_by_full_pass(tmp_path):
    """The known incremental-mode hole (ADR-0011): a fork extracted without
    its original gets fork_of=None; the daily full pass re-derives the family
    and the store's record-equality rule lets the correction land."""
    root = _claude_root(tmp_path)
    data_dir = tmp_path / "extracted"
    now = time.time()
    # only the fork's file looks new -> incremental run emits it alone
    # (copytree preserved the fixtures' old mtimes, so stamp both ends)
    _utime_all(root, now - 2 * WATERMARK_SLACK_S, except_stems={FORK})
    fork_file = next(p for p in root.rglob(f"{FORK}.jsonl"))
    os.utime(fork_file, (now, now))
    extract(["claude_code"], data_dir, SCHEMA, include_content=False,
            plugins_override={"claude_code": _plugin(root)},
            since={"claude_code": now}, trigger="scheduled")
    assert _sessions(data_dir)[FORK]["fork_of"] is None  # wrong, and known

    m = extract(["claude_code"], data_dir, SCHEMA, include_content=False,
                plugins_override={"claude_code": _plugin(root)})
    assert _sessions(data_dir)[FORK]["fork_of"] == ORIGINAL  # healed
    assert m["sources"]["claude_code"]["records"]["updated"] >= 1


# ---- scheduled runner ------------------------------------------------------

def _seed_state(covered_and_watermarked: bool, include_content=False):
    data_dir = extracted_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(state_dir())
    now = datetime.now(timezone.utc)
    state["include_content"] = include_content
    if covered_and_watermarked:
        state["last_full_pass"] = now.isoformat(timespec="seconds")
        state["watermark"] = {"claude_code": now.timestamp()}
    save_state(state_dir(), state)
    return data_dir


def test_scheduled_skips_when_lock_held(tmp_path):
    lock = acquire_lock(state_dir())
    try:
        assert run_scheduled(Path.cwd(), plugins_override={}) == 0
    finally:
        lock.close()


def test_scheduled_idle_tick_is_heartbeat_only(tmp_path, capsys):
    root = _claude_root(tmp_path)
    data_dir = _seed_state(covered_and_watermarked=True)
    _utime_all(root, time.time() - 2 * WATERMARK_SLACK_S)
    assert run_scheduled(Path.cwd(),
                         plugins_override={"claude_code": _plugin(root)}) == 0
    assert "idle" in capsys.readouterr().out
    assert not (data_dir / "manifests").exists()  # gate ran, extract didn't
    state = load_state(state_dir())
    assert state["last_heartbeat"] is not None
    # a verified-idle tick IS coverage (ADR-0011)
    assert state["last_covered"]["claude_code"] is not None


def test_scheduled_extracts_on_activity_and_respects_content_optin(tmp_path):
    root = _claude_root(tmp_path)
    data_dir = _seed_state(covered_and_watermarked=False,
                           include_content=True)  # no full pass yet -> full
    assert run_scheduled(Path.cwd(),
                         plugins_override={"claude_code": _plugin(root)}) == 0
    assert (data_dir / "claude_code" / "sessions.jsonl").exists()
    assert (data_dir / "claude_code" / "content.jsonl").exists()  # opt-in honored
    state = load_state(state_dir())
    assert state["last_full_pass"] is not None
    assert state["watermark"]["claude_code"] > 0
    [manifest] = list((data_dir / "manifests").glob("*.json"))
    assert json.loads(manifest.read_text())["trigger"] == "scheduled"


def test_scheduled_discover_failure_raises_pending_alarm(tmp_path):
    class Exploding(ClaudeCodePlugin):
        def discover(self):
            raise RuntimeError("boom")

    data_dir = _seed_state(covered_and_watermarked=False)
    assert run_scheduled(Path.cwd(), plugins_override={
        "claude_code": Exploding(root=tmp_path, salt="test-salt")}) == 0
    state = load_state(state_dir())
    kinds = {(a["kind"], a["source"]) for a in state["pending_alarms"]}
    assert ("self_check", "claude_code") in kinds
    # a failed source is NOT marked covered — the gap warning stays armed
    assert "claude_code" not in state["last_covered"]
