"""Caliper connectors: source plugins for the extractor.

One plugin per harness (ADR-0003). CLI names use dashes (claude-code);
source_tool values and module names use underscores (claude_code).
"""

from __future__ import annotations

from .base import CONNECTOR_VERSION, Emission, RawArtifact, Skip, SourcePlugin
from .claude_code import ClaudeCodePlugin
from .codex import CodexPlugin
from .cursor import CursorPlugin

PLUGINS = {
    "claude_code": ClaudeCodePlugin,
    "cursor": CursorPlugin,
    "codex": CodexPlugin,
}


def normalize_source_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


__all__ = [
    "CONNECTOR_VERSION", "Emission", "RawArtifact", "Skip", "SourcePlugin",
    "ClaudeCodePlugin", "CursorPlugin", "CodexPlugin",
    "PLUGINS", "normalize_source_name",
]
