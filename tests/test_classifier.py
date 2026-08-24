"""Classifier guarantees: content-free enforcement (the hard rule), schema
validity of emitted records, and rule behavior on synthetic units."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from harness.classifier.classify import classify_all
from tests.conftest import REPO

SENTINEL = "TOP_SECRET_PROMPT_TEXT_NEVER_READ"


def _fixture_extracted(tmp_path: Path) -> Path:
    """A minimal data/extracted layout WITH content sidecars present."""
    d = tmp_path / "extracted" / "claude_code"
    d.mkdir(parents=True)
    session = {"schema_version": "0.4.0", "session_id": "s1",
               "source_tool": "claude_code", "started_at": "2026-01-01T00:00:00.000Z",
               "provenance": {"log_format": "claude_code_jsonl",
                              "connector_version": "0.3.0",
                              "extracted_at": "2026-01-01T00:00:00.000Z",
                              "content_hash": "sha256:x",
                              "source_artifacts": [{"path": "/x", "sha256": "sha256:x"}]}}
    (d / "sessions.jsonl").write_text(json.dumps(session) + "\n")
    unit = {"schema_version": "0.1.1", "session_id": "s1", "source_tool": "claude_code",
            "turn_index": 0, "started_at": "2026-01-01T00:00:00.000Z",
            "window": {"assistant_messages": 1, "tool_calls": 2,
                       "tool_counts": {"WebSearch": 2}, "interrupted": False,
                       "files_edited": [], "lines_added": 0, "lines_removed": 0}}
    (d / "prompt_units.jsonl").write_text(json.dumps(unit) + "\n")
    # the sidecar the classifier must never open
    (d / "content.jsonl").write_text(json.dumps({"text": SENTINEL}) + "\n")
    return tmp_path / "extracted"


def test_classifier_never_opens_content_sidecar(tmp_path, monkeypatch):
    data_dir = _fixture_extracted(tmp_path)
    opened: list[str] = []
    real_open = builtins.open

    def spy_open(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    real_read_text = Path.read_text

    def spy_read_text(self, *a, **kw):
        opened.append(str(self))
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", spy_read_text)
    records = classify_all(data_dir)
    assert records, "classification produced no records"
    touched = [p for p in opened if "content.jsonl" in p]
    assert not touched, f"classifier opened content sidecars: {touched}"
    blob = json.dumps(records)
    assert SENTINEL not in blob


def test_classifier_source_has_no_sidecar_references():
    pkg = REPO / "harness" / "classifier"
    for f in pkg.glob("*.py"):
        assert "content.jsonl" not in f.read_text(), f"{f} references the sidecar"


def test_emitted_records_validate_and_web_qa_rule():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        data_dir = _fixture_extracted(Path(td))
        records = classify_all(data_dir)
    v = Draft202012Validator(json.loads(
        (REPO / "schemas" / "task_class.schema.json").read_text()))
    for r in records:
        v.validate(r)
    prompt = next(r for r in records if r["unit"] == "prompt")
    # WebSearch-heavy, zero edits -> exploratory_qa at raised confidence
    assert prompt["task_type"] == "exploratory_qa"
    assert prompt["confidence"] == 0.75
    assert prompt["features_used"], "features_used must be populated"
    assert prompt["method"]["rule_ids"] == ["R07-read-search-no-edits"]


# ---- neighborhood flow features (rules-0.2.0, ADR-0013) --------------------

def _unit(turn, browser=0, edits=0, tools=None):
    tc = dict(tools or {})
    if browser:
        tc["mcp__claude-in-chrome__computer"] = browser
    w = {"tool_calls": sum(tc.values()), "tool_counts": tc,
         "files_edited": [{"file_ref": f"f{turn}-{i}", "top_dir_ref": "d",
                           "extension": "py", "is_test_path": False,
                           "is_docs_path": False, "is_config_path": False,
                           "is_agent_config_path": False, "is_new_file": False}
                          for i in range(edits)]}
    return {"session_id": "s", "turn_index": turn, "window": w}


def test_neighborhood_is_segment_bounded_and_radius_limited():
    from harness.classifier.features import neighborhood_features
    us = [_unit(0, edits=1), _unit(1), _unit(2, browser=2),
          _unit(4, browser=5), _unit(9, browser=7)]
    seg = {0, 1, 2, 9}  # turn 4 is outside the segment; 9 is inside but far
    nbh = neighborhood_features(us, 0, seg)
    assert nbh["nbr_browser"] == 2  # turn 2 only: 4 out-of-segment, 9 out-of-radius
    nbh2 = neighborhood_features(us, 2, seg)
    assert nbh2["nbr_edits"] == 1  # sees turn 0's edit


def test_neighborhood_tolerates_missing_optional_fields():
    from harness.classifier.features import neighborhood_features
    us = [{"session_id": "s", "turn_index": 0, "window": {}},
          {"session_id": "s", "turn_index": 1, "window": {}}]
    assert neighborhood_features(us, 0, {0, 1}) == \
        {"nbr_browser": 0, "nbr_edits": 0}


def test_r01c_neighborhood_browser_flips_edit_window():
    from harness.classifier.features import features_from_units
    from harness.classifier.rules import classify_features
    f = features_from_units([_unit(0, edits=1)],
                            neighborhood={"nbr_browser": 1, "nbr_edits": 0})
    v = classify_features(f)
    assert v["rule_id"] == "R01c-neighborhood-browser"
    assert v["task_type"] == "ui_verification_loop"
    # in-window browser still wins as R01b — precedence preserved
    f2 = features_from_units([_unit(0, edits=1, browser=1)],
                             neighborhood={"nbr_browser": 3, "nbr_edits": 1})
    assert classify_features(f2)["rule_id"] == "R01b-browser-present-edits"


def test_r01d_flow_sandwich_reclaims_no_edit_windows():
    from harness.classifier.features import features_from_units
    from harness.classifier.rules import classify_features
    # a no-activity window that R06 would take, sandwiched in a browser flow
    f = features_from_units([_unit(5)],
                            neighborhood={"nbr_browser": 2, "nbr_edits": 1})
    v = classify_features(f)
    assert v["rule_id"] == "R01d-flow-sandwich"
    # weaker flow evidence does NOT reclaim it — thresholds are the contract
    f2 = features_from_units([_unit(5)],
                             neighborhood={"nbr_browser": 1, "nbr_edits": 1})
    assert classify_features(f2)["rule_id"] == "R06-no-activity"
    f3 = features_from_units([_unit(5)],
                             neighborhood={"nbr_browser": 2, "nbr_edits": 0})
    assert classify_features(f3)["rule_id"] == "R06-no-activity"


def test_no_neighborhood_means_zero_flow_features():
    """Segment/session grains pass no neighborhood — the flow rules must be
    structurally unable to fire there."""
    from harness.classifier.features import features_from_units
    f = features_from_units([_unit(0, edits=1)])
    assert f["nbr_browser"] == 0 and f["nbr_edits"] == 0


def test_classifier_version_stamped_020(tmp_path):
    from harness.classifier import CLASSIFIER_VERSION
    assert CLASSIFIER_VERSION == "rules-0.2.0"
