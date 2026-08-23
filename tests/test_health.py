"""Gap-detection logic (ADR-0011 + its retention postscript): per-source,
per-machine rotation windows (cleanupPeriodDays-derived for Claude Code,
non-rotating for Codex/Cursor), the loss/at-risk/coverage gap kinds, and the
state/manifest fallback."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cli.health import (CLAUDE_CLEANUP_DEFAULT_DAYS, COVERAGE_GAP_DAYS,
                        STATE_FILENAME, RetentionWindow, claude_cleanup_days,
                        collection_gap, last_covered_from_disk,
                        retention_windows)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def test_gap_none_without_prior_coverage():
    assert collection_gap({}, NOW) == []
    assert collection_gap({"claude_code": None}, NOW) == []


WIN = {"claude_code": RetentionWindow(days=30, basis="test basis")}


def test_gap_loss_past_rotation_window_names_span_and_basis():
    last = _ago(days=31)
    [gap] = collection_gap({"claude_code": last}, NOW, windows=WIN)
    assert gap.kind == "loss"
    assert gap.lost_from == last
    # anything newer than now - window may still be in the vendor's logs
    assert gap.lost_to == NOW - timedelta(days=30)
    assert gap.basis == "test basis"  # the derivation travels with the gap


def test_gap_at_risk_past_half_window():
    [gap] = collection_gap({"claude_code": _ago(days=16)}, NOW, windows=WIN)
    assert gap.kind == "at_risk"
    assert gap.lost_from is None  # nothing lost yet


def test_gap_silent_below_half_window():
    assert collection_gap({"claude_code": _ago(days=14)}, NOW,
                          windows=WIN) == []


def test_gap_nonrotating_source_is_coverage_not_loss():
    windows = retention_windows()
    [gap] = collection_gap({"codex": _ago(days=COVERAGE_GAP_DAYS + 1)},
                           NOW, windows=windows)
    assert gap.kind == "coverage"
    assert gap.lost_from is None
    assert collection_gap({"codex": _ago(days=COVERAGE_GAP_DAYS - 1)},
                          NOW, windows=windows) == []


def test_gap_unknown_source_treated_as_nonrotating():
    [gap] = collection_gap({"mystery_tool": _ago(days=20)}, NOW, windows=WIN)
    assert gap.kind == "coverage"


def test_gap_is_per_source():
    covered = {"claude_code": _ago(hours=2), "cursor": _ago(days=20)}
    gaps = collection_gap(covered, NOW, windows=retention_windows())
    assert [(g.source, g.kind) for g in gaps] == [("cursor", "coverage")]


def test_claude_cleanup_days_reads_user_setting(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"cleanupPeriodDays": 7}))
    days, basis = claude_cleanup_days(p)
    assert days == 7
    assert "your cleanupPeriodDays=7" in basis


def test_claude_cleanup_days_falls_back_to_default(tmp_path):
    days, basis = claude_cleanup_days(tmp_path / "missing.json")
    assert days == CLAUDE_CLEANUP_DEFAULT_DAYS
    assert "default" in basis and "unset" in basis
    garbage = tmp_path / "settings.json"
    garbage.write_text("{not json")
    assert claude_cleanup_days(garbage)[0] == CLAUDE_CLEANUP_DEFAULT_DAYS
    garbage.write_text(json.dumps({"cleanupPeriodDays": True}))  # bool trap
    assert claude_cleanup_days(garbage)[0] == CLAUDE_CLEANUP_DEFAULT_DAYS


def test_retention_windows_per_machine(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"cleanupPeriodDays": 365}))
    w = retention_windows(settings_path=p)
    assert w["claude_code"].days == 365  # 365 -> a year of quiet, by design
    assert w["codex"].days is None and w["cursor"].days is None


def _write_manifest(mdir: Path, run_id: str, finished_at: str,
                    sources: list[str], kind: str | None = None):
    m: dict = {"run_id": run_id, "started_at": finished_at,
               "finished_at": finished_at}
    if kind:
        m["kind"] = kind
        m["repos"] = {}
    else:
        m["sources"] = {s: {"records": {}} for s in sources}
    (mdir / f"{run_id}.json").write_text(json.dumps(m))


def test_last_covered_falls_back_to_manifest_scan(tmp_path):
    mdir = tmp_path / "manifests"
    mdir.mkdir()
    _write_manifest(mdir, "20260810T000000Z-aa", "2026-08-10T00:00:01.000Z",
                    ["claude_code", "codex"])
    _write_manifest(mdir, "20260812T000000Z-bb", "2026-08-12T00:00:01.000Z",
                    ["claude_code"])
    # a signals manifest is not collection coverage and must be ignored
    _write_manifest(mdir, "20260820T000000Z-cc", "2026-08-20T00:00:01.000Z",
                    [], kind="signals")
    covered = last_covered_from_disk(tmp_path)
    assert covered["claude_code"].isoformat().startswith("2026-08-12")
    assert covered["codex"].isoformat().startswith("2026-08-10")


def test_last_covered_prefers_state_file(tmp_path):
    (tmp_path / "manifests").mkdir()
    _write_manifest(tmp_path / "manifests", "20260801T000000Z-aa",
                    "2026-08-01T00:00:01.000Z", ["claude_code"])
    (tmp_path / STATE_FILENAME).write_text(json.dumps(
        {"last_covered": {"claude_code": "2026-08-22T09:00:00+00:00"}}))
    covered = last_covered_from_disk(tmp_path)
    assert covered["claude_code"].isoformat().startswith("2026-08-22")


def test_last_covered_empty_when_nothing_on_disk(tmp_path):
    assert last_covered_from_disk(tmp_path) == {}


# ---- drift canaries (ADR-0011) --------------------------------------------

from cli.health import (COVERAGE_DROP_ABS, CANARY_MIN_EVENTS, RunStats,  # noqa: E402
                        canary_counts, field_coverage_alarms)


def _stats(source="codex", unknown=0, seen=1000, skips=0, discovered=50,
           cv="0.3.1", sv="0.4.0"):
    return RunStats(source=source, unknown_count=unknown, records_seen=seen,
                    skip_count=skips, artifacts_discovered=discovered,
                    connector_version=cv, schema_version=sv)


def test_canary_unknown_spike_fires():
    baseline = [_stats() for _ in range(20)]
    [alarm] = canary_counts(_stats(unknown=10, seen=50), baseline)
    assert alarm["kind"] == "unknown_shapes"
    assert alarm["source"] == "codex"


def test_canary_below_min_events_silent_on_tiny_run():
    baseline = [_stats() for _ in range(20)]
    tiny = _stats(unknown=CANARY_MIN_EVENTS - 1, seen=3)
    assert canary_counts(tiny, baseline) == []


def test_canary_skip_rate_spike_fires():
    baseline = [_stats() for _ in range(20)]
    [alarm] = canary_counts(_stats(skips=20, discovered=40), baseline)
    assert alarm["kind"] == "skip_rate"


def test_canary_steady_rates_stay_silent():
    baseline = [_stats(unknown=5, seen=1000) for _ in range(20)]
    assert canary_counts(_stats(unknown=6, seen=1100), baseline) == []


def test_canary_version_bump_resets_baseline():
    baseline = [_stats(cv="0.3.1") for _ in range(20)]
    bumped = _stats(unknown=10, seen=50, cv="0.4.0")
    # same numbers fired against a same-version baseline; a bumped run has
    # no comparable history yet, so it must stay silent, not trip
    assert canary_counts(bumped, baseline) == []


def _session(days_old: float, with_branch: bool):
    rec = {"started_at": (NOW - timedelta(days=days_old)).isoformat(),
           "tokens": {"input": 1, "output": 1}}
    if with_branch:
        rec["git_branch"] = "main"
    return rec


def _baseline_sessions(with_branch=True, n=34):
    # ages 7.5..34.x days: inside the [7d, 35d) baseline window, n >= 30
    return [_session(7.5 + i * 0.8, with_branch) for i in range(n)]


def test_coverage_removed_field_fires():
    sessions = _baseline_sessions(True) + \
               [_session(d / 2, False) for d in range(12)]
    [alarm] = field_coverage_alarms(sessions, "claude_code", NOW)
    assert alarm["kind"] == "field_coverage"
    assert "git_branch" in alarm["key"]


def test_coverage_thin_windows_silent():
    sessions = _baseline_sessions(True) + \
               [_session(1, False) for _ in range(5)]  # only 5 recent
    assert field_coverage_alarms(sessions, "claude_code", NOW) == []


def test_coverage_ignores_rarely_present_fields():
    # the field was only at 30% baseline coverage — its absence is not drift
    base = [_session(7.5 + i * 0.8, with_branch=(i % 3 == 0))
            for i in range(34)]
    recent = [_session(1, False) for _ in range(12)]
    alarms = field_coverage_alarms(base + recent, "claude_code", NOW)
    assert all("git_branch" not in a["key"] for a in alarms)


def test_coverage_stable_fields_stay_silent():
    sessions = _baseline_sessions(True) + \
               [_session(1, True) for _ in range(12)]
    assert field_coverage_alarms(sessions, "claude_code", NOW) == []
