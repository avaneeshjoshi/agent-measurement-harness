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

# Retention model (ADR-0011 postscript — correcting ADR-0009's n=1 reading):
# measured on 2026-08-23, Claude Code deletes session logs at its
# cleanupPeriodDays setting (default 30; deletion boundary observed between
# 29d-old surviving and 45d-old deleted files). Codex and Cursor showed NO
# rotation (files ≥6 months old; cumulative DBs). The old
# RETENTION_OBSERVED_DAYS=3 over-generalized one July log crossing the
# 30-day boundary. Thresholds are derived per source and per machine; every
# warning states its derivation.
CLAUDE_CLEANUP_DEFAULT_DAYS = 30
# Warn once a lapse passes half the rotation window: early enough to act,
# derived from the window rather than a second magic number.
RETENTION_WARN_FRACTION = 0.5
# Non-rotating sources: a lapse is a coverage problem, never a loss. Two
# stale weeks is where the picture stops being current.
COVERAGE_GAP_DAYS = 14

STATE_FILENAME = ".collection.json"

# How many recent manifests the fallback scan reads when no state file
# exists yet (pre-state users still deserve the warning).
_FALLBACK_MANIFEST_SCAN = 50

# ---- drift-canary thresholds (ADR-0011 threshold table) --------------------
# Count canaries pool a trailing baseline because scheduled runs often emit
# 1-3 records — per-run rates would false-positive constantly.
CANARY_BASELINE_RUNS = 20     # pooled same-version manifests per source
CANARY_MIN_EVENTS = 5         # absolute floor: one weird record in a
                              # three-record run is not an alarm
CANARY_RATE_MULTIPLIER = 3.0  # current smoothed rate vs pooled baseline
# Field coverage (the removed-field case, ADR-0005 §4) is computed over
# trailing session windows keyed by started_at, not per-run emissions.
COVERAGE_RECENT_DAYS = 7
COVERAGE_BASELINE_DAYS = 28   # the window immediately preceding "recent"
COVERAGE_MIN_RECENT_N = 10
COVERAGE_MIN_BASELINE_N = 30
COVERAGE_BASELINE_FLOOR = 0.8  # only fields that were reliably present
COVERAGE_DROP_ABS = 0.3        # alarm on a >=30-point absolute drop


@dataclass
class RetentionWindow:
    days: float | None  # None = no rotation observed for this source
    basis: str          # stated in the warning itself — never a bare number


@dataclass
class Gap:
    source: str
    last_covered: datetime
    kind: str  # "loss" | "at_risk" | "coverage"
    window_days: float | None
    basis: str
    lost_from: datetime | None = None
    lost_to: datetime | None = None


def claude_cleanup_days(settings_path: Path | None = None) -> tuple[int, str]:
    """This machine's actual Claude Code rotation window. Someone who set
    cleanupPeriodDays=7 has a real 7-day window; someone at 365 should
    barely ever be warned — so read the setting, default only as fallback,
    and return the basis so the warning can state its derivation."""
    path = settings_path or Path.home() / ".claude" / "settings.json"
    try:
        v = json.loads(path.read_text()).get("cleanupPeriodDays")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return int(v), f"your cleanupPeriodDays={int(v)}"
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return CLAUDE_CLEANUP_DEFAULT_DAYS, (
        f"Claude Code default {CLAUDE_CLEANUP_DEFAULT_DAYS}d — "
        "cleanupPeriodDays unset")


def retention_windows(settings_path: Path | None = None
                      ) -> dict[str, RetentionWindow]:
    days, basis = claude_cleanup_days(settings_path)
    return {
        "claude_code": RetentionWindow(days=days, basis=basis),
        "codex": RetentionWindow(days=None, basis="no rotation observed — "
                                 "files ≥6 months old on disk"),
        "cursor": RetentionWindow(days=None, basis="cumulative databases, "
                                  "no rotation"),
    }


_NON_ROTATING = RetentionWindow(days=None,
                                basis="unknown source — treated as "
                                      "non-rotating")


def collection_gap(last_covered: dict[str, datetime | None],
                   now: datetime,
                   windows: dict[str, RetentionWindow] | None = None
                   ) -> list[Gap]:
    """Per-source, per-machine gap classification.

    Rotating sources (Claude Code): "loss" once the lapse exceeds the
    rotation window — the may-already-be-rotated span is
    [last_covered, now − window], since anything newer may still be in the
    logs and rotation means we cannot prove what existed (absent is not zero
    applies to warnings too). "at_risk" past half the window: nothing lost
    yet, time to act. Non-rotating sources (Codex, Cursor): a lapse is a
    "coverage" gap — the picture is stale, nothing is lost. No prior
    coverage → no gap: a fresh machine is not a loss.
    """
    windows = windows or {}
    gaps = []
    for source, ts in sorted(last_covered.items()):
        if ts is None:
            continue
        lapse = now - ts
        w = windows.get(source, _NON_ROTATING)
        if w.days is None:
            if lapse > timedelta(days=COVERAGE_GAP_DAYS):
                gaps.append(Gap(source=source, last_covered=ts,
                                kind="coverage", window_days=None,
                                basis=w.basis))
            continue
        window = timedelta(days=w.days)
        if lapse > window:
            gaps.append(Gap(source=source, last_covered=ts, kind="loss",
                            window_days=w.days, basis=w.basis,
                            lost_from=ts, lost_to=now - window))
        elif lapse > window * RETENTION_WARN_FRACTION:
            gaps.append(Gap(source=source, last_covered=ts, kind="at_risk",
                            window_days=w.days, basis=w.basis))
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


@dataclass
class RunStats:
    source: str
    unknown_count: int
    records_seen: int
    skip_count: int
    artifacts_discovered: int
    connector_version: str | None
    schema_version: str | None


def run_stats_from_manifest(m: dict, source: str) -> RunStats:
    src = m["sources"][source]
    notes = src.get("notes") or {}
    return RunStats(
        source=source,
        unknown_count=sum((notes.get("unknown_record_types") or {}).values()),
        records_seen=notes.get("raw_records_seen") or 0,
        skip_count=len(src.get("skipped") or []),
        artifacts_discovered=src.get("artifacts_discovered") or 0,
        connector_version=m.get("connector_version"),
        schema_version=m.get("schema_version"))


def _rate(x: int, n: int) -> float:
    return (x + 1) / (n + 2)  # Laplace-smoothed: defined even at n=0


def canary_counts(current: RunStats, baseline: list[RunStats]) -> list[dict]:
    """Count canaries: unknown shapes and skip rate vs a pooled same-version
    baseline. A contract bump re-emits everything, so mixed-version pooling
    would trip on the storm — same-version only, which also means an empty
    baseline (fresh install, fresh version) never alarms."""
    same = [b for b in baseline
            if (b.connector_version, b.schema_version)
            == (current.connector_version, current.schema_version)]
    alarms: list[dict] = []

    def check(kind: str, cur_x: int, cur_n: int,
              base_x: int, base_n: int, what: str) -> None:
        if cur_x < CANARY_MIN_EVENTS:
            return
        if _rate(cur_x, cur_n) >= CANARY_RATE_MULTIPLIER * _rate(base_x, base_n):
            alarms.append({
                "key": f"{current.source}:{kind}",
                "source": current.source, "kind": kind,
                "detail": (f"{what}: {cur_x}/{cur_n} this run vs "
                           f"{base_x}/{base_n} across {len(same)} baseline "
                           f"runs (ADR-0011 thresholds)")})

    check("unknown_shapes", current.unknown_count, current.records_seen,
          sum(b.unknown_count for b in same),
          sum(b.records_seen for b in same),
          "unrecognized record shapes jumped")
    check("skip_rate", current.skip_count, current.artifacts_discovered,
          sum(b.skip_count for b in same),
          sum(b.artifacts_discovered for b in same),
          "artifact skip rate jumped")
    return alarms


def _present_keys(rec: dict) -> set[str]:
    """Depth-2 dotted keys with non-null values — 'vcs.branch'-style keys are
    what catch a vendor removing a block (the ADR-0005 Codex git case)."""
    out: set[str] = set()
    for k, v in rec.items():
        if v is None:
            continue
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if v2 is not None:
                    out.add(f"{k}.{k2}")
        else:
            out.add(k)
    return out


def field_coverage_alarms(sessions: list[dict], source: str,
                          now: datetime) -> list[dict]:
    """The removed-field canary: for fields that were reliably present in the
    trailing baseline window, alarm when recent coverage sinks. Windows are
    keyed by started_at over on-disk sessions, so there is enough n even when
    each scheduled run emits almost nothing."""
    recent_lo = now - timedelta(days=COVERAGE_RECENT_DAYS)
    base_lo = recent_lo - timedelta(days=COVERAGE_BASELINE_DAYS)
    recent: list[set[str]] = []
    base: list[set[str]] = []
    for r in sessions:
        ts = r.get("started_at")
        if not ts:
            continue
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= recent_lo:
            recent.append(_present_keys(r))
        elif t >= base_lo:
            base.append(_present_keys(r))
    if len(recent) < COVERAGE_MIN_RECENT_N or len(base) < COVERAGE_MIN_BASELINE_N:
        return []  # thin windows: silence, not guesses

    def coverage(pop: list[set[str]]) -> dict[str, float]:
        counts: dict[str, int] = {}
        for keys in pop:
            for k in keys:
                counts[k] = counts.get(k, 0) + 1
        return {k: c / len(pop) for k, c in counts.items()}

    base_cov = coverage(base)
    recent_cov = coverage(recent)
    alarms = []
    for field, bc in sorted(base_cov.items()):
        if bc < COVERAGE_BASELINE_FLOOR:
            continue  # was never reliably present; its absence is not drift
        rc = recent_cov.get(field, 0.0)
        if rc <= bc - COVERAGE_DROP_ABS:
            alarms.append({
                "key": f"{source}:field_coverage:{field}",
                "source": source, "kind": "field_coverage",
                "detail": (f"{field} coverage {bc:.0%} → {rc:.0%} over "
                           f"trailing {COVERAGE_RECENT_DAYS}d vs prior "
                           f"{COVERAGE_BASELINE_DAYS}d "
                           f"(n={len(recent)} vs {len(base)}) — a source "
                           "format may have dropped the field (ADR-0005 §4)")})
    return alarms


_CANARY_KINDS = ("unknown_shapes", "skip_rate", "field_coverage")


def evaluate_canaries(data_dir: Path, manifest: dict,
                      now: datetime | None = None,
                      exclude_run_ids: set[str] | None = None,
                      patch_file: bool = True) -> list[dict]:
    """Run all canaries for the sources in this manifest, persist alarms to
    collection state (load-bearing: a scheduled run's stdout goes to a log
    nobody reads — state is what the next interactive invocation surfaces),
    and patch them into the manifest file when it exists. Alarms self-clear:
    each run replaces the canary alarms for the sources it processed."""
    now = now or datetime.now(timezone.utc)
    exclude = exclude_run_ids or ({manifest["run_id"]}
                                  if manifest.get("run_id") else set())
    baselines: dict[str, list[RunStats]] = {s: [] for s in manifest["sources"]}
    mdir = data_dir / "manifests"
    if mdir.is_dir():
        for path in sorted(mdir.glob("*.json"), reverse=True):
            if path.stem in exclude:
                continue
            if all(len(v) >= CANARY_BASELINE_RUNS for v in baselines.values()):
                break
            try:
                m = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if m.get("kind") is not None or "sources" not in m:
                continue
            for source in baselines:
                if source in m["sources"] \
                        and len(baselines[source]) < CANARY_BASELINE_RUNS:
                    baselines[source].append(run_stats_from_manifest(m, source))

    alarms: list[dict] = []
    for source in manifest["sources"]:
        current = run_stats_from_manifest(manifest, source)
        alarms.extend(canary_counts(current, baselines[source]))
        sessions_path = data_dir / source / "sessions.jsonl"
        if sessions_path.exists():
            sessions = [json.loads(l) for l in
                        sessions_path.read_text().splitlines() if l.strip()]
            alarms.extend(field_coverage_alarms(sessions, source, now))

    for a in alarms:
        a["raised_at"] = now.isoformat(timespec="seconds")
        src = manifest["sources"][a["source"]]
        src.setdefault("notes", {}).setdefault("drift_alarms", []).append(
            {k: a[k] for k in ("kind", "detail")})

    # persist: replace this run's sources' canary alarms, keep the rest
    from .collection import load_state, save_state
    state = load_state(data_dir)
    kept = [a for a in state.get("pending_alarms", [])
            if a.get("kind") not in _CANARY_KINDS
            or a.get("source") not in manifest["sources"]]
    state["pending_alarms"] = kept + alarms
    save_state(data_dir, state)

    run_id = manifest.get("run_id")
    if patch_file and run_id and (mdir / f"{run_id}.json").exists():
        (mdir / f"{run_id}.json").write_text(json.dumps(manifest, indent=2))
    return alarms


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
        gaps = collection_gap(last, datetime.now(timezone.utc),
                              windows=retention_windows())
        state_path = data_dir / STATE_FILENAME
        alarms = (json.loads(state_path.read_text()).get("pending_alarms")
                  or []) if state_path.exists() else []
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return  # health bookkeeping must never break the actual command
    from .style import step
    for a in alarms:
        print(step(S.byellow(f"drift alarm · {a.get('source', '?')}")
                   + " " + S.dim(str(a.get("detail", "")))))
        print()
    if not gaps:
        return
    collect_hint = (S.dim("Collect now: ") + S.accent("caliper extract")
                    + S.dim(" · keep it continuous: ")
                    + S.accent("caliper schedule install"))
    losses = [g for g in gaps if g.kind == "loss"]
    if losses:
        lines = [f"{g.source}: last collected {g.last_covered:%Y-%m-%d} — "
                 f"logs rotate at ~{g.window_days:.0f}d ({g.basis}); "
                 f"activity between then and {g.lost_to:%Y-%m-%d} may "
                 "already be rotated away"
                 for g in losses]
        print(box(S.bred("Collection gap — a rotation window has passed"),
                  "", *lines, "",
                  S.dim("Rotation means what existed cannot be proven — "
                        "\"may be lost\", never \"was\". Known limitation "
                        "(ADR-0011 postscript), not a bug."),
                  collect_hint))
        print()
    for g in gaps:
        if g.kind == "at_risk":
            deadline = g.last_covered + timedelta(days=g.window_days)
            print(step(S.byellow(f"{g.source}: collection is lapsing")
                       + " " + S.dim(f"last collected "
                                     f"{g.last_covered:%Y-%m-%d}; logs "
                                     f"rotate at ~{g.window_days:.0f}d "
                                     f"({g.basis}) — collect before "
                                     f"{deadline:%Y-%m-%d}")))
            print()
        elif g.kind == "coverage":
            print(step(S.byellow(f"{g.source}: no collection since "
                                 f"{g.last_covered:%Y-%m-%d}")
                       + " " + S.dim(f"nothing is lost ({g.basis}) — "
                                     "but the picture is stale")))
            print()
    if not losses:
        print("    " + collect_hint)
        print()
