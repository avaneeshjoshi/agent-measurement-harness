"""`caliper pricing update` — build-time price-sheet generation from LiteLLM.

Fetches BerriAI/litellm's model_prices_and_context_window.json ONCE, at the
operator's command, and writes a dated snapshot into the repo. The harness
reads snapshots, never the network. Old snapshots are never rewritten —
historical sessions keep the rates that applied then.

FIELD MAPPING (LiteLLM per-token -> our $/MTok buckets), explicit:
  input_cost_per_token                        -> input
  output_cost_per_token                       -> output
  cache_read_input_token_cost                 -> cache_read
  cache_creation_input_token_cost             -> cache_write_5m
  cache_creation_input_token_cost_above_1hr   -> cache_write_1h
Tiered/priority variants (above_272k, _priority) are deliberately ignored:
we price at base rates and say so.

CACHE SEMANTICS: our token buckets are NON-OVERLAPPING by connector
normalization (ADR-0005 — codex input_tokens includes cached at the vendor,
and the connector subtracts). LiteLLM rates are per-bucket vendor rates, so
sum(bucket x rate) is correct against OUR buckets. The double-count hazard
exists only for a future connector that emits raw vendor buckets without
normalizing — noted here so the mapping's assumption is on record.

MISSING RATES stay null (e.g. OpenAI models carry no 1h cache-write rate);
price_usage() then declines to price any session with traffic in a null-rate
bucket. Models absent from LiteLLM are simply absent -> "not recorded".

LiteLLM is COMMUNITY-MAINTAINED and not authoritative; every snapshot and
the report footer say so.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .runner import load_pricing

LITELLM_URL = ("https://raw.githubusercontent.com/BerriAI/litellm/main/"
               "model_prices_and_context_window.json")

# models Caliper has actually seen in traffic or eval tiers; extend as traffic
# grows. codex-auto-review and cursor's 'default' are internal pseudo-models
# with no public price — deliberately absent.
TRAFFIC_MODELS = [
    "claude-fable-5", "claude-opus-5", "claude-opus-4-8",
    "claude-sonnet-5", "claude-sonnet-4-5", "claude-haiku-4-5",
    "gpt-5.5", "gpt-5.6-sol", "gpt-5.3-codex", "grok-4.5",
]

_FIELD_MAP = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_write_5m": "cache_creation_input_token_cost",
    "cache_write_1h": "cache_creation_input_token_cost_above_1hr",
}


def resolve_key(data: dict, model_id: str) -> str | None:
    """Canonical LiteLLM key for a model: bare key first, then provider-
    prefixed (anthropic/openai/xai) — never a reseller (azure/bedrock)."""
    if model_id in data:
        return model_id
    for k in data:
        if "/" not in k and k.startswith(model_id):
            return k
    for pref in ("anthropic/", "openai/", "xai/"):
        for k in data:
            if k.startswith(pref + model_id):
                return k
    return None


def build_snapshot(data: dict, fetched_at: str) -> dict:
    models = {}
    unresolved = []
    for mid in TRAFFIC_MODELS:
        key = resolve_key(data, mid)
        if key is None:
            unresolved.append(mid)
            continue
        e = data[key]
        rates = {}
        for ours, theirs in _FIELD_MAP.items():
            v = e.get(theirs)
            rates[ours] = round(v * 1_000_000, 6) if v is not None else None
        rates["litellm_key"] = key
        models[mid] = rates
    today = fetched_at[:10]
    return {
        "pricing_version": f"{today}-litellm",
        "effective_date": today,
        "fetched_at": fetched_at,
        "source_url": LITELLM_URL,
        "maintenance": ("generated from LiteLLM community price data — "
                        "COMMUNITY-MAINTAINED, NOT AUTHORITATIVE; base rates "
                        "only (tiered/priority variants ignored)"),
        "pricing_source": (f"LiteLLM model_prices ({today}, community-maintained, "
                           "not authoritative); base rates; buckets are Caliper-"
                           "normalized non-overlapping (ADR-0005)"),
        "currency": "USD_per_million_tokens",
        "unresolved_models": unresolved,
        "models": models,
    }


def cross_check(new: dict, old: dict) -> list[str]:
    """Rate disagreements vs the previous snapshot — findings, not silent
    overwrites."""
    findings = []
    for mid, nr in new["models"].items():
        orates = old["models"].get(mid) or old["models"].get(mid.rsplit("-2025", 1)[0])
        if not orates:
            continue
        for bucket in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"):
            ov, nv = orates.get(bucket), nr.get(bucket)
            if ov is not None and nv is not None and abs(ov - nv) > 1e-9:
                findings.append(f"{mid}.{bucket}: {old['pricing_version']}={ov} "
                                f"vs new={nv}")
            elif ov is not None and nv is None:
                findings.append(f"{mid}.{bucket}: absent in new snapshot "
                                f"(was {ov})")
    return findings


def update(snap_dir: Path | None = None, log=print) -> Path:
    snap_dir = snap_dir or Path(__file__).parent / "pricing_snapshots"
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log(f"fetching {LITELLM_URL}")
    with urllib.request.urlopen(LITELLM_URL, timeout=60) as r:
        data = json.load(r)
    snap = build_snapshot(data, fetched_at)
    try:
        prev = load_pricing()
        findings = cross_check(snap, prev)
        if findings:
            log(f"RATE DISAGREEMENTS vs {prev['pricing_version']} (findings, kept alongside — nothing overwritten):")
            for f in findings:
                log(f"  {f}")
            snap["cross_check_vs_previous"] = {"previous": prev["pricing_version"],
                                               "disagreements": findings}
        else:
            log("cross-check vs previous snapshot: all shared rates match")
    except FileNotFoundError:
        pass
    out = snap_dir / f"{snap['pricing_version']}.json"
    if out.exists():
        raise FileExistsError(f"{out} exists — snapshots are never rewritten; "
                              "delete manually only if the fetch was bad")
    out.write_text(json.dumps(snap, indent=2))
    log(f"wrote {out} ({len(snap['models'])} models; "
        f"unresolved: {snap['unresolved_models'] or 'none'})")
    return out
