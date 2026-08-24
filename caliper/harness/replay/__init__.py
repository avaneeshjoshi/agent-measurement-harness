"""harness/replay — the controlled-evaluation engine (v0: Java/Maven repos).

v0 scope (first eval slice, 2026-08-09): mine real bug-fix tasks from a public
Java repo's history, replay each from the pre-fix state across model tiers
under identical conditions, score by hidden-test pass rate with a compile
floor, emit eval_result records.
"""

HARNESS_VERSION = "replay-0.1.0"
