"""Idempotent session store: <data_dir>/<source_tool>/sessions.jsonl.

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


def _session_key(rec: dict) -> str:
    return rec["session_id"]


class SessionStore:
    """Also serves signal records: pass filename and a key function."""

    def __init__(self, out_dir: Path, filename: str = "sessions.jsonl",
                 key=_session_key) -> None:
        self.out_dir = Path(out_dir)
        self.path = self.out_dir / filename
        self.key = key
        self.existing: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        self.existing[self.key(rec)] = rec
                    except (json.JSONDecodeError, KeyError):
                        continue  # rebuilt on write
        self.counts = {"new": 0, "unchanged": 0, "updated": 0}
        self._merged: dict[str, dict] = dict(self.existing)

    @staticmethod
    def _same_payload(old: dict, new: dict) -> bool:
        """Record equality ignoring the per-run stamps the unchanged path
        deliberately preserves (sessions: provenance.extracted_at; signals:
        measured_at). Needed because derived fields can change under an
        unchanged source hash — e.g. fork_of is derived from the fork FAMILY,
        so a watermark-filtered incremental run followed by a full pass
        recomputes it (ADR-0011); without this check the corrected value
        would be discarded as "unchanged"."""
        def strip(r: dict) -> dict:
            out = {k: v for k, v in r.items() if k != "measured_at"}
            prov = dict(out.get("provenance") or {})
            prov.pop("extracted_at", None)
            out["provenance"] = prov
            return out
        return strip(old) == strip(new)

    def upsert(self, record: dict) -> str:
        sid = self.key(record)
        old = self.existing.get(sid)
        new_hash = record["provenance"]["content_hash"]
        # Unchanged means: same source content AND same extractor contract
        # AND the same computed record. A schema or connector bump re-emits
        # so new fields propagate; a changed derived field updates in place.
        if old is not None \
                and old.get("provenance", {}).get("content_hash") == new_hash \
                and old.get("schema_version") == record.get("schema_version") \
                and old.get("provenance", {}).get("connector_version") \
                    == record["provenance"]["connector_version"] \
                and self._same_payload(old, record):
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
                         key=lambda r: (r.get("started_at") or "", self.key(r)))
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
