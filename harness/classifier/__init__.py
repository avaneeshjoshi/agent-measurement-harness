"""harness/classifier — the visibility deliverable.

Labels units of agent work (prompt / segment / session) from CONTENT-FREE
metadata only. Consumes session records and prompt-unit records from
the extracted tree (~/.caliper/extracted, written by connectors); never reads raw logs, never reads
content sidecars — enforced by tests/test_classifier.py.

Versions (independent axes per docs/conventions.md):
- CLASSIFIER_VERSION: this ruleset
- TAXONOMY_VERSION: label meanings (0.1.0, ADR-0001/0002 draft taxonomy)
- SEGMENTER_VERSION: observable-boundary rules (0.1.0, conventions.md)
"""

CLASSIFIER_VERSION = "rules-0.2.0"  # neighborhood flow rules, ADR-0013
TAXONOMY_VERSION = "0.1.0"
SEGMENTER_VERSION = "0.1.0"
TASK_CLASS_SCHEMA_VERSION = "0.1.0"
