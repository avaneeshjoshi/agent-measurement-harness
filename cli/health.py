"""Collection health (ADR-0011): gap detection against the observed
retention window, and drift canaries over recent runs. Pure logic plus one
nudge renderer — no scheduling code lives here.

Every threshold is a named constant with its rationale attached; retuning one
requires an ADR note (same rule as classifier thresholds, ADR-0009), never a
silent edit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ADR-0009 §infrastructure-1: a raw Claude Code log present on 2026-08-07 was
# gone by 2026-08-10 — observed vendor retention is ~3 days. Collection older
# than this may have permanently lost whatever the vendor rotated out. A
# known limitation (ADR-0011), not a bug. Never inline this as a magic number.
RETENTION_OBSERVED_DAYS = 3

STATE_FILENAME = ".collection.json"

# How many recent manifests the fallback scan reads when no state file
# exists yet (pre-state users still deserve the warning).
_FALLBACK_MANIFEST_SCAN = 50


@dataclass
class Gap:
    source: str
    last_covered: datetime
    lost_from: datetime
    lost_to: datetime


def collection_gap(last_covered: dict[str, datetime | None],
                   now: datetime) -> list[Gap]:
    """Sources whose last covered time predates the retention window.

    The honest lost window is [last_covered, now − retention]: anything newer
    may still be sitting in the vendor's logs, and rotation means we cannot
    prove what existed — so callers phrase it "may be lost" (absent is not
    zero applies to warnings too). No prior coverage → no gap: a fresh
    machine is not a loss.
    """
    retention = timedelta(days=RETENTION_OBSERVED_DAYS)
    gaps = []
    for source, ts in sorted(last_covered.items()):
        if ts is not None and now - ts > retention:
            gaps.append(Gap(source=source, last_covered=ts,
                            lost_from=ts, lost_to=now - retention))
    return gaps


def last_covered_from_disk(data_dir: Path) -> dict[str, datetime]:
    """Per-source last-covered times. Prefers the collection state file
    (updated even by activity-gated no-op runs — a verified-idle tick IS
    coverage); falls back to scanning recent extract-run manifests so users
    from before the state file existed still get warned."""
    state_path = data_dir / STATE_FILENAME
    if state_path.exists():
        state = json.loads(state_path.read_text())
        covered = state.get("last_covered") or {}
        return {src: datetime.fromisoformat(ts)
                for src, ts in covered.items() if ts}

    manifests = data_dir / "manifests"
    if not manifests.is_dir():
        return {}
    out: dict[str, datetime] = {}
    # filenames sort chronologically (run_id is a UTC timestamp prefix)
    for path in sorted(manifests.glob("*.json"),
                       reverse=True)[:_FALLBACK_MANIFEST_SCAN]:
        try:
            m = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("kind") is not None or "sources" not in m:
            continue  # signals manifests are not collection coverage
        ts = m.get("finished_at") or m.get("started_at")
        if not ts:
            continue
        when = datetime.fromisoformat(ts)
        for src in m["sources"]:
            if src not in out or when > out[src]:
                out[src] = when
    return out


def health_nudge() -> None:
    """Invocation-time warning, policy_nudge-shaped: read state, bail
    silently when there is nothing to say, print loudly when collection has
    lapsed past the retention window. Called before dispatch for every
    command except `caliper setup` (about to backfill) and `--scheduled`
    runs (they ARE the collector)."""
    from .paths import extracted_dir
    from .style import S, box

    data_dir = extracted_dir()
    if not data_dir.is_dir():
        return
    try:
        last = last_covered_from_disk(data_dir)
        gaps = collection_gap(last, datetime.now(timezone.utc))
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return  # health bookkeeping must never break the actual command
    if not gaps:
        return
    lines = []
    for g in gaps:
        lines.append(f"{g.source}: last collected "
                     f"{g.last_covered:%Y-%m-%d %H:%M}Z — activity between "
                     f"then and {g.lost_to:%Y-%m-%d} may be permanently lost")
    print(box(S.bred("Collection gap — the retention window has passed"),
              "",
              *lines,
              "",
              S.dim(f"Vendor logs rotate after ~{RETENTION_OBSERVED_DAYS} "
                    "days (observed, ADR-0009). This is the known retention "
                    "limitation, not a bug."),
              S.dim("Collect now: ") + S.accent("caliper extract")))
    print()
