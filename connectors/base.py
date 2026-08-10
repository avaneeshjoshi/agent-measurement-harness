"""Source-plugin interface for the extractor.

Every source tool (Claude Code, Cursor, Codex, ...) is one plugin implementing
SourcePlugin. Plugins are read-only over their sources: nothing here may write
to, move, or lock an original file. SQLite sources are snapshot-copied before
opening (see cursor.py).

The contract per plugin:

    discover() -> [RawArtifact]      what exists on this machine
    read(artifact) -> iter raw      raw parsed records, never mutated
    emit(artifact) -> [Emission]    session.schema-conforming records

Fields a tool cannot provide are ABSENT from emitted records — never defaulted,
never inferred. Prompt text and file contents are dropped at this boundary
unless include_content is set, and even then they travel in the content
sidecar, never inside the session record (the schema forbids content fields).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


CONNECTOR_VERSION = "0.3.0"
SESSION_SCHEMA_VERSION = "0.4.0"


@dataclass
class RawArtifact:
    """One discoverable unit of source material (a log file, a DB file)."""

    path: Path
    kind: str  # plugin-defined, e.g. "session_jsonl", "subagent_jsonl", "tracking_db"
    extra: dict = field(default_factory=dict)


@dataclass
class Skip:
    """A file or record that could not be processed. Logged, never fatal."""

    path: str
    reason: str


@dataclass
class Emission:
    """One emitted session record plus its (optional) content sidecar rows
    and (optional) content-free prompt-unit records (prompt_unit.schema)."""

    record: dict
    content_rows: list[dict] = field(default_factory=list)
    prompt_units: list[dict] = field(default_factory=list)


class SourcePlugin:
    """Base class. Subclasses set `name` and `log_format` and implement the
    three-method contract. `emit` may consume `read` internally."""

    name: str = "other"
    log_format: str = "other"

    def discover(self) -> list[RawArtifact]:
        raise NotImplementedError

    def read(self, artifact: RawArtifact) -> Iterator[Any]:
        raise NotImplementedError

    def emit(self, artifact: RawArtifact, include_content: bool = False) -> list[Emission]:
        raise NotImplementedError

    def finalize(self, emissions: list[Emission]) -> list[Emission]:
        """Cross-artifact post-processing hook (e.g. fork detection).
        Default: pass-through."""
        return emissions

    # -- shared helpers -----------------------------------------------------

    skips: list[Skip]

    def __init__(self) -> None:
        self.skips = []

    def skip(self, path: Path | str, reason: str) -> None:
        self.skips.append(Skip(path=str(path), reason=reason))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_json(obj: Any) -> str:
    """Deterministic hash of a JSON-serializable object (for DB-row content)."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()
