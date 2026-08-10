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
