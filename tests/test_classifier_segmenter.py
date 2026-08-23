"""Segmenter 0.1.0 unit tests — each observable boundary rule, plus the
calibration-reproduction check (which requires extracted local data and
skips cleanly elsewhere)."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import pytest

from harness.classifier.segmenter import TURN_GAP_MS, segment_units
from tests.conftest import REPO


def unit(i, ts="2026-01-01T10:00:00.000Z", gap=0, branch="main",
         files=(), interrupted=False):
    return {
        "session_id": "aaaabbbb-x", "source_tool": "claude_code",
        "turn_index": i, "started_at": ts, "window_ended_at": ts,
        "gap_ms_before": gap, "git_branch": branch,
        "window": {"assistant_messages": 1, "tool_calls": 0,
                   "interrupted": interrupted,
                   "files_edited": [{"file_ref": f, "top_dir_ref": "d_" + f[:2]}
                                    for f in files]},
    }


def test_single_segment_session_start():
    segs = segment_units([unit(0), unit(1), unit(2)])
    assert len(segs) == 1
    assert segs[0]["opened_by"] == "session_start"
    assert segs[0]["turn_range"] == {"start_turn": 0, "end_turn": 2}
    assert segs[0]["segment_id"] == "aaaabbbb-seg0"


def test_turn_gap_boundary():
    segs = segment_units([unit(0), unit(1, gap=TURN_GAP_MS + 1)])
    assert [s["opened_by"] for s in segs] == ["session_start", "turn_gap"]


def test_branch_change_boundary():
    segs = segment_units([unit(0), unit(1, branch="feature/x")])
    assert [s["opened_by"] for s in segs] == ["session_start", "branch_change"]


def test_branch_null_is_not_a_change():
    segs = segment_units([unit(0, branch=None), unit(1, branch="main")])
    assert len(segs) == 1


def test_file_set_jump_needs_both_levels_disjoint():
    # same top dir -> no jump even with disjoint files
    segs = segment_units([unit(0, files=("aa1",)), unit(1, files=("aa2",))])
    assert len(segs) == 1
    # disjoint at file AND top-dir level -> jump
    segs = segment_units([unit(0, files=("aa1",)), unit(1, files=("zz9",))])
    assert [s["opened_by"] for s in segs] == ["session_start", "file_set_jump"]
    # empty file sets never jump
    segs = segment_units([unit(0, files=()), unit(1, files=("zz9",))])
    assert len(segs) == 1


def test_interrupt_boundary_from_tool_result_flag():
    segs = segment_units([unit(0, interrupted=True), unit(1)])
    assert [s["opened_by"] for s in segs] == ["session_start", "interrupt"]


def test_precedence_gap_beats_interrupt():
    segs = segment_units([unit(0, interrupted=True),
                          unit(1, gap=TURN_GAP_MS + 1)])
    assert segs[1]["opened_by"] == "turn_gap"


def test_reproduces_calibration_boundaries():
    """The 0.1.0 identity check: every validatable ADR-0002 segment must be
    reproduced exactly from extracted prompt units."""
    # Machine-local reproduction check: reads this machine's real extracted
    # units from the data home (ADR-0011) — not the CALIPER_HOME test sandbox.
    units_path = (Path(os.environ.get("CALIPER_REAL_HOME")
                       or Path.home() / ".caliper")
                  / "extracted" / "claude_code" / "prompt_units.jsonl")
    if not units_path.exists():
        pytest.skip("no extracted prompt units on this machine")
    by_sid = defaultdict(list)
    for line in units_path.read_text().splitlines():
        u = json.loads(line)
        by_sid[u["session_id"]].append(u)
    cal = [json.loads(l) for l in
           (REPO / "data" / "calibration" / "unit-comparison-2026-08-07" /
            "segment_units.jsonl").read_text().splitlines()]
    cal_by = defaultdict(list)
    for r in cal:
        u = r["unit_ref"]
        cal_by[u["session_id"]].append(
            (u["segment_id"], u["turn_range"]["start_turn"], u["turn_range"]["end_turn"]))
    checked = 0
    for sid8, expected in cal_by.items():
        mine = next((segment_units(us) for sid, us in by_sid.items()
                     if sid.startswith(sid8)), None)
        if mine is None:
            continue  # raw log rotated away (ADR-0009)
        got = [(s["segment_id"], s["turn_range"]["start_turn"],
                s["turn_range"]["end_turn"]) for s in mine]
        assert got == sorted(expected, key=lambda x: x[1]), sid8
        checked += len(expected)
    assert checked >= 10  # at least the surviving sessions' segments
