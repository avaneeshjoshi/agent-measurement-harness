"""First-look report guarantees: absent-data never renders as zero, raw
paths never enter the output, model-id matching prices dated ids."""

from __future__ import annotations

from harness.replay.runner import load_pricing
from harness.report.generate import _price
from harness.report.render import NR, _fmt, render


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
