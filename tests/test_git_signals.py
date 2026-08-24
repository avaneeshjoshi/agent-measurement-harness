"""Git-history connector tests: a synthetic repo with backdated commits gives
known survival/rework/revert/attribution answers; records validate against
production_signal.schema.json and re-runs are idempotent."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.conftest import REPO

SIGNAL_SCHEMA = REPO / "schemas" / "production_signal.schema.json"

NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _commit(repo: Path, days_ago: int, message: str, files: dict[str, str]) -> str:
    when = (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT12:00:00Z")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "HOME": str(repo), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env,
                   capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message,
                    "--no-gpg-sign"], check=True, env=env, capture_output=True)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture()
def synthetic_repo(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)

    # C1, 100 days old: 5 lines. Lines 4-5 get rewritten 8 days later (inside
    # the 14d rework window) -> 3/5 survive all horizons.
    c1 = _commit(repo, 100, "add module",
                 {"mod.py": "line1\nline2\nline3\nline4\nline5\n"})
    c2 = _commit(repo, 92, "rework tail of module",
                 {"mod.py": "line1\nline2\nline3\nchanged4\nchanged5\n"})
    # C3, 50 days old: separate file, untouched since -> 100% survival at 30d,
    # 60/90d not yet measurable (repo 'now' is 2026-08-01).
    c3 = _commit(repo, 50, "add helper (#7)",
                 {"helper.py": "h1\nh2\n"})
    # C4, 40 days old, with an AI co-author trailer -> self_report/partial
    c4 = _commit(repo, 40, "tweak helper\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
                 {"helper2.py": "x1\n"})
    # C5 reverts C4 (30 days ago) -> revert linkage on C4
    c5 = _commit(repo, 30, f"Revert \"tweak helper\"\n\nThis reverts commit {c4}.",
                 {"helper2.py": ""})
    return {"root": repo, "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5}


@pytest.fixture()
def signals_run(synthetic_repo, cursor_dbs, tmp_path):
    """Run the full signals pipeline over the synthetic repo. The cursor
    tracking DB gets a scored_commits row for C1 -> vendor attribution."""
    conn_db = sqlite3.connect(cursor_dbs["tracking"])
    conn_db.execute(
        "INSERT INTO scored_commits VALUES (?,?,?,?,?,?)",
        (synthetic_repo["c1"], "main", 1767600000000, 5, 0, "add module"))
    # widen table to the real column set used by the connector
    for col in ("tabLinesAdded", "composerLinesAdded", "humanLinesAdded",
                "v1AiPercentage", "v2AiPercentage"):
        try:
            conn_db.execute(f"ALTER TABLE scored_commits ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    conn_db.execute(
        "UPDATE scored_commits SET tabLinesAdded=1, composerLinesAdded=3, "
        "humanLinesAdded=1, v2AiPercentage='80.0' WHERE commitHash=?",
        (synthetic_repo["c1"],))
    conn_db.commit()
    conn_db.close()

    from caliper.cli.main import signals
    from caliper.connectors.git_history import GitHistoryConnector

    empty = tmp_path / "no-such-dir"
    conn = GitHistoryConnector(
        claude_root=empty, codex_root=empty,
        cursor_tracking_db=cursor_dbs["tracking"],
        cursor_state_db=cursor_dbs["state"],
        extra_repos=[synthetic_repo["root"]],
        salt="test-salt", now=NOW)
    data_dir = tmp_path / "extracted"
    manifest = signals(data_dir, SIGNAL_SCHEMA, connector=conn)
    recs = {}
    for line in (data_dir / "git_history" / "production_signals.jsonl").read_text().splitlines():
        r = json.loads(line)
        recs[r["change_ref"]["commit_sha"]] = r
    return manifest, recs, data_dir, synthetic_repo


def test_signal_records_validate(signals_run):
    manifest, recs, _, _ = signals_run
    assert manifest["records"]["invalid"] == 0
    assert manifest["records"]["emitted"] == 5
    validator = Draft202012Validator(json.loads(SIGNAL_SCHEMA.read_text()))
    for r in recs.values():
        validator.validate(r)


def test_survival_and_horizon_status(signals_run):
    _, recs, _, s = signals_run
    c1 = recs[s["c1"]]
    by_h = {x["horizon_days"]: x for x in c1["survival"]}
    # 3 of 5 lines survive the day-92 rewrite at every measured horizon
    for h in (30, 60, 90):
        assert by_h[h]["status"] == "measured"
        assert by_h[h]["lines_original"] == 5
        assert by_h[h]["lines_surviving"] == 3
        assert by_h[h]["surviving_fraction"] == 0.6
    # C3 is 50 days old: 30d measured at full survival, 60/90 not yet
    c3 = recs[s["c3"]]
    by_h = {x["horizon_days"]: x for x in c3["survival"]}
    assert by_h[30]["status"] == "measured"
    assert by_h[30]["surviving_fraction"] == 1.0
    assert by_h[60]["status"] == "not_yet_measurable"
    assert by_h[90]["status"] == "not_yet_measurable"
    assert by_h[60]["lines_surviving"] is None  # absence encoded, not zeroed


def test_rework_window(signals_run):
    _, recs, _, s = signals_run
    c1 = recs[s["c1"]]
    # the day-8 rewrite falls inside C1's 14-day window
    assert c1["rework"]["status"] == "measured"
    assert c1["rework"]["occurred"] is True
    assert c1["rework"]["lines_reworked"] == 2
    assert s["c2"] in c1["rework"]["rework_commit_shas"]
    # C3 untouched within its window
    c3 = recs[s["c3"]]
    assert c3["rework"]["occurred"] is False


def test_revert_and_pr_and_attribution(signals_run):
    _, recs, _, s = signals_run
    # C4 reverted by C5, detected from the explicit marker only
    c4 = recs[s["c4"]]
    assert c4["revert"] == {"reverted": True, "revert_commit_sha": s["c5"],
                            "revert_detection": "git_revert_marker"}
    assert recs[s["c1"]]["revert"]["reverted"] is False
    # squash-style PR pattern in C3's subject
    assert recs[s["c3"]]["change_ref"]["pr_number"] == 7
    # attribution: C1 via cursor scored_commits (known, line-level);
    # C4 via Co-Authored-By trailer (partial, self_report); C3 unknown
    a1 = recs[s["c1"]]["ai_attribution"]
    assert a1["status"] == "known"
    assert a1["evidence_source"] == "vendor_tracking_db"
    assert a1["ai_lines"] == 4 and a1["human_lines"] == 1
    assert a1["ai_fraction"] == 0.8
    assert a1["vendor_score_version"] == "v2"
    a4 = recs[s["c4"]]["ai_attribution"]
    assert a4 == {"status": "partial", "evidence_source": "self_report",
                  "ai_lines": None, "human_lines": None, "ai_fraction": None,
                  "vendor_score_version": None}
    a3 = recs[s["c3"]]["ai_attribution"]
    assert a3["status"] == "unknown" and a3["evidence_source"] == "none"


def test_signals_idempotent_and_provenance(signals_run):
    manifest, recs, data_dir, s = signals_run
    path = data_dir / "git_history" / "production_signals.jsonl"
    first = path.read_bytes()

    from caliper.cli.main import signals
    from caliper.connectors.git_history import GitHistoryConnector
    conn = GitHistoryConnector(
        claude_root=data_dir / "nope", codex_root=data_dir / "nope",
        cursor_tracking_db=data_dir / "nope.db",
        cursor_state_db=data_dir / "nope.db",
        extra_repos=[s["root"]], salt="test-salt", now=NOW)
    m2 = signals(data_dir, SIGNAL_SCHEMA, connector=conn)
    # attribution evidence differs without the cursor DB? C1 falls back to
    # unknown -> record changes; every other record must be unchanged.
    assert m2["records"]["unchanged"] >= 4
    for r in recs.values():
        p = r["provenance"]
        assert p["content_hash"].startswith("sha256:")
        assert p["head_sha"] == recs[s["c5"]]["provenance"]["head_sha"]
        assert Path(p["repo_path"]) == s["root"]
