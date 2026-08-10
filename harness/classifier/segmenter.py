"""Segmenter 0.1.0 — observable boundaries only, per docs/conventions.md.

A new segment opens at user prompt turn T when any rule fires. Precedence for
the opened_by label when several fire: turn_gap > branch_change >
file_set_jump > interrupt. No semantic or content inference.

Known v0 limitations are recorded in conventions.md and ADR-0002 (finding 2:
on solo single-branch traffic this degenerates to a gap-splitter); they are
measurement facts, not bugs to tune away.
"""

from __future__ import annotations

from . import SEGMENTER_VERSION

TURN_GAP_MS = 30 * 60 * 1000


def segment_units(units: list[dict]) -> list[dict]:
    """Group a session's prompt units (sorted by turn_index) into segments.

    Returns [{segment_id, turn_range, started_at, ended_at, opened_by,
    segmenter_version, member_indices}]. segment_id uses the 8-char session
    prefix to match the ADR-0002 calibration convention."""
    if not units:
        return []
    units = sorted(units, key=lambda u: u["turn_index"])
    sid8 = units[0]["session_id"][:8]

    segments: list[dict] = []
    current: list[dict] = []
    seg_files: set[str] = set()
    seg_dirs: set[str] = set()

    def files_of(u):
        fe = u["window"].get("files_edited") or []
        return {f["file_ref"] for f in fe}, {f["top_dir_ref"] for f in fe}

    def close(opened_by_next=None):
        nonlocal current, seg_files, seg_dirs
        if current:
            segments.append({
                "segment_id": f"{sid8}-seg{len(segments)}",
                "turn_range": {"start_turn": current[0]["turn_index"],
                               "end_turn": current[-1]["turn_index"]},
                "started_at": current[0]["started_at"],
                "ended_at": current[-1].get("window_ended_at") or current[-1]["started_at"],
                "opened_by": current[0]["_opened_by"],
                "segmenter_version": SEGMENTER_VERSION,
                "member_indices": [u["turn_index"] for u in current],
            })
        current, seg_files, seg_dirs = [], set(), set()

    prev = None
    for u in units:
        if prev is None:
            opened = "session_start"
        else:
            fired = []
            if (u.get("gap_ms_before") or 0) > TURN_GAP_MS:
                fired.append("turn_gap")
            if u.get("git_branch") and prev.get("git_branch") \
                    and u["git_branch"] != prev["git_branch"]:
                fired.append("branch_change")
            uf, ud = files_of(u)
            if uf and seg_files and not (uf & seg_files) and not (ud & seg_dirs):
                fired.append("file_set_jump")
            if prev["window"].get("interrupted"):
                fired.append("interrupt")
            opened = fired[0] if fired else None  # list order = precedence order

        if opened and prev is not None:
            close()
        if opened:
            u = dict(u); u["_opened_by"] = opened
        current.append(u)
        uf, ud = files_of(u)
        seg_files |= uf
        seg_dirs |= ud
        prev = u
    close()
    return segments
