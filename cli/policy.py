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
                 "claude-sonnet": "mid", "claude-haiku": "small",
                 # open-weight: weights are runnable outside the vendor; folds
                 # in strict open-source too (ADR-0010) — routing economics
                 # and quality measurement treat them identically
                 "qwen": "open_weight", "deepseek": "open_weight",
                 "llama": "open_weight", "meta-llama": "open_weight",
                 "kimi": "open_weight", "glm": "open_weight",
                 "mistral": "open_weight", "mixtral": "open_weight",
                 "gpt-oss": "open_weight", "olmo": "open_weight"}


def _tier(model_ids: list[str]) -> str | None:
    for m in model_ids:
        for prefix, tier in TIER_OF_MODEL.items():
            if m.startswith(prefix):
                return tier
    return None


def accessible_tiers(sessions: dict) -> dict[str, list[str]]:
    """Access is proven by traffic, not declared: a tier is accessible iff a
    model of that tier actually appears in extracted sessions (ADR-0010).
    `caliper connect` (future) will be the path for proving access to models
    not yet used. Returns tier -> sorted model ids that proved it."""
    from harness.report.generate import _dominant_models

    proof: dict[str, set[str]] = {}
    for s in sessions.values():
        for m in _dominant_models(s):
            t = _tier([m])
            if t:
                proof.setdefault(t, set()).add(m)
    return {t: sorted(ms) for t, ms in proof.items()}


def analyze(repo_root: Path) -> dict | None:
    """Everything the flow renders, computed from records on disk."""
    from harness.replay.runner import load_pricing
    from harness.report.generate import _cohort, _dominant_models, _price

    from .paths import routing_policies_path
    policies_path = routing_policies_path(repo_root)
    if not policies_path.exists():
        return None
    policy = [json.loads(l) for l in policies_path.read_text().splitlines()][-1]

    pricing = load_pricing()
    sessions = {}
    for tool in ("claude_code", "cursor", "codex"):
        from .paths import extracted_dir
        p = extracted_dir() / tool / "sessions.jsonl"
        if p.exists():
            for line in p.read_text().splitlines():
                r = json.loads(line)
                sessions[r["session_id"]] = r

    from .paths import task_classes_path
    classes_path = task_classes_path(repo_root)
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
    fork_netted = 0
    for sid in in_scope_ids:
        s = sessions.get(sid)
        if not s or not s.get("tokens"):
            continue
        if s.get("fork_of"):
            # duplicated transcript (ADR-0002 f4): netted from the verdict,
            # disclosed on screen
            fork_netted += 1
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
    from .paths import eval_results_path
    eval_path = eval_results_path(repo_root)
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
        "access": accessible_tiers(sessions),
        "policy": policy,
        "n_sessions": len(sessions),
        "in_scope": len(in_scope_ids),
        "fork_netted": fork_netted,
        "overspend": {**over, "delta": over["actual"] - over["at_mid"]},
        "below_floor": floor,
        "curve": curve,
        "pricing_version": pricing["pricing_version"],
    }


def record_decision(repo_root: Path, policy_id: str, applied: bool) -> Path:
    """Local-only decision log (gitignored tree) — the apply engine will
    consume this when it exists."""
    from .paths import state_dir
    out = state_dir() / ".policy_decisions.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    entry = {"policy_id": policy_id, "applied": applied,
             "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "note": "UX-prototype decision; no agent config was modified"}
    with open(out, "a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return out
