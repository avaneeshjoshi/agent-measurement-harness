"""First-look report guarantees: absent-data never renders as zero, raw
paths never enter the output, model-id matching prices dated ids."""

from __future__ import annotations

from caliper.harness.replay.runner import load_pricing
from caliper.harness.report.generate import _price
from caliper.harness.report.render import NR, _fmt, render


def test_dated_model_ids_price_against_undated_sheet_keys():
    pricing = load_pricing()
    tok = {"input": 1_000_000, "output": 0, "cache_read": 0, "cache_creation": 0}
    assert _price(tok, ["claude-haiku-4-5-20251001"], pricing) == 1.0
    assert _price(tok, ["claude-sonnet-4-5-20250929"], pricing) == 3.0
    # OpenAI models price from the LiteLLM snapshot
    assert _price(tok, ["gpt-5.6-sol"], pricing) == 5.0
    # models absent from every sheet stay unpriced — never guessed
    assert _price(tok, ["codex-auto-review"], pricing) is None
    # traffic in a bucket with no published rate -> whole session unpriced
    cw = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 1_000_000}
    assert _price(cw, ["gpt-5.5"], pricing) is None
    assert _price(tok, ["<synthetic>", "claude-fable-5"], pricing) == 10.0


def test_absent_renders_not_recorded_never_zero():
    assert _fmt(None) == NR
    assert _fmt(None, money=True) == NR
    assert "$0.00" not in _fmt(None, money=True)


def test_render_smoke_no_raw_paths():
    summary = {
        "generated_at": "2026-08-10T00:00:00+00:00",
        "pricing": {"as_of": "2026-08-10", "source": "sheet"},
        "n_sessions": 1,
        "headline": {"total_cost": 1.0, "priced_sessions": 1,
                     "unpriced_sessions": 0, "no_token_sessions": 0,
                     "unpriced_tokens": 0,
                     "autoreview": {"sessions": 0, "tokens": 0},
                     "cursor_sessions": 0, "cursor_share_all": 0.0,
                     "cursor_share_organic": 0.0},
        "spend": {"by_model": {}, "by_tool": {}, "by_project": {},
                  "by_day": {}, "unpriced_sessions": 0, "no_token_sessions": 0},
        "mix": {}, "auto_mix": {},
        "repos": {"r_x": {"commits": 1, "path": "demo", "rework_m": 0,
                          "rework_y": 0, "surv30_median": None, "surv30_n": 0,
                          "attr": {}}},
        "proj_cost": {"demo": None},
        "coverage": {}, "sources": {},
    }
    html = render(summary)
    assert "not recorded" in html          # unpriced repo cost + missing survival
    assert "$0.00" not in html
    assert "/Users/" not in html


def test_fork_children_netted_from_spend_and_disclosed(run_extract):
    """Fork/resume children duplicate the original's transcript (ADR-0002
    finding 4): their tokens are netted from spend, and the netting is said
    on the page — '(1 fork child netted)' — never a silently smaller count."""
    import json

    from caliper.harness.report.generate import _dominant_models, collect
    from tests.conftest import REPO

    _, data_dir = run_extract()
    names_path = data_dir / "names.json"
    names_path.write_text("{}")
    s = collect(data_dir,
                classes_path=data_dir / "no-classes.jsonl",
                names_path=names_path, salt_file=data_dir / ".salt")
    assert s["headline"]["fork_children_netted"] == 1

    # session counts stay full — the netting is disclosed, not hidden
    n_claude = len((data_dir / "claude_code" / "sessions.jsonl")
                   .read_text().splitlines())
    assert s["sources"]["sessions"]["claude_code"] == n_claude

    # the fork child's tokens are absent from the total
    pricing = load_pricing()
    expected = 0.0
    for tool in ("claude_code", "cursor", "codex"):
        p = data_dir / tool / "sessions.jsonl"
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            r = json.loads(line)
            if r.get("fork_of") or not r.get("tokens"):
                continue
            c = _price(r["tokens"], _dominant_models(r), pricing)
            if c:
                expected += c
    assert abs(s["headline"]["total_cost"] - expected) < 0.05

    assert "1 fork child netted from spend" in render(s)


def test_chart_renders_nothing_for_empty_rows():
    """C1: the empty-machine crash — _chart over no rows returns empty,
    never ValueError."""
    from caliper.cli.policy_flow import _chart
    assert _chart([]) == ""


def test_policy_surfaces_gate_on_own_evidence(monkeypatch, capsys):
    """ADR-0014: a fresh install (no checkout, no own eval evidence) gets one
    sentence, never a recommendation from the author's shipped evidence."""
    import caliper.cli.paths as paths
    from caliper.cli.policy_flow import run_policy_flow
    from caliper.cli.policy_nudge import policy_nudge
    from caliper.cli.setup_flow import _policy_step
    from tests.conftest import REPO

    monkeypatch.setattr(paths, "checkout_root", lambda: None)
    import caliper.cli.policy_flow as pf
    monkeypatch.setattr(pf, "run_policy_flow", run_policy_flow)

    assert run_policy_flow(REPO) == 0
    out = capsys.readouterr().out
    assert "No routing policy yet" in out
    assert "rp-0001" not in out

    policy_nudge(REPO)  # silent: no own evidence
    assert capsys.readouterr().out == ""

    assert _policy_step(REPO) == 0
    assert "Policy step skipped" in capsys.readouterr().out


def test_policy_runs_for_dev_checkout(capsys):
    """The dev path (source checkout, shipped evidence fallback) still works
    non-interactively — declining by default and recording nothing scary."""
    from caliper.cli.policy_flow import run_policy_flow
    from tests.conftest import REPO

    assert run_policy_flow(REPO, no=True) == 0
    out = capsys.readouterr().out
    assert "rp-0001" in out  # dev sees the draft against shipped evidence
