"""Assemble the first-look summary from records on disk, then render HTML.

Every figure carries provenance (source file + n). Absent data renders as
'not recorded', never zero. Costs are LIST-PRICE EQUIVALENTS from the
versioned sheet — on a subscription this is what you'd have paid at API
rates, not what you were billed; the page says so."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from caliper.harness.replay.runner import load_pricing
from .names import load_name_map

TOOLS = ("claude_code", "cursor", "codex")


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _price(tokens: dict | None, model_ids: list[str], pricing: dict) -> float | None:
    """List-price a session's token buckets using its dominant model.
    Sessions mix models; dominant-model pricing is an approximation and is
    labeled as such on the page."""
    if not tokens:
        return None
    def sheet_key(mid):
        if mid in pricing["models"]:
            return mid
        # dated ids (claude-haiku-4-5-20251001) match their undated sheet key
        for k in pricing["models"]:
            if mid.startswith(k + "-") or mid.startswith(k):
                return k
        return None
    key = None
    for m in model_ids:
        key = sheet_key(m)
        if key:
            break
    if key is None:
        return None
    p = pricing["models"][key]
    M = 1_000_000
    total = 0.0
    for bucket, rate_key in (("input", "input"), ("output", "output"),
                             ("cache_read", "cache_read"),
                             ("cache_creation", "cache_write_1h")):
        t = tokens.get(bucket, 0)
        if not t:
            continue
        rate = p.get(rate_key)
        if rate is None:
            return None  # traffic in a bucket with no rate: unpriced, not partial
        total += t / M * rate
    return total


def _dominant_models(rec: dict) -> list[str]:
    ms = sorted(rec.get("models") or [],
                key=lambda m: -(m.get("assistant_messages") or 0))
    return [m["model_id"] for m in ms]


def _cohort(rec: dict) -> str:
    paths = " ".join(a["path"] for a in rec["provenance"]["source_artifacts"])
    return "eval_harness" if "caliper-eval" in paths else "organic"


def collect(repo_root: Path, data_dir: Path, classes_path: Path,
            names_path: Path, salt_file: Path) -> dict:
    """All locations are resolved by the caller through cli.paths (ADR-0012)
    — this layer stays path-agnostic. data_dir is the extracted tree;
    classes_path the task_class records; names_path the local display-name
    map; salt_file the ref salt."""
    pricing = load_pricing()
    names = load_name_map(names_path, salt_file)

    sessions = {}
    for tool in TOOLS:
        for r in _jsonl(data_dir / tool / "sessions.jsonl"):
            sessions[r["session_id"]] = r

    # ---- spend ----------------------------------------------------------
    spend_by_model: dict[str, dict] = defaultdict(lambda: Counter())
    spend_by_tool: dict[str, dict] = defaultdict(lambda: Counter())
    spend_by_project: dict[str, dict] = defaultdict(lambda: Counter())
    spend_by_day: dict[str, dict] = defaultdict(lambda: Counter())
    unpriced_sessions = no_token_sessions = fork_children_netted = 0
    for r in sessions.values():
        if r.get("fork_of"):
            # fork/resume duplicates the original's transcript (ADR-0002
            # finding 4): netted from spend, counted and disclosed — never
            # silently dropped
            fork_children_netted += 1
            continue
        tok = r.get("tokens")
        tool = r["source_tool"]
        day = r["started_at"][:10]
        if _cohort(r) == "eval_harness":
            spend_by_day[day]["eval_sessions"] += 1
        if not tok:
            no_token_sessions += 1
            spend_by_tool[tool]["sessions_no_tokens"] += 1
            continue
        cost = _price(tok, _dominant_models(r), pricing)
        buckets = {k: tok.get(k, 0) for k in ("input", "output", "cache_read", "cache_creation")}
        model = next(iter(_dominant_models(r)), "unknown")
        proj = names.get(r.get("project_ref"), None) or "(unmapped)"
        for target, key in ((spend_by_model, model), (spend_by_tool, tool),
                           (spend_by_project, proj), (spend_by_day, day)):
            c = target[key]
            for b, v in buckets.items():
                c[b] += v
            c["sessions"] += 1
            if cost is not None:
                c["cost_x1000"] += int(cost * 1000)
        if cost is None:
            unpriced_sessions += 1

    # ---- task mix -------------------------------------------------------
    classes = _jsonl(classes_path)
    mix = defaultdict(lambda: defaultdict(Counter))
    auto_mix = defaultdict(Counter)
    for r in classes:
        sid = r["unit_ref"]["session_id"]
        s = sessions.get(sid)
        if not s:
            continue
        cohort = _cohort(s)
        label = r["task_type"] or "unclassified"
        mix[r["unit"]][(s["source_tool"], cohort)][label] += 1
        if r["unit"] == "session" and cohort == "organic":
            a = s.get("automated")
            akey = "automated" if a is True else ("human" if a is False else "unmarked")
            auto_mix[akey][label] += 1

    # ---- outcomes (git signals) ----------------------------------------
    signals = _jsonl(data_dir / "git_history" / "production_signals.jsonl")
    repos = defaultdict(lambda: {"commits": 0, "surv": [], "rework_m": 0,
                                 "rework_y": 0, "attr": Counter(), "path": None})
    for r in signals:
        ref = r["change_ref"]["repo_ref"]
        rp = repos[ref]
        rp["commits"] += 1
        rp["path"] = r["provenance"]["repo_path"].rsplit("/", 1)[-1]
        for s in r["survival"]:
            if s["horizon_days"] == 30 and s["status"] == "measured":
                rp["surv"].append(s["surviving_fraction"])
        rw = r.get("rework")
        if rw and rw["status"] == "measured":
            rp["rework_m"] += 1
            if rw["occurred"]:
                rp["rework_y"] += 1
        rp["attr"][r["ai_attribution"]["status"]] += 1

    # spend beside outcomes: project display name -> repo name is the join
    # "never priced" must stay None — 0.0 would violate the absent!=zero rule
    proj_cost = {}
    for proj, c in spend_by_project.items():
        x = c.get("cost_x1000")
        proj_cost[proj] = (x / 1000) if x is not None else None

    # ---- headline -------------------------------------------------------
    total_cost = sum(c.get("cost_x1000", 0) for c in spend_by_tool.values()) / 1000
    autoreview = {"sessions": 0, "tokens": 0}
    unpriced_tokens = 0
    for r in sessions.values():
        tok = r.get("tokens")
        if not tok:
            continue
        if _price(tok, _dominant_models(r), pricing) is None:
            unpriced_tokens += sum(tok.values())
            if any(m.startswith("codex-auto-review") for m in _dominant_models(r)):
                autoreview["sessions"] += 1
                autoreview["tokens"] += sum(tok.values())
    cursor_n = sum(1 for r in sessions.values() if r["source_tool"] == "cursor")
    organic_n = sum(1 for r in sessions.values() if _cohort(r) == "organic")
    headline = {
        "total_cost": total_cost,
        "fork_children_netted": fork_children_netted,
        "priced_sessions": (len(sessions) - unpriced_sessions
                            - no_token_sessions - fork_children_netted),
        "unpriced_sessions": unpriced_sessions,
        "no_token_sessions": no_token_sessions,
        "unpriced_tokens": unpriced_tokens,
        "autoreview": autoreview,
        "cursor_sessions": cursor_n,
        "cursor_share_all": cursor_n / len(sessions) if sessions else 0,
        "cursor_share_organic": cursor_n / organic_n if organic_n else 0,
    }

    # ---- coverage -------------------------------------------------------
    coverage = {}
    for tool in TOOLS:
        recs = [r for r in sessions.values() if r["source_tool"] == tool]
        if not recs:
            continue
        joined = sum(1 for r in recs if names.get(r.get("project_ref")))
        starts = sorted(r["started_at"] for r in recs)
        coverage[tool] = {
            "sessions": len(recs),
            "repo_join": joined,
            "with_tokens": sum(1 for r in recs if r.get("tokens")),
            "with_units": None,  # filled below
            "range": [starts[0][:10], starts[-1][:10]],
        }
        units = _jsonl(data_dir / tool / "prompt_units.jsonl")
        with_units = len({u["session_id"] for u in units})
        coverage[tool]["with_units"] = with_units

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pricing": {"as_of": pricing["pricing_version"],
                    "source": pricing["pricing_source"]},
        "n_sessions": len(sessions),
        "headline": headline,
        "spend": {"by_model": {k: dict(v) for k, v in spend_by_model.items()},
                  "by_tool": {k: dict(v) for k, v in spend_by_tool.items()},
                  "by_project": {k: dict(v) for k, v in spend_by_project.items()},
                  "by_day": {k: dict(v) for k, v in sorted(spend_by_day.items())},
                  "unpriced_sessions": unpriced_sessions,
                  "no_token_sessions": no_token_sessions},
        "mix": {u: {f"{t}/{c}": dict(cnt) for (t, c), cnt in m.items()}
                for u, m in mix.items()},
        "auto_mix": {k: dict(v) for k, v in auto_mix.items()},
        "repos": {ref: {**{k: v for k, v in rp.items() if k not in ("surv", "attr")},
                        "surv30_median": (sorted(rp["surv"])[len(rp["surv"]) // 2]
                                          if rp["surv"] else None),
                        "surv30_n": len(rp["surv"]),
                        "attr": dict(rp["attr"])}
                  for ref, rp in repos.items()},
        "proj_cost": proj_cost,
        "coverage": coverage,
        "sources": {
            "sessions": {t: len([r for r in sessions.values() if r["source_tool"] == t]) for t in TOOLS},
            "task_classes": len(classes),
            "production_signals": len(signals),
        },
    }
