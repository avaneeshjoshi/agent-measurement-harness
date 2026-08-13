"""`caliper policy` — the policy-creation conversation, prototyped.

Scans real extracted+classified traffic against the routing_policy record,
computes the overspend/underspend verdict, shows the policy's evidence, and
asks the apply question. Two deliberate stubs, labeled as such on screen:
the web dashboard (preview link) and the apply engine (a yes records the
decision locally; no agent config is touched yet)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

TIER_OF_MODEL = {"claude-fable-5": "frontier", "claude-opus": "frontier",
                 "claude-sonnet": "mid", "claude-haiku": "small"}


def _tier(model_ids: list[str]) -> str | None:
    for m in model_ids:
        for prefix, tier in TIER_OF_MODEL.items():
            if m.startswith(prefix):
                return tier
    return None


def analyze(repo_root: Path) -> dict | None:
    """Everything the flow renders, computed from records on disk."""
    from harness.replay.runner import load_pricing
    from harness.report.generate import _cohort, _dominant_models, _price

    policies_path = repo_root / "data" / "derived" / "routing" / "routing_policies.jsonl"
    if not policies_path.exists():
        return None
    policy = [json.loads(l) for l in policies_path.read_text().splitlines()][-1]

    pricing = load_pricing()
    sessions = {}
    for tool in ("claude_code", "cursor", "codex"):
        p = repo_root / "data" / "extracted" / tool / "sessions.jsonl"
        if p.exists():
            for line in p.read_text().splitlines():
                r = json.loads(line)
                sessions[r["session_id"]] = r

    classes_path = repo_root / "data" / "derived" / "classes" / "task_classes.jsonl"
    in_scope_ids = set()
    if classes_path.exists():
        scope_type = policy["scope"]["task_type"]
        for line in classes_path.read_text().splitlines():
            r = json.loads(line)
            if r["unit"] == "session" and r["task_type"] == scope_type:
                in_scope_ids.add(r["unit_ref"]["session_id"])

    def sonnet_price(tokens):
        return _price(tokens, ["claude-sonnet-5"], pricing)

    over = {"sessions": 0, "actual": 0.0, "at_mid": 0.0, "eval_sessions": 0}
    floor = {"sessions": 0}
    for sid in in_scope_ids:
        s = sessions.get(sid)
        if not s or not s.get("tokens"):
            continue
        tier = _tier(_dominant_models(s))
        if tier == "frontier":
            actual = _price(s["tokens"], _dominant_models(s), pricing)
            counter = sonnet_price(s["tokens"])
            if actual is None or counter is None:
                continue
            over["sessions"] += 1
            over["actual"] += actual
            over["at_mid"] += counter
            if _cohort(s) == "eval_harness":
                over["eval_sessions"] += 1
        elif tier == "small":
            floor["sessions"] += 1

    curve = {p["model_tier"]: p for p in policy["evidence"]["quality_curve"]
             if p["metric"].endswith("full_run_n1")}

    # per-tier detail straight from the eval records (full 90-run grid)
    eval_path = repo_root / "data" / "derived" / "replay" / "eval_results.jsonl"
    tiers: dict[str, dict] = {}
    if eval_path.exists():
        for line in eval_path.read_text().splitlines():
            r = json.loads(line)
            t = r["cell"]["model_tier"]
            d = tiers.setdefault(t, {"model": r["cell"]["model_id"], "n": 0,
                                     "solved": 0, "cost": 0.0, "turns": [],
                                     "wall_s": 0.0})
            run = r["tracks"]["objective"]["runs"][0]
            d["n"] += 1
            d["solved"] += int(r["tracks"]["objective"]["aggregate"]["value"])
            d["cost"] += r["cost"]["cost_usd_estimate"] or 0
            if run.get("turns") is not None:
                d["turns"].append(run["turns"])
            d["wall_s"] += run.get("wall_seconds") or 0
    for t, d in tiers.items():
        d["mean_turns"] = (sum(d["turns"]) / len(d["turns"])) if d["turns"] else None
        d.pop("turns")
        # ADR-0007 postscript: sonnet-5 restated at billed intro rate (x 2/3)
        if d["model"] == "claude-sonnet-5":
            d["cost_billed"] = d["cost"] * 2 / 3
            d["restated"] = True
        else:
            d["cost_billed"] = d["cost"]
            d["restated"] = False
        d["per_solve"] = d["cost_billed"] / d["solved"] if d["solved"] else None

    return {
        "tiers": tiers,
        "policy": policy,
        "n_sessions": len(sessions),
        "in_scope": len(in_scope_ids),
        "overspend": {**over, "delta": over["actual"] - over["at_mid"]},
        "below_floor": floor,
        "curve": curve,
        "pricing_version": pricing["pricing_version"],
    }


def record_decision(repo_root: Path, policy_id: str, applied: bool) -> Path:
    """Local-only decision log (gitignored tree) — the apply engine will
    consume this when it exists."""
    out = repo_root / "data" / "extracted" / ".policy_decisions.jsonl"
    entry = {"policy_id": policy_id, "applied": applied,
             "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "note": "UX-prototype decision; no agent config was modified"}
    with open(out, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return out
