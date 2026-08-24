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


def test_blame_failure_is_unmeasurable_never_zero(signals_run, monkeypatch):
    """C3 (ADR-0006 postscript): a blame that FAILS on an existing path must
    record 'unmeasurable', not a fabricated 'measured 0.0'."""
    import caliper.connectors.git_history as gh

    manifest, recs, data_dir, s = signals_run
    conn = gh.GitHistoryConnector(
        claude_root=data_dir / "nope", codex_root=data_dir / "nope",
        cursor_tracking_db=data_dir / "no.db", cursor_state_db=data_dir / "no.db",
        extra_repos=[s["root"]], salt="test-salt", now=NOW)

    real_git = gh._git

    def failing_blame(root, *args):
        if args and args[0] == "blame":
            return None  # git failed
        if args and args[0] == "cat-file":
            return ""  # path EXISTS at the snapshot -> true failure
        return real_git(root, *args)

    monkeypatch.setattr(gh, "_git", failing_blame)
    records = conn.analyze_repo(str(s["root"]))
    measured = [e for r in records for e in r["survival"]
                if e["status"] == "measured"]
    assert measured == []  # nothing may claim a measured figure
    assert any(e["status"] == "unmeasurable"
               for r in records for e in r["survival"])
    assert all(e["surviving_fraction"] is None
               for r in records for e in r["survival"]
               if e["status"] == "unmeasurable")


# ---- known-answer verification (user-mandated ground truth) ----------------
# A purpose-built repo where every durability answer is KNOWN in advance and
# the tool must report exactly it — not a plausible-looking output. Timeline
# (days before NOW): K1@44 K2orig@43 K3orig@42 K5orig@41 K6@40, revert@35,
# K5 delete@33, K2 rewrite@32, K4@10.

@pytest.fixture()
def known_answer_repo(tmp_path):
    repo = tmp_path / "ka-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)],
                   check=True, capture_output=True)
    k = {}
    k["k1"] = _commit(repo, 44, "K1 stable module",
                      {"stable.py": "".join(f"s{i}\n" for i in range(6))})
    k["k2"] = _commit(repo, 43, "K2 hot module",
                      {"hot.py": "".join(f"h{i}\n" for i in range(10))})
    k["k3"] = _commit(repo, 42, "K3 oops",
                      {"oops.py": "o1\no2\no3\n"})
    k["k5"] = _commit(repo, 41, "K5 doomed file",
                      {"gone.py": "g1\ng2\ng3\ng4\n"})
    k["k6"] = _commit(repo, 40, "K6 generated lockfile",
                      {"package-lock.json":
                       "".join(f'"dep-{i}": "1.0.{i}"\n' for i in range(50000))})
    # real revert, marker with an ABBREVIATED sha (the untested match path)
    (repo / "oops.py").unlink()
    k["k3_reverter"] = _commit(
        repo, 35, f'Revert "K3 oops"\n\nThis reverts commit {k["k3"][:7]}.', {})
    # true deletion (cat-file-absent path — c5's truncation never reaches it)
    (repo / "gone.py").unlink()
    k["k5_deleter"] = _commit(repo, 33, "K5 remove doomed file", {})
    # rework ~8 days after K2: rewrite 4 of its 10 lines
    k["k2_rewriter"] = _commit(
        repo, 32, "K2 partial rewrite",
        {"hot.py": "".join(f"h{i}\n" for i in range(6))
         + "".join(f"H{i}\n" for i in range(6, 10))})
    k["k4"] = _commit(repo, 10, "K4 too young",
                      {"young.py": "y1\ny2\ny3\ny4\ny5\n"})
    k["root"] = repo
    return k


@pytest.fixture()
def known_answers(known_answer_repo, tmp_path):
    from caliper.connectors.git_history import GitHistoryConnector
    nope = tmp_path / "no-such"
    conn = GitHistoryConnector(
        claude_root=nope, codex_root=nope,
        cursor_tracking_db=tmp_path / "no.db", cursor_state_db=tmp_path / "no2.db",
        extra_repos=[known_answer_repo["root"]], salt="test-salt", now=NOW)
    records = conn.analyze_repo(str(known_answer_repo["root"]))
    v = Draft202012Validator(json.loads(SIGNAL_SCHEMA.read_text()))
    for r in records:
        v.validate(r)
    by = {r["change_ref"]["commit_sha"]: r for r in records}
    return by, known_answer_repo


def _s30(rec):
    return next(e for e in rec["survival"] if e["horizon_days"] == 30)


def test_k1_untouched_commit_survives_fully(known_answers):
    by, k = known_answers
    rec = by[k["k1"]]
    e = _s30(rec)
    assert (e["status"], e["lines_original"], e["lines_surviving"],
            e["surviving_fraction"]) == ("measured", 6, 6, 1.0)
    for h in (60, 90):  # NOW is only 44d after K1
        eh = next(x for x in rec["survival"] if x["horizon_days"] == h)
        assert eh["status"] == "not_yet_measurable"
    rw = rec["rework"]
    assert (rw["status"], rw["occurred"], rw["lines_reworked"]) == \
        ("measured", False, 0)


def test_k2_rework_eight_days_later(known_answers):
    by, k = known_answers
    rec = by[k["k2"]]
    rw = rec["rework"]
    assert (rw["status"], rw["occurred"], rw["lines_reworked"]) == \
        ("measured", True, 4)
    assert k["k2_rewriter"] in rw["rework_commit_shas"]
    e = _s30(rec)
    assert (e["status"], e["lines_surviving"], e["surviving_fraction"]) == \
        ("measured", 6, 0.6)


def test_k3_real_revert_with_abbreviated_marker(known_answers):
    by, k = known_answers
    assert by[k["k3"]]["revert"] == {
        "reverted": True,
        "revert_commit_sha": k["k3_reverter"],
        "revert_detection": "git_revert_marker"}
    e = _s30(by[k["k3"]])
    assert (e["status"], e["lines_surviving"], e["surviving_fraction"]) == \
        ("measured", 0, 0.0)
    # the reverting commit itself is not "reverted"
    assert by[k["k3_reverter"]]["revert"]["reverted"] is False


def test_k4_too_young_is_never_zero(known_answers):
    by, k = known_answers
    for e in by[k["k4"]]["survival"]:
        assert e["status"] == "not_yet_measurable"
        assert e["lines_surviving"] is None
        assert e["surviving_fraction"] is None  # NEVER 0%


def test_k5_deleted_file_is_a_measurement_not_a_failure(known_answers):
    by, k = known_answers
    e = _s30(by[k["k5"]])
    # post-C3: path absent at the snapshot = lines genuinely dead — measured
    # 0.0, explicitly NOT unmeasurable
    assert (e["status"], e["lines_original"], e["lines_surviving"],
            e["surviving_fraction"]) == ("measured", 4, 0, 0.0)
    rw = by[k["k5"]]["rework"]
    assert (rw["occurred"], rw["lines_reworked"]) == (True, 4)


def test_k6_generated_file_is_not_filtered_and_skews_line_weighting(known_answers):
    by, k = known_answers
    e = _s30(by[k["k6"]])
    # pins the ADR-0006 deferral: NO generated-file filter exists — the
    # lockfile measures like any code
    assert (e["status"], e["lines_original"], e["surviving_fraction"]) == \
        ("measured", 50000, 1.0)
    # and the skew is an executable fact: line-weighted survival is ~1 while
    # the per-commit distribution says something else entirely
    fracs, orig, surv = [], 0, 0
    for rec in by.values():
        s = _s30(rec)
        if s["status"] == "measured":
            fracs.append(s["surviving_fraction"])
            orig += s["lines_original"]
            surv += s["lines_surviving"]
    assert surv / orig > 0.99          # line-weighted: the lockfile's story
    assert sum(fracs) / len(fracs) == 0.6  # per-commit mean: the honest one
    assert min(fracs) == 0.0           # dead commits exist; weighting hides them


def test_existing_fixture_untested_knowns(signals_run):
    """Exact values the original fixture produced but nothing asserted."""
    _, recs, _, s = signals_run
    # c2: its own 2 lines survive everywhere measurable
    for e in recs[s["c2"]]["survival"]:
        if e["status"] == "measured":
            assert e["surviving_fraction"] == 1.0
    # c4: reverted at day-30 -> 30d snapshot sees the empty file: measured 0.0
    e = _s30(recs[s["c4"]])
    assert (e["status"], e["surviving_fraction"]) == ("measured", 0.0)
    rw = recs[s["c4"]]["rework"]
    assert (rw["occurred"], rw["lines_reworked"]) == (True, 1)
    assert s["c5"] in rw["rework_commit_shas"]
    # c5: pure deletion -> unmeasurable everywhere, rework null, not reverted
    for e in recs[s["c5"]]["survival"]:
        assert e["status"] == "unmeasurable"
    assert recs[s["c5"]]["rework"] is None
    assert recs[s["c5"]]["revert"]["reverted"] is False
    # pr_number: only c3 carries the (#7) squash marker
    assert recs[s["c1"]]["change_ref"]["pr_number"] is None
    assert recs[s["c5"]]["change_ref"]["pr_number"] is None
