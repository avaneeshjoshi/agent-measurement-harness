"""Replay harness units: price-sheet math and eval_result record shape.

The scorer's end-to-end behavior (null agent fails hidden tests, oracle agent
passes) is verified against the real mined repo at run time — it needs a
cloned Java repo and Maven, so it is not a unit test here.
"""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from harness.replay.runner import EVAL_SCHEMA_VERSION, load_pricing, price_usage
from tests.conftest import REPO

EVAL_SCHEMA = REPO / "schemas" / "eval_result.schema.json"


def test_price_usage_covers_all_buckets():
    pricing = load_pricing()
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_read_input_tokens": 1_000_000,
             "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000,
                                "ephemeral_1h_input_tokens": 1_000_000}}
    # haiku: 1 + 5 + 0.1 + 1.25 + 2.0
    assert price_usage(usage, "claude-haiku-4-5", pricing) == 9.35
    # fable: 10 + 50 + 1 + 12.5 + 20
    assert price_usage(usage, "claude-fable-5", pricing) == 93.5


def test_price_usage_defaults_to_1h_cache_write():
    pricing = load_pricing()
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 1_000_000}
    # no TTL breakdown -> 1h assumed (documented in the sheet)
    assert price_usage(usage, "claude-haiku-4-5", pricing) == 2.0
    assert price_usage(usage, "unknown-model", pricing) is None


def test_eval_record_shape_validates():
    validator = Draft202012Validator(json.loads(EVAL_SCHEMA.read_text()))
    record = {
        "schema_version": EVAL_SCHEMA_VERSION,
        "run_id": "r1",
        "created_at": "2026-08-09T12:00:00.000Z",
        "task_ref": {"task_id": "t1", "source_session_id": None,
                     "task_class": {"task_type": "single_file_bug_fix",
                                    "taxonomy_version": "0.1.0-provisional",
                                    "classification_confidence": None}},
        "cell": {"model_id": "claude-haiku-4-5", "model_tier": "small",
                 "skill_attached": False, "skill_id": None, "effort": None},
        "replay_config": {"harness_version": "replay-0.1.0", "n_runs": 1,
                          "seed": None, "sandbox": "local",
                          "prompt_template_version": "p1"},
        "tracks": {"objective": {"runs": [{
            "run_index": 0, "tests_passed": 58, "tests_total": 59,
            "lint": "not_applicable", "type_check": "not_applicable",
            "build": "pass", "completed": True}],
            "aggregate": {"metric": "hidden_test_pass_rate",
                          "value": 58 / 59, "n": 1, "ci": None}}},
        "cost": {"tokens_input": 100, "tokens_output": 200,
                 "tokens_cache_read": 300, "tokens_cache_creation": 400,
                 "cost_usd_estimate": 0.01, "cli_reported_cost_usd": 0.011,
                 "pricing_source": "sheet", "pricing_as_of": "2026-08-09"},
    }
    validator.validate(record)
