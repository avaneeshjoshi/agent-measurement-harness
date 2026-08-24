"""caliper serve guarantees (ADR-0016): read-only over ~/.caliper, one data
layer with the report, proximity labeled never attribution, absence words
never zero, every view alive on every partial machine, filters as URL
state, no policy route."""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from caliper.cli.serve import BundleCache, Locations, ServeHandler
from caliper.harness.report.generate import load_data, summarize

NEAR_SHA = "aaaa111122223333aaaa111122223333aaaa1111"
FAR_SHA = "bbbb444455556666bbbb444455556666bbbb4444"
GEN_SHA = "cccc777788889999cccc777788889999cccc7777"


def _signal(sha, authored, status="measured", frac=1.0, lines=10,
            gen_added=0):
    surv = {"horizon_days": 30, "status": status,
            "lines_original": lines if status == "measured" else 0,
            "lines_surviving": int(lines * frac) if status == "measured" else 0,
            "surviving_fraction": frac if status == "measured" else None}
    return {
        "schema_version": "0.3.0", "signals_version": "0.2.0",
        "measured_at": "2026-08-24T00:00:00+00:00",
        "change_ref": {"repo_ref": "r_test1", "commit_sha": sha,
                       "authored_at": authored, "branch": None,
                       "pr_number": None,
                       "lines_added": 0 if status == "excluded_generated"
                       else lines,
                       "lines_deleted": 1},
        "survival": [surv],
        "rework": {"status": status, "occurred": False}
        if status in ("measured", "excluded_generated") else None,
        "revert": {"reverted": False},
        "review": None,
        "ai_attribution": {"status": "unknown", "ai_lines": None,
                           "human_lines": None, "ai_fraction": None,
                           "evidence_source": "none",
                           "vendor_score_version": None},
        "generated": {"patterns_version": "gen-0.1.0",
                      "files_excluded": 1 if gen_added else 0,
                      "lines_added_excluded": gen_added,
                      "lines_deleted_excluded": 0},
        "provenance": {"repo_path": "/Users/test/projA"},
    }


@pytest.fixture()
def serve_home(run_extract, tmp_path):
    """Extracted fixtures + hand-written signals/classes/names wired so one
    claude_code session joins repo projA with one commit inside the
    proximity window, one outside it, and one generated-only."""
    _, data_dir = run_extract()
    sessions = [json.loads(l) for l in
                (data_dir / "claude_code" / "sessions.jsonl")
                .read_text().splitlines()]
    s0 = next(s for s in sessions if not s.get("fork_of") and s.get("tokens"))

    names_path = tmp_path / "names.json"
    names_path.write_text(json.dumps({s0["project_ref"]: "projA"}))

    gh = data_dir / "git_history"
    gh.mkdir(exist_ok=True)
    sigs = [
        _signal(NEAR_SHA, s0["started_at"]),
        _signal(FAR_SHA, "2020-01-01T00:00:00+00:00", frac=0.5),
        _signal(GEN_SHA, "2020-01-02T00:00:00+00:00",
                status="excluded_generated", gen_added=50000),
    ]
    (gh / "production_signals.jsonl").write_text(
        "\n".join(json.dumps(x) for x in sigs) + "\n")

    classes_path = tmp_path / "classes.jsonl"
    classes_path.write_text(json.dumps({
        "schema_version": "0.1.0", "taxonomy_version": "0.1.0",
        "classifier_version": "rules-0.1.1", "unit": "session",
        "unit_ref": {"session_id": s0["session_id"]},
        "status": "classified", "task_type": "exploratory_qa",
        "other_note": None, "context_breadth": "unknown",
        "risk": {"test_coverage": "unknown", "criticality": "unknown"},
        "confidence": 0.7, "alternatives": [],
        "method": {"kind": "rule", "rule_ids": ["R06-no-activity"],
                   "model_id": None,
                   "rationale": "no tool calls and no edits"},
        "features_used": [],
    }) + "\n")

    loc = Locations(data_dir=data_dir, classes_path=classes_path,
                    names_path=names_path,
                    salt_file=data_dir / ".salt")
    return loc, s0


@pytest.fixture()
def serve_url(serve_home):
    loc, s0 = serve_home
    ServeHandler.cache = BundleCache(loc)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ServeHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", loc, s0
    httpd.shutdown()
    httpd.server_close()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def _tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)):
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_serve_is_read_only_and_every_view_answers(serve_url, tmp_path):
    """Every route renders; nothing under the data locations changes by so
    much as a byte; there is no policy route (ADR-0014's gate stands)."""
    base, loc, s0 = serve_url
    before = _tree(tmp_path), _tree(loc.data_dir)

    for path, want in [("/", 200), ("/coverage", 200),
                       ("/repo/r_test1", 200),
                       (f"/session/{s0['session_id']}", 200),
                       ("/repo/r_nope", 404), ("/session/nope", 404),
                       ("/policy", 404), ("/anything", 404)]:
        status, body = _get(base + path)
        assert status == want, (path, status)
        assert "<main>" in body  # even the 404 is a page, not a blank

    assert (_tree(tmp_path), _tree(loc.data_dir)) == before


def test_overview_renders_the_reports_figures(serve_home):
    """Serve's overview and the report's collect() carry the same headline
    numbers — the same-records-same-figures guarantee, through both paths."""
    from caliper.harness.report import views

    loc, s0 = serve_home
    raw = load_data(loc.data_dir, loc.classes_path, loc.names_path,
                    loc.salt_file)
    s = summarize(raw)
    html = views.overview(raw, s, {}, "test")
    assert f"${s['headline']['total_cost']:,.2f}" in html
    assert f"{s['headline']['priced_sessions']} priced of " \
           f"{s['n_sessions']} sessions" in html
    if s["headline"]["fork_children_netted"]:
        assert "netted from spend" in html


def test_session_detail_labels_proximity_never_attribution(serve_url):
    """Commits beside a session carry the temporal-proximity label, the
    trace-layer disclaimer, and only commits inside the window."""
    base, loc, s0 = serve_url
    _, body = _get(base + f"/session/{s0['session_id']}")
    assert "temporal proximity, not attribution" in body
    assert "trace layer" in body
    assert "unvalidated display choice" in body
    assert NEAR_SHA[:10] in body
    assert FAR_SHA[:10] not in body  # outside the window
    assert "R06-no-activity" in body  # the rule that fired
    assert "no tool calls and no edits" in body  # its rationale, verbatim


def test_absence_words_render_never_zero(serve_url):
    """A Cursor session prices as 'not recorded', never $0.00; a
    generated-only commit reads excluded_generated, never 0%."""
    base, loc, s0 = serve_url
    cur = [json.loads(l) for l in
           (loc.data_dir / "cursor" / "sessions.jsonl")
           .read_text().splitlines()]
    sid = cur[0]["session_id"]
    _, body = _get(base + f"/session/{sid}")
    assert "not recorded" in body
    assert "$0.00" not in body

    _, repo = _get(base + "/repo/r_test1")
    assert "excluded_generated" in repo
    assert GEN_SHA[:10] in repo  # the row is present, not dropped


def test_every_view_survives_an_empty_home(tmp_path):
    from caliper.harness.report import views

    empty = tmp_path / "nothing"
    empty.mkdir()
    loc = Locations(data_dir=empty, classes_path=empty / "c.jsonl",
                    names_path=empty / "n.json",
                    salt_file=empty / ".salt")
    (empty / ".salt").write_text("s")
    raw = load_data(loc.data_dir, loc.classes_path, loc.names_path,
                    loc.salt_file)
    s = summarize(raw)
    over = views.overview(raw, s, {}, "t")
    assert "No sessions extracted yet. Run" in over
    assert "caliper extract" in over
    assert views.coverage_view(raw, s, {}, "t")
    assert views.repo_detail(raw, s, "r_x", {}, "t") is None
    assert views.session_detail(raw, s, "x", {}, "t") is None


def test_partial_machine_states_are_sentences_not_zeros(run_extract):
    """Sessions but no signals and no classifications: the sections say so
    in one sentence with one action — no fabricated aggregate."""
    from caliper.harness.report import views

    _, data_dir = run_extract()
    names = data_dir / "names.json"
    names.write_text("{}")
    raw = load_data(data_dir, data_dir / "none.jsonl", names,
                    data_dir / ".salt")
    s = summarize(raw)
    html = views.overview(raw, s, {}, "t")
    assert "No signals yet. Run" in html
    assert "caliper signals" in html
    assert "No classifications yet. Run" in html
    assert "caliper classify" in html


def test_filters_are_url_state(serve_url):
    base, loc, s0 = serve_url
    _, body = _get(base + "/?tool=codex")
    assert 'href="/coverage?tool=codex"' in body  # filter travels on links
    assert "Filtered: tool codex" in body  # and is stated in words
    _, none = _get(base + "/?from=2099-01-01")
    assert "No sessions match this filter." in none
    _, cov = _get(base + "/coverage?tool=codex")
    assert "Filtered: tool codex" in cov


def test_bundle_cache_invalidates_on_mtime_change(serve_home):
    import os

    loc, s0 = serve_home
    cache = BundleCache(loc)
    a, _ = cache.get({})
    b, _ = cache.get({})
    assert a is b  # unchanged sources: no re-parse
    p = loc.data_dir / "claude_code" / "sessions.jsonl"
    os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))
    c, _ = cache.get({})
    assert c is not a  # a source changed: fresh bundle
    assert c["sessions"].keys() == a["sessions"].keys()
