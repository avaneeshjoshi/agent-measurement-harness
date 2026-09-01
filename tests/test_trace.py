"""Trace layer v0 tests (ADR-0019): ticket-key extraction with its
blocklist, the ref-join contract (session-side absolute-path hashes must
equal commit-side reconstructed hashes — a mismatch fails loudly),
file-overlap scoring and the time tiebreaker, the causality constraint,
idempotent re-runs, the read-only guarantee, and schema validity of every
emitted edge."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from caliper.harness.trace.tracer import (_score_overlap, run_trace,
                                          ticket_keys)
from tests.conftest import REPO

TRACE_SCHEMA = REPO / "schemas" / "trace_event.schema.json"
SALT = "test-salt"  # matches the autouse CALIPER_HASH_SALT fixture

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit(repo: Path, days_ago: float, message: str,
            files: dict[str, str]) -> str:
    when = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT12:00:00Z")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True,
                   capture_output=True, env={**env})
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                         capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path):
    """Three commits: a two-file ticket commit, a one-file chunk with no
    key, and a docs commit whose only key-shaped strings are blocklisted.
    Commit-message timestamps are backdated so causality is testable."""
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True,
                   capture_output=True)
    shas = {}
    shas["c1"] = _commit(r, 10, "PROJ-7: login form, first chunk",
                         {"src/login.py": "a\n", "src/form.py": "b\n"})
    shas["c2"] = _commit(r, 8, "polish login output",
                         {"src/login.py": "a2\n"})
    shas["c3"] = _commit(r, 5, "notes: ADR-0018, UTF-8, SHA-256, CVE-2024",
                         {"docs/notes.md": "n\n"})
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=r,
                          check=True, capture_output=True,
                          text=True).stdout.strip()
    return {"path": r, "root": root, "shas": shas}


def _file_ref(root: str, rel: str) -> str:
    norm = f"{root}/{rel}"
    return "f_" + hashlib.sha256((SALT + "|" + norm).encode()).hexdigest()[:12]


def _project_ref(root: str) -> str:
    return "p_" + hashlib.sha256((SALT + "|" + root).encode()).hexdigest()[:16]


def _write_data(data_dir: Path, root: str) -> None:
    """Session-side fixtures. s1 edited both c1 files just before c1;
    s2 edited the same files much earlier (the tiebreak loser); s3
    started after every commit (causality excludes it); s-branch carries
    a ticket key in its branch name and no prompt units."""
    d = data_dir / "claude_code"
    d.mkdir(parents=True, exist_ok=True)
    sessions = [
        {"session_id": "s1", "source_tool": "claude_code",
         "project_ref": _project_ref(root), "git_branch": "main",
         "started_at": _iso(10.2), "ended_at": _iso(10.1)},
        {"session_id": "s2", "source_tool": "claude_code",
         "project_ref": _project_ref(root), "git_branch": "main",
         "started_at": _iso(20), "ended_at": _iso(19)},
        {"session_id": "s3", "source_tool": "claude_code",
         "project_ref": _project_ref(root), "git_branch": "main",
         "started_at": _iso(2), "ended_at": _iso(1.9)},
        {"session_id": "s-branch", "source_tool": "claude_code",
         "project_ref": _project_ref(root),
         "git_branch": "feature/PROJ-9-login",
         "started_at": _iso(3), "ended_at": _iso(2.9)},
    ]
    with open(d / "sessions.jsonl", "w") as fh:
        for s in sessions:
            fh.write(json.dumps(s) + "\n")
    units = [
        {"session_id": sid, "window": {"files_edited": [
            {"file_ref": _file_ref(root, "src/login.py")},
            {"file_ref": _file_ref(root, "src/form.py")},
        ]}}
        for sid in ("s1", "s2", "s3")
    ]
    with open(d / "prompt_units.jsonl", "w") as fh:
        for u in units:
            fh.write(json.dumps(u) + "\n")


def _connector(tmp_path: Path, repo_path: Path):
    from caliper.connectors.git_history import GitHistoryConnector
    none = tmp_path / "not-there"
    return GitHistoryConnector(
        claude_root=none, codex_root=none,
        cursor_tracking_db=none / "t.db", cursor_state_db=none / "s.db",
        extra_repos=[repo_path], salt=SALT, now=NOW)


def _run(tmp_path: Path, repo: dict) -> tuple[dict, list[dict], Path]:
    data_dir = tmp_path / "data"
    _write_data(data_dir, repo["root"])
    validator = Draft202012Validator(json.loads(TRACE_SCHEMA.read_text()))
    summary = run_trace(data_dir, connector=_connector(tmp_path, repo["path"]),
                        validator=validator)
    edges = [json.loads(l) for l in
             (data_dir / "trace" / "trace_events.jsonl").read_text().splitlines()]
    return summary, edges, data_dir


# ------------------------------------------------------------- ticket keys

def test_ticket_keys_extracts_and_blocklists():
    text = "PROJ-7 fixes ISSUE-42; not UTF-8, SHA-256, ADR-0018, CVE-2024"
    assert ticket_keys(text) == ["PROJ-7", "ISSUE-42"]


def test_ticket_keys_dedupes_preserving_order():
    assert ticket_keys("AB-1 then CD-2 then AB-1 again") == ["AB-1", "CD-2"]


def test_ticket_keys_empty_and_none():
    assert ticket_keys("") == []
    assert ticket_keys("no keys here, just prose") == []


# ---------------------------------------------------------- ref-join contract

def test_ref_join_session_and_commit_sides_agree(repo):
    """The tracer reconstructs root/rel before hashing; the session side
    hashed the absolute path. Both must yield the same ref — and hashing
    the repo-relative path must NOT (the mismatch this test keeps loud)."""
    from caliper.connectors.util import file_refs
    session_side = file_refs(SALT, f"{repo['root']}/src/login.py")["file_ref"]
    assert session_side == _file_ref(repo["root"], "src/login.py")
    relative_hash = file_refs(SALT, "src/login.py")["file_ref"]
    assert relative_hash != session_side


# ------------------------------------------------------------ overlap scoring

def test_score_full_containment_multifile():
    assert _score_overlap({"a", "b", "c"}, {"a", "b"}, {"a": 1, "b": 1}) \
        == ("inferred", 0.85)


def test_score_single_rare_file():
    assert _score_overlap({"a"}, {"a"}, {"a": 1}) == ("inferred", 0.6)


def test_score_single_common_file():
    assert _score_overlap({"a"}, {"a"}, {"a": 5}) == ("speculative", 0.25)


def test_score_partial_containment():
    cls, conf = _score_overlap({"a"}, {"a", "b"}, {})
    assert cls == "speculative" and conf == 0.2


def test_score_below_floor_is_absence():
    assert _score_overlap({"a"}, {"a", "b", "c"}, {}) is None
    assert _score_overlap({"x"}, {"a"}, {}) is None


# ------------------------------------------------------------------ end to end

def test_commit_ticket_edges(tmp_path, repo):
    summary, edges, _ = _run(tmp_path, repo)
    ticket = [e for e in edges if e["from_node"]["kind"] == "commit"
              and e["to_node"]["kind"] == "ticket"]
    assert len(ticket) == 1
    e = ticket[0]
    assert e["from_node"]["id"] == repo["shas"]["c1"]
    assert e["to_node"]["id"] == "PROJ-7"
    assert e["link"]["method"] == "explicit_id_reference"
    assert e["link"]["confidence_class"] == "known"
    assert summary["commits_with_ticket_edge"] == 1
    assert summary["commits_analyzed"] == 3


def test_session_commit_edge_full_containment_and_tiebreak(tmp_path, repo):
    _, edges, _ = _run(tmp_path, repo)
    sc = {e["to_node"]["id"]: e for e in edges
          if e["from_node"]["kind"] == "session"
          and e["to_node"]["kind"] == "commit"}
    e1 = sc[repo["shas"]["c1"]]
    assert e1["from_node"]["id"] == "s1"  # closer-preceding beats s2
    assert e1["link"]["method"] == "file_overlap"
    assert e1["link"]["confidence_class"] == "inferred"
    assert e1["link"]["confidence"] == 0.85
    assert "2/2 changed files" in e1["link"]["evidence"]
    assert "2 candidate" in e1["link"]["evidence"]


def test_session_commit_edge_single_common_file(tmp_path, repo):
    _, edges, _ = _run(tmp_path, repo)
    sc = {e["to_node"]["id"]: e for e in edges
          if e["from_node"]["kind"] == "session"
          and e["to_node"]["kind"] == "commit"}
    e2 = sc[repo["shas"]["c2"]]  # login.py appears in two commits: common
    assert e2["from_node"]["id"] == "s1"
    assert e2["link"]["confidence_class"] == "speculative"
    assert e2["link"]["confidence"] == 0.25


def test_causality_excludes_later_sessions(tmp_path, repo):
    """s3 edited the same files but started after every commit — it can
    not have produced them, so it gets no edge (and no clock window is
    involved in saying so)."""
    summary, edges, _ = _run(tmp_path, repo)
    assert not [e for e in edges if e["from_node"]["id"] == "s3"]
    assert summary["sessions_with_commit_edge"] == 1  # s1 only


def test_branch_ticket_edge(tmp_path, repo):
    summary, edges, _ = _run(tmp_path, repo)
    br = [e for e in edges if e["from_node"]["id"] == "s-branch"]
    assert len(br) == 1
    assert br[0]["to_node"] == {"kind": "ticket", "id": "PROJ-9",
                                "source_system": None}
    assert br[0]["link"]["method"] == "branch_name_match"
    assert br[0]["link"]["confidence_class"] == "inferred"
    assert summary["sessions_with_branch_ticket_edge"] == 1


def test_no_ticket_edge_for_blocklisted_keys(tmp_path, repo):
    _, edges, _ = _run(tmp_path, repo)
    c3 = [e for e in edges if e["from_node"].get("id") == repo["shas"]["c3"]]
    assert c3 == []  # ADR/UTF/SHA/CVE are not tickets; absence, no record


def test_every_edge_validates(tmp_path, repo):
    summary, edges, _ = _run(tmp_path, repo)
    validator = Draft202012Validator(json.loads(TRACE_SCHEMA.read_text()))
    for e in edges:
        validator.validate(e)
    assert summary["invalid"] == 0
    assert summary["edges"] == len(edges) == 4


def test_rerun_is_idempotent(tmp_path, repo):
    _, _, data_dir = _run(tmp_path, repo)
    path = data_dir / "trace" / "trace_events.jsonl"
    before = path.read_bytes()
    summary2 = run_trace(data_dir,
                         connector=_connector(tmp_path, repo["path"]))
    assert summary2["store_counts"] == {"new": 0, "unchanged": 4,
                                        "updated": 0}
    assert path.read_bytes() == before


def test_sources_untouched(tmp_path, repo):
    """Read-only guarantee: the repo (working tree and .git) and the
    extracted session files are byte-identical after a trace run."""
    data_dir = tmp_path / "data"
    _write_data(data_dir, repo["root"])

    def tree_hash(base: Path) -> dict[str, str]:
        out = {}
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(base))] = hashlib.sha256(
                    p.read_bytes()).hexdigest()
        return out

    repo_before = tree_hash(repo["path"])
    sessions_before = tree_hash(data_dir / "claude_code")
    run_trace(data_dir, connector=_connector(tmp_path, repo["path"]))
    assert tree_hash(repo["path"]) == repo_before
    assert tree_hash(data_dir / "claude_code") == sessions_before
