# tests/

The test suite for the harness, mirroring the `harness/` subpackage layout, plus the contract checks that keep the repo honest.

## What's here

Flat test files per built component, run on every push and PR (`.github/workflows/ci.yml`): `test_extractor.py` (read-only sources, idempotency, content boundary, gitignore enforcement, per-format shapes), `test_git_signals.py` (survival/rework/revert/attribution on fixture repos), `test_classifier.py` + `test_classifier_segmenter.py` (content-free enforcement, rule behavior, calibration-boundary reproduction), `test_replay.py` (pricing, record shape), `test_report.py` (absent renders "not recorded" never zero, no raw paths). Emitted records validate against `schemas/` inside these tests — that is the enforcement mechanism for the "components communicate through schemas" rule.

## Planned (as the matching components get built)

- Tests per remaining subpackage (`test_judge`, `test_trace`, `test_routing`) and a pipeline smoke test: synthetic sessions in → classified → replayed (stub models) → traced → policy out.
- Safeguard tests for the glass-box promises: the judge's position-swapping, the 80% agreement gate, the no-individual-aggregation rule in the dashboard's data layer.

## Rules

- Tests run on fixtures and synthetic data only — nothing here calls external APIs or paid models; model calls are stubbed.
