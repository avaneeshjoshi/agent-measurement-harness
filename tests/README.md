# tests/

The test suite for the harness, mirroring the `harness/` subpackage layout, plus the contract checks that keep the repo honest.

## What goes here

- Unit tests per harness subpackage (`test_classifier/`, `test_replay/`, `test_judge/`, `test_signals/`, `test_trace/`, `test_routing/`) and per connector.
- **Schema validation**: every fixture in `data/fixtures/` validates against its schema in `schemas/`; a component whose output stops validating fails CI. This is the enforcement mechanism for the "components communicate through schemas" rule.
- Pipeline smoke test: synthetic sessions in → classified → replayed (stub models) → traced → policy out, end to end.
- Safeguard tests: the judge's position-swapping, the 80% agreement gate, the no-individual-aggregation rule in the dashboard's data layer — the glass-box promises, tested.

## Rules

- Tests run on fixtures and synthetic data only — nothing here calls external APIs or paid models; model calls are stubbed.
