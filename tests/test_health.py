"""Gap-detection threshold logic (ADR-0011): the ~3-day retention constant,
the may-be-lost window math, and the state/manifest fallback."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cli.health import (RETENTION_OBSERVED_DAYS, STATE_FILENAME,
                        collection_gap, last_covered_from_disk)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def _ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


def test_gap_none_without_prior_coverage():
    assert collection_gap({}, NOW) == []
    assert collection_gap({"claude_code": None}, NOW) == []


def test_gap_under_threshold_silent():
    covered = {"claude_code": _ago(days=RETENTION_OBSERVED_DAYS, minutes=-1)}
    assert collection_gap(covered, NOW) == []


def test_gap_over_threshold_names_lost_window():
    last = _ago(days=10)
    [gap] = collection_gap({"codex": last}, NOW)
    assert gap.source == "codex"
    assert gap.lost_from == last
    # anything newer than now - retention may still be in the vendor's logs
    assert gap.lost_to == NOW - timedelta(days=RETENTION_OBSERVED_DAYS)


def test_gap_is_per_source():
    covered = {"claude_code": _ago(hours=2), "cursor": _ago(days=5)}
    gaps = collection_gap(covered, NOW)
    assert [g.source for g in gaps] == ["cursor"]


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
