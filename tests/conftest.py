"""Shared fixtures: fixture source roots, a synthetic Cursor DB pair, and a
ready-to-call extract() runner wired to them."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "data" / "fixtures" / "source_logs"
SCHEMA = REPO / "schemas" / "session.schema.json"

# Fixed salt: refs must be deterministic across test runs.
pytest_plugins: list[str] = []


@pytest.fixture(autouse=True)
def _fixed_salt(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("CALIPER_HASH_SALT", "test-salt")
    # Sandbox the data home (ADR-0011): tests must never read or migrate
    # into the developer's real ~/.caliper.
    monkeypatch.setenv("CALIPER_HOME",
                       str(tmp_path_factory.mktemp("caliper-home")))


@pytest.fixture()
def cursor_dbs(tmp_path: Path) -> dict[str, Path]:
    """Build the two Cursor SQLite files with the real production schemas
    (column sets copied from the live DBs, ADR-0001/0004)."""
    tracking = tmp_path / "ai-code-tracking.db"
    conn = sqlite3.connect(tracking)
    conn.execute(
        "CREATE TABLE ai_code_hashes (hash TEXT PRIMARY KEY, source TEXT NOT NULL,"
        " fileExtension TEXT, fileName TEXT, requestId TEXT, conversationId TEXT,"
        " timestamp INTEGER, model TEXT, createdAt INTEGER NOT NULL)")
    conn.execute(
        "CREATE TABLE scored_commits (commitHash TEXT NOT NULL, branchName TEXT NOT NULL,"
        " scoredAt INTEGER NOT NULL, linesAdded INTEGER, linesDeleted INTEGER,"
        " commitMessage TEXT, PRIMARY KEY (commitHash, branchName))")
    rows = [
        # conversation with a composer header
        ("h1", "composer", "py", "a.py", "r1", "cccccccc-1111", 1767600000000, "grok-4.5", 1767600000000),
        ("h2", "composer", "py", "a.py", "r1", "cccccccc-1111", 1767600001000, "grok-4.5", 1767600001000),
        ("h3", "tab", "ts", "b.ts", "r2", "cccccccc-1111", 1767600002000, "", 1767600002000),
        ("h4", "human", "py", "a.py", None, "cccccccc-1111", 1767600003000, "", 1767600003000),
        # orphan conversation: attribution rows, no composer header
        ("h5", "composer", "md", "c.md", "r3", "dddddddd-2222", 1767700000000, "default", 1767700000000),
    ]
    conn.executemany("INSERT INTO ai_code_hashes VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO scored_commits VALUES ('deadbeef','main',1767600000000,10,2,'msg')")
    conn.commit()
    conn.close()

    state = tmp_path / "state.vscdb"
    conn = sqlite3.connect(state)
    conn.execute(
        "CREATE TABLE composerHeaders (composerId TEXT PRIMARY KEY, workspaceId TEXT,"
        " createdAt INTEGER, lastUpdatedAt INTEGER, isArchived INTEGER,"
        " isSubagent INTEGER, recency INTEGER, checkpointAt INTEGER, value TEXT)")
    header_value = json.dumps({
        "type": "head", "composerId": "cccccccc-1111",
        "createdAt": 1767600000000, "lastUpdatedAt": 1767603600000,
        "unifiedMode": "agent",
        "totalLinesAdded": 120, "totalLinesRemoved": 30, "filesChangedCount": 3,
        "numSubComposers": 1,
        "name": "CURSOR_SECRET_TITLE should never be extracted",
        "trackedGitRepos": [{"repoPath": "/Users/test/projc",
                             "branches": [{"branchName": "main"}]}],
        "workspaceIdentifier": {"id": "ws1", "uri": {"fsPath": "/Users/test/projc"}},
    })
    conn.execute("INSERT INTO composerHeaders VALUES (?,?,?,?,?,?,?,?,?)",
                 ("cccccccc-1111", "ws1", 1767600000000, 1767603600000, 0, 0,
                  1767603600000, None, header_value))
    conn.commit()
    conn.close()
    return {"tracking": tracking, "state": state}


@pytest.fixture()
def run_extract(tmp_path: Path, cursor_dbs):
    """Return a callable running the real extract() pipeline over fixture
    roots into a tmp data dir."""
    from cli.main import extract
    from connectors import ClaudeCodePlugin, CodexPlugin, CursorPlugin

    data_dir = tmp_path / "extracted"

    def _run(sources=("claude_code", "cursor", "codex"), include_content=False):
        plugins = {
            "claude_code": ClaudeCodePlugin(root=FIXTURES / "claude_code", salt="test-salt"),
            "codex": CodexPlugin(root=FIXTURES / "codex", salt="test-salt"),
            "cursor": CursorPlugin(tracking_db=cursor_dbs["tracking"],
                                   state_db=cursor_dbs["state"], salt="test-salt"),
        }
        manifest = extract(list(sources), data_dir, SCHEMA,
                           include_content=include_content,
                           plugins_override=plugins)
        return manifest, data_dir

    return _run


def read_sessions(data_dir: Path, tool: str) -> list[dict]:
    path = data_dir / tool / "sessions.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
