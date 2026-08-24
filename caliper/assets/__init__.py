"""Packaged runtime assets (ADR-0014).

At build time the repo's top-level schemas/ is force-included here
(caliper/assets/schemas/) so a wheel install carries the record contracts.
In a source checkout this package holds only this file — the checkout's
schemas/ is the single source of truth and cli.paths.schema_path prefers it.
"""
