"""Idempotent session store: data/extracted/<source_tool>/sessions.jsonl.

Dedupe contract:
- One record per (source_tool, session_id), keyed by provenance.content_hash.
- Unchanged hash -> the EXISTING record is kept byte-for-byte (including its
  original extracted_at), so a re-run over unchanged sources produces an
  identical file. Changed hash (source file grew) -> record replaced.
- Output order is stable: (started_at, session_id).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class SessionStore:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.path = self.out_dir / "sessions.jsonl"
        self.existing: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        self.existing[rec["session_id"]] = rec
                    except (json.JSONDecodeError, KeyError):
                        continue  # rebuilt on write
        self.counts = {"new": 0, "unchanged": 0, "updated": 0}
        self._merged: dict[str, dict] = dict(self.existing)

    def upsert(self, record: dict) -> str:
        sid = record["session_id"]
        old = self.existing.get(sid)
        new_hash = record["provenance"]["content_hash"]
        if old is not None and old.get("provenance", {}).get("content_hash") == new_hash:
            self.counts["unchanged"] += 1
            return "unchanged"
        self._merged[sid] = record
        if old is None:
            self.counts["new"] += 1
            return "new"
        self.counts["updated"] += 1
        return "updated"

    def write(self) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        records = sorted(self._merged.values(),
                         key=lambda r: (r.get("started_at") or "", r["session_id"]))
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
        os.replace(tmp, self.path)
        return len(records)


class ContentStore:
    """Sidecar for --include-content rows. Never schema-validated, never
    written unless the flag is set; session records stay content-free."""

    def __init__(self, out_dir: Path) -> None:
        self.path = Path(out_dir) / "content.jsonl"
        self.rows: list[dict] = []

    def add(self, rows: list[dict]) -> None:
        self.rows.extend(rows)

    def write(self) -> int:
        if not self.rows:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        merged: list[dict] = []
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        merged.append(json.loads(line))
                        seen.add(line)
        with open(self.path, "a", encoding="utf-8") as fh:
            for row in self.rows:
                blob = json.dumps(row, sort_keys=True, separators=(",", ":"))
                if blob not in seen:
                    fh.write(blob + "\n")
                    seen.add(blob)
        return len(self.rows)
