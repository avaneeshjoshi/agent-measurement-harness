# unit-comparison-2026-08-07

First calibration set: 83 per-prompt + 14 per-segment hand labels over 8 real local Claude Code sessions, produced for the classification-unit comparison in [ADR-0002](../../../docs/decisions/0002-classification-unit-comparison.md).

- Records conform to `schemas/task_class.schema.json` v0.1.0 (validated at write time).
- `classifier_version: human-calibration-2026-08-07` — labels were assigned by reading prompt text + activity features. Content-free: these records contain only session ids, turn ranges, and labels; no prompt text.
- Segments per `segmenter_version: 0.1.0` (rules in `docs/conventions.md`). Segment labels via rule `segment-dominant-prompt-label-v0` — known to erase embedded minority classes (ADR-0002 finding 1); treat as baseline, not truth.
- Solo-developer data: validates the instrument, not enterprise task distributions.

The future content-free classifier is validated against `prompt_units.jsonl`.
