"""Classification orchestration: extracted records -> task_class records.

Reads ONLY data/extracted/*/sessions.jsonl and prompt_units.jsonl. Never
raw logs, never content sidecars (tests enforce). Sessions without prompt
units (cursor; rotated-log claude sessions) get session-grain records from
session aggregates only."""

from __future__ import annotations

import json
from pathlib import Path

from . import (CLASSIFIER_VERSION, SEGMENTER_VERSION, TASK_CLASS_SCHEMA_VERSION,
               TAXONOMY_VERSION)
from .features import FEATURE_NAMES, features_from_session, features_from_units
from .rules import classify_features
from .segmenter import segment_units

TOOLS = ("claude_code", "cursor", "codex")


def _breadth(f: dict) -> str:
    if not f["files_edited"]:
        return "unknown"
    if f.get("top_dirs", 0) >= 2:
        return "cross_module"
    if f.get("top_dirs", 0) == 1:
        return "localized"
    return "unknown"


def _record(unit: str, unit_ref: dict, f: dict, verdict: dict) -> dict:
    return {
        "schema_version": TASK_CLASS_SCHEMA_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "unit": unit,
        "unit_ref": unit_ref,
        "status": verdict["status"],
        "task_type": verdict["task_type"],
        "other_note": None,
        "context_breadth": _breadth(f),
        "risk": {"test_coverage": "unknown", "criticality": "unknown"},
        "confidence": verdict["confidence"],
        "alternatives": verdict["alternatives"],
        "method": {"kind": "rule", "rule_ids": [verdict["rule_id"]],
                   "model_id": None, "rationale": verdict["rationale"]},
        "features_used": FEATURE_NAMES,
    }


def load_extracted(data_dir: Path):
    sessions, units_by_session = {}, {}
    for tool in TOOLS:
        sp = data_dir / tool / "sessions.jsonl"
        if sp.exists():
            for line in sp.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    sessions[r["session_id"]] = r
        up = data_dir / tool / "prompt_units.jsonl"
        if up.exists():
            for line in up.read_text().splitlines():
                if line.strip():
                    u = json.loads(line)
                    units_by_session.setdefault(u["session_id"], []).append(u)
    for us in units_by_session.values():
        us.sort(key=lambda u: u["turn_index"])
    return sessions, units_by_session


def classify_all(data_dir: Path, units: tuple[str, ...] = ("prompt", "segment", "session")):
    sessions, units_by_session = load_extracted(data_dir)
    records = []

    if "prompt" in units:
        for sid, us in units_by_session.items():
            for u in us:
                f = features_from_units([u])
                v = classify_features(f)
                records.append(_record("prompt", {
                    "session_id": sid,
                    "turn_range": {"start_turn": u["turn_index"],
                                   "end_turn": u["turn_index"]},
                    "segment_id": None, "segmenter_version": None,
                }, f, v))

    if "segment" in units:
        for sid, us in units_by_session.items():
            for seg in segment_units(us):
                members = [u for u in us if u["turn_index"] in set(seg["member_indices"])]
                f = features_from_units(members)
                v = classify_features(f)
                records.append(_record("segment", {
                    "session_id": sid,
                    "turn_range": seg["turn_range"],
                    "segment_id": seg["segment_id"],
                    "segmenter_version": SEGMENTER_VERSION,
                }, f, v))

    if "session" in units:
        for sid, rec in sessions.items():
            us = units_by_session.get(sid)
            f = features_from_units(us) if us else features_from_session(rec)
            v = classify_features(f)
            records.append(_record("session", {
                "session_id": sid, "turn_range": None,
                "segment_id": None, "segmenter_version": None,
            }, f, v))

    return records
