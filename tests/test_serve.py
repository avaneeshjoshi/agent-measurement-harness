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

    def _cls(sid, task_type, status):
        return {
            "schema_version": "0.1.0", "taxonomy_version": "0.1.0",
            "classifier_version": "rules-0.1.1", "unit": "session",
            "unit_ref": {"session_id": sid},
            "status": status, "task_type": task_type,
            "other_note": None, "context_breadth": "unknown",
            "risk": {"test_coverage": "unknown", "criticality": "unknown"},
            "confidence": 0.7, "alternatives": [],
            "method": {"kind": "rule", "rule_ids": ["R06-no-activity"],
                       "model_id": None,
                       "rationale": "no tool calls and no edits"},
            "features_used": [],
        }

    other_sid = next(s["session_id"] for s in sessions
                     if s["session_id"] != s0["session_id"])
    classes_path = tmp_path / "classes.jsonl"
    classes_path.write_text(
        json.dumps(_cls(s0["session_id"], "exploratory_qa", "classified"))
        + "\n"
        + json.dumps(_cls(other_sid, None, "unclassified")) + "\n")

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


def test_serve_never_builds_the_name_map_or_salt(tmp_path, monkeypatch):
    """The first empty-HOME walkthrough caught serve WRITING: a missing
    name map made load_data build and persist it, and load_salt created
    .salt as a side effect. readonly=True forbids both — proven here on a
    home with no names.json, no salt file, and no salt env override."""
    monkeypatch.delenv("CALIPER_HASH_SALT", raising=False)
    home = tmp_path / "bare"
    home.mkdir()
    loc = Locations(data_dir=home, classes_path=home / "c.jsonl",
                    names_path=home / "names.json",
                    salt_file=home / ".salt")
    ServeHandler.cache = BundleCache(loc)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ServeHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        for path in ("/", "/coverage", "/repo/r_x", "/session/x"):
            _get(base + path)
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert _tree(home) == {}  # not one file appeared — not even the salt


def test_cli_dispatch_reaches_serve(monkeypatch):
    """main() has a command whitelist that predates serve; the first live
    run fell through it to print_help. This pins the dispatch path."""
    import caliper.cli.main as main_mod

    called = {}
    monkeypatch.setattr("caliper.cli.serve.serve",
                        lambda port=None, open_browser=True, loc=None:
                        called.update(port=port, browser=open_browser) or 0)
    rc = main_mod.main(["serve", "--no-browser", "--port", "1234"])
    assert rc == 0
    assert called == {"port": 1234, "browser": False}


def test_range_selector_is_url_state(serve_url):
    """?range=7d resolves to a from-date server-side (fixture sessions are
    months old, so nothing survives it); range links preserve the other
    filters; the active state is stated in words."""
    base, loc, s0 = serve_url
    _, body = _get(base + "/?range=7d")
    assert "No sessions match this filter." in body
    assert "Filtered: last 7d (since " in body
    _, all_body = _get(base + "/?range=all")
    assert "No sessions match this filter." not in all_body
    _, tooled = _get(base + "/?tool=codex")
    assert 'href="?tool=codex&amp;range=7d"' in tooled
    # an explicit date wins over a range (the range is ignored, said so
    # by the state line naming only the dates)
    _, both = _get(base + f"/?range=7d&from=2020-01-01")
    assert "from 2020-01-01" in both


def test_headline_framing_sentence(serve_home):
    from caliper.harness.report import views

    loc, s0 = serve_home
    raw = load_data(loc.data_dir, loc.classes_path, loc.names_path,
                    loc.salt_file)
    s = summarize(raw)
    html = views.overview(raw, s, {}, "t")
    assert ("The total price of everything you ran, at pay-as-you-go API "
            "rates — if a subscription covered it, that is what you saved."
            in html)


def test_spend_chart_quiet_days_are_gaps_not_zero_bars():
    """Two sessions three days apart: the axis spans four days, exactly two
    columns render. A quiet day is ground, never a zero-height bar."""
    from caliper.harness.replay.runner import load_pricing
    from caliper.harness.report import views

    def mk(sid, day):
        return {"session_id": sid, "source_tool": "claude_code",
                "started_at": f"{day}T10:00:00.000Z", "fork_of": None,
                "tokens": {"input": 1_000_000, "output": 0,
                           "cache_read": 0, "cache_creation": 0},
                "models": [{"model_id": "claude-haiku-4-5",
                            "assistant_messages": 1}]}

    raw = {"pricing": load_pricing(),
           "sessions": {"a": mk("a", "2026-08-01"),
                        "b": mk("b", "2026-08-04")}}
    html = views._spend_chart(raw, {})
    assert html.count("<g data-tip=") == 2  # two hoverable columns only
    assert html.count('class="hit"') == 2   # each with a full-height target
    assert "n = 2 active days · 2 priced sessions" in html
    assert "quiet days are gaps, not zeros" in html
    # day columns no longer navigate — a single-day filter re-rendering
    # one stretched bar is not a destination (ADR-0017 postscript 2)
    assert '<a href="/?from=' not in html


def test_every_chart_carries_its_n_and_hover_payloads(serve_url):
    """Charts without their sample size do not render; hover payloads carry
    the underlying dollars; scatter points still click through to their
    repo (the one genuinely different destination)."""
    import re

    base, loc, s0 = serve_url
    _, body = _get(base + "/")
    assert " active days" in body                       # spend chart n
    assert " repos · survival = per-commit median" in body  # outcomes n
    assert "<g data-tip=" in body                       # hoverable columns
    assert '<a href="/repo/r_test1' in body             # outcome row link
    # a day tooltip payload carries per-group dollars and the ruled total
    m = re.search(r'<g data-tip="([^"]+)"', body)
    assert m and "$" in m.group(1) and "Total" in m.group(1)
    # every panel opens with its header: title + meta with an n
    figs = re.findall(r'<figcaption><span class="ct">(.*?)</span>'
                      r'<span class="cm">(.*?)</span>', body)
    assert figs and all("n" in meta or "n=" in meta or "share" in meta
                        for _t, meta in figs)


def test_tooltip_engine_ships_with_the_page(serve_url):
    base, loc, s0 = serve_url
    _, body = _get(base + "/")
    assert "tip.className = 'tip'" in body   # the instant-tooltip JS
    assert "data-tip" in body


def test_cat_tokens_match_design_md():
    """The chart-category token values in serve's CSS are DESIGN.md's,
    byte-equal — a palette change that skips the design authority (and its
    ADR) fails here."""
    import re

    from caliper.harness.report import views
    from tests.conftest import REPO

    design = (REPO / "DESIGN.md").read_text()
    css_light = dict(re.findall(r"--cat-(\d+):(#[0-9A-Fa-f]{6})",
                                views.CSS.split("prefers-color-scheme")[0]))
    row = re.search(r"`--cat-1` … `--cat-10` \| ([^|]+) \|", design)
    design_vals = re.findall(r"#[0-9A-Fa-f]{6}", row.group(1))
    assert [css_light[str(i)] for i in range(1, 11)] == design_vals


def test_chrono_table_truncates_with_stated_count():
    from caliper.harness.report.views import _spend_section

    data = {f"2026-07-{d:02d}": {"sessions": 1, "input": 10, "output": 1,
                                 "cache_read": 0, "cache_creation": 0,
                                 "cost_x1000": 1000}
            for d in range(1, 27)}  # 26 days -> 5 truncated
    html = _spend_section("day", data, "src", chrono=True)
    assert "+ 5 earlier days · 5 sessions · $5.00" in html
    assert "narrow the range to see them" in html
    assert "2026-07-01" not in html and "2026-07-26" in html


def test_outcome_rows_absences_are_words_never_tracks(serve_url):
    """Every repo gets a row in the outcomes panel. A dimension the
    instrument does not have renders its absence words in place with NO
    track — an absence never becomes a bar of any length."""
    import re

    base, loc, s0 = serve_url
    extra = _signal("dddd000011112222dddd000011112222dddd0000",
                    "2026-08-20T00:00:00+00:00", status="not_yet_measurable")
    extra["change_ref"]["repo_ref"] = "r_young"
    extra["provenance"]["repo_path"] = "/Users/test/youngrepo"
    p = loc.data_dir / "git_history" / "production_signals.jsonl"
    p.write_text(p.read_text() + json.dumps(extra) + "\n")

    _, body = _get(base + "/")
    sec = body.split("Cost × 30d survival per repo", 1)[1] \
              .split("</figure>", 1)[0]
    per_row = sec.split('<div class="row2">')
    young = next((r for r in per_row if "r_young" in r), None)
    assert young, "young repo missing from outcome rows"
    assert "not yet measurable" in young
    assert "no commit has cleared the 30d horizon" in young
    assert '"track"' not in young
    # projA: measured survival -> a --measured track with its n beside it
    proj = next((r for r in per_row if "projA" in r), None)
    assert proj and "survival" in proj
    assert "var(--measured)" in proj
    assert " repos · survival = per-commit median" in body  # the panel's n


def test_mix_bars_unclassified_is_absent_gray_and_present(serve_url):
    base, loc, s0 = serve_url
    _, body = _get(base + "/")
    # the legend names unclassified in the absent color, always
    assert 'background:var(--absent)"></i>unclassified' in body
    # and the fixture's one unclassified session renders a real segment
    assert "unclassified · 1 · " in body


def test_empty_home_renders_no_chart_frame(tmp_path):
    from caliper.harness.report import views

    empty = tmp_path / "nothing"
    empty.mkdir()
    (empty / ".salt").write_text("s")
    raw = load_data(empty, empty / "c.jsonl", empty / "n.json",
                    empty / ".salt")
    html = views.overview(raw, summarize(raw), {}, "t")
    assert '<figure class="chart"' not in html


def test_stats_strip_every_tile_carries_its_basis(serve_url):
    """ADR-0018's amendment condition: a stats strip is legal only when
    every tile states its basis; the builder refuses a naked number."""
    import pytest as _pytest

    from caliper.harness.report.views import tiles

    base, loc, s0 = serve_url
    _, body = _get(base + "/")
    assert body.count('<div class="stats">') == 1  # one strip, max
    assert body.count('class="stat lead"') == 1    # one lead tile, max
    assert "at API list rates" in body             # the lead's basis
    assert "days with priced usage" in body        # per-active-day basis
    assert "total, all four buckets" in body       # tokens basis
    with _pytest.raises(ValueError):
        tiles([("Naked", "$1", "", False)])


def test_empty_home_has_no_stats_strip(tmp_path):
    from caliper.harness.report import views

    empty = tmp_path / "nothing"
    empty.mkdir()
    (empty / ".salt").write_text("s")
    raw = load_data(empty, empty / "c.jsonl", empty / "n.json",
                    empty / ".salt")
    html = views.overview(raw, summarize(raw), {}, "t")
    assert '<div class="stats">' not in html
    assert "No sessions extracted yet. Run" in html


def test_controls_are_pressed_buttons(serve_url):
    base, loc, s0 = serve_url
    _, body = _get(base + "/?range=7d")
    assert 'class="btn" aria-pressed="true"' in body   # active range
    assert body.count('aria-pressed="true"') >= 2      # + active nav view


def test_tool_rank_rows_keep_absence_words_without_a_bar(serve_url):
    """Cursor's spend row: absence words, session count in the sub-line,
    and NO track — an absence never becomes a bar of any length."""
    import re

    base, loc, s0 = serve_url
    _, body = _get(base + "/")
    m = re.search(r'<div class="row2"><div class="nm"><b>cursor</b>'
                  r"</div>(.*?)</div></div>", body)
    assert m, "cursor rank row missing"
    row = m.group(1)
    assert "not recorded" in row
    assert "none with tokens (ADR-0004)" in row
    assert '"track"' not in row


def test_daily_table_is_newest_first(serve_url):
    base, loc, s0 = serve_url
    _, body = _get(base + "/")
    assert "newest first" in body
    idx = body.rindex("sessions.jsonl → started_at date")
    seg = body[:idx]
    days = __import__("re").findall(r'<td data-s="(\d{4}-\d{2}-\d{2})"', seg)
    assert days == sorted(days, reverse=True) and days


def test_cumulative_runs_to_the_headline_total_with_flat_gaps():
    """The running total ends at the headline figure; quiet days are flat
    segments (a true zero), and hover carries running total + that day."""
    from caliper.harness.report import charts

    svg = charts.cumulative({"2026-08-01": 10.0, "2026-08-04": 5.0},
                            "Cumulative spend", "n = 2 active days")
    assert "$15" in svg                       # end label = the total
    assert svg.count('class="hit"') == 4      # every day in the span hoverable
    assert "running total" in svg
    assert "that day" in svg
    # a single day cannot curve — the builder refuses, caller says why
    assert charts.cumulative({"2026-08-01": 10.0}, "t", "m") == ""


def test_cumulative_panel_on_overview_matches_headline(serve_home):
    from caliper.harness.report import views

    loc, s0 = serve_home
    raw = load_data(loc.data_dir, loc.classes_path, loc.names_path,
                    loc.salt_file)
    s = summarize(raw)
    html = views.overview(raw, s, {}, "t")
    assert "Cumulative spend" in html
    if "Pick a wider range" not in html:
        assert f"runs to ${s['headline']['total_cost']:,.2f}" in html


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
