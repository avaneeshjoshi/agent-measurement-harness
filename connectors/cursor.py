"""Cursor plugin: the AI tracking DB plus the global state DB's composer headers.

Sources (ADR-0001 for the tracking DB; state DB validated 2026-08-09, ADR-0004):

- ~/.cursor/ai-tracking/ai-code-tracking.db
    ai_code_hashes: per-AI-line attribution rows (hash, source composer/tab/
    human, fileExtension, conversationId, model, createdAt). This is line
    attribution, NOT session shape.
    scored_commits: commit-level AI/human line splits — production_signal
    material, not session records; counted in the manifest, not emitted.
    conversation_summaries: content-level, never read (ADR-0001).
- ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
    composerHeaders: one row per composer (= conversation): composerId,
    workspaceId, createdAt, lastUpdatedAt, isSubagent, and a value JSON with
    totalLinesAdded/Removed, filesChangedCount, unifiedMode, trackedGitRepos
    (repoPath + branch names), workspaceIdentifier (fsPath), numSubComposers.
    name/subtitle/latestConversationSummary in that JSON are content-level and
    are never extracted. cursorDiskKV composerData/agentKv blobs hold full
    conversation content and are never read.

Cursor cannot provide turns or tokens: those fields are ABSENT, not faked —
these are deliberately partial records (attribution, diff totals, models).

HARD RULE: live SQLite files are never opened in place. Each DB (plus -wal/
-shm siblings) is copied to a temp snapshot first and opened read-only there.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Iterator

from .base import CONNECTOR_VERSION, SESSION_SCHEMA_VERSION, Emission, RawArtifact, SourcePlugin, sha256_file, sha256_json
from .util import iso_utc, languages_from_extensions, ms_between, now_iso, project_ref, prune


def _snapshot_db(src: Path, tmpdir: Path) -> Path:
    """Copy a SQLite DB and its -wal/-shm siblings; never touch the original."""
    dst = tmpdir / src.name
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        sib = Path(str(src) + suffix)
        if sib.exists():
            shutil.copy2(sib, Path(str(dst) + suffix))
    return dst


class CursorPlugin(SourcePlugin):
    name = "cursor"
    log_format = "cursor_state_db"

    def __init__(self, tracking_db: Path | None = None,
                 state_db: Path | None = None, salt: str = "") -> None:
        super().__init__()
        home = Path.home()
        self.tracking_db = Path(tracking_db) if tracking_db else \
            home / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
        self.state_db = Path(state_db) if state_db else \
            home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        self.salt = salt

    def discover(self) -> list[RawArtifact]:
        artifacts = []
        if self.tracking_db.is_file():
            artifacts.append(RawArtifact(path=self.tracking_db, kind="tracking_db"))
        if self.state_db.is_file():
            artifacts.append(RawArtifact(path=self.state_db, kind="state_db"))
        return artifacts

    def read(self, artifact: RawArtifact) -> Iterator[dict]:
        """Yield raw rows from a snapshot copy of the DB."""
        with tempfile.TemporaryDirectory(prefix="caliper-cursor-") as td:
            snap = _snapshot_db(artifact.path, Path(td))
            conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            try:
                if artifact.kind == "tracking_db":
                    cur = conn.execute(
                        "SELECT rowid, hash, source, fileExtension, requestId, "
                        "conversationId, timestamp, model, createdAt FROM ai_code_hashes")
                    cols = [c[0] for c in cur.description]
                    for row in cur:
                        yield {"table": "ai_code_hashes", **dict(zip(cols, row))}
                    cur = conn.execute("SELECT count(*) FROM scored_commits")
                    yield {"table": "_meta", "scored_commits": cur.fetchone()[0]}
                elif artifact.kind == "state_db":
                    cur = conn.execute(
                        "SELECT composerId, workspaceId, createdAt, lastUpdatedAt, "
                        "isArchived, isSubagent, value FROM composerHeaders")
                    cols = [c[0] for c in cur.description]
                    for row in cur:
                        yield {"table": "composerHeaders", **dict(zip(cols, row))}
            finally:
                conn.close()

    # Cursor's session picture spans two DBs, so emission happens once, over
    # both artifacts, in finalize-style: emit() on the state_db artifact does
    # the join; emit() on the tracking_db artifact returns [] (rows are
    # cached for the join and its counts land in the manifest via extra).
    def emit(self, artifact: RawArtifact, include_content: bool = False) -> list[Emission]:
        if artifact.kind == "tracking_db":
            rows = []
            for r in self.read(artifact):
                if r["table"] == "_meta":
                    artifact.extra["scored_commits"] = r["scored_commits"]
                else:
                    rows.append(r)
            artifact.extra["ai_code_hash_rows"] = len(rows)
            self._hash_rows = rows
            self._tracking_sha = sha256_file(artifact.path)
            return []

        if artifact.kind != "state_db":
            return []

        hash_rows = getattr(self, "_hash_rows", [])
        tracking_sha = getattr(self, "_tracking_sha", None)
        by_conv: dict[str, list[dict]] = {}
        for r in hash_rows:
            cid = r.get("conversationId")
            if cid:
                by_conv.setdefault(cid, []).append(r)

        state_sha = sha256_file(artifact.path)
        emissions: list[Emission] = []
        seen_conv_ids: set[str] = set()

        for row in self.read(artifact):
            if row["table"] != "composerHeaders":
                continue
            cid = row["composerId"]
            seen_conv_ids.add(cid)
            try:
                value = json.loads(row.get("value") or "{}")
            except json.JSONDecodeError:
                self.skip(f"{artifact.path}:composerHeaders:{cid}", "malformed value JSON")
                value = {}

            conv_rows = by_conv.get(cid, [])
            emissions.append(self._emit_composer(row, value, conv_rows,
                                                 state_sha, tracking_sha))

        # conversations present in the tracking DB but with no composer header:
        # emit from attribution rows alone rather than dropping them.
        for cid, conv_rows in by_conv.items():
            if cid not in seen_conv_ids:
                emissions.append(self._emit_orphan(cid, conv_rows, tracking_sha))

        return [e for e in emissions if e is not None]

    def _models_from_rows(self, conv_rows: list[dict]) -> list[dict]:
        models = sorted({r["model"] for r in conv_rows
                         if r.get("model") and r.get("source") in ("composer", "tab")})
        return [{"model_id": m} for m in models]

    def _emit_composer(self, row: dict, value: dict, conv_rows: list[dict],
                       state_sha: str, tracking_sha: str | None) -> Emission:
        cid = row["composerId"]
        started_at = iso_utc(row.get("createdAt"))
        ended_at = iso_utc(row.get("lastUpdatedAt"))
        if started_at is None:
            self.skip(f"composerHeaders:{cid}", "no createdAt")
            return None

        ws = (value.get("workspaceIdentifier") or {}).get("uri") or {}
        ws_path = ws.get("fsPath") or ws.get("path")

        branch = None
        repos = value.get("trackedGitRepos") or []
        if len(repos) == 1:
            branches = repos[0].get("branches") or []
            if len(branches) == 1:
                branch = branches[0].get("branchName")

        la = value.get("totalLinesAdded")
        lr = value.get("totalLinesRemoved")
        fc = value.get("filesChangedCount")
        diff = None
        if any(isinstance(v, int) and v > 0 for v in (la, lr, fc)):
            diff = prune({
                "files_touched": fc if isinstance(fc, int) else None,
                "lines_added": la if isinstance(la, int) else None,
                "lines_removed": lr if isinstance(lr, int) else None,
            })

        exts = {r.get("fileExtension") for r in conv_rows if r.get("fileExtension")}
        n_sub = value.get("numSubComposers")

        source_artifacts = [{"path": str(self.state_db), "sha256": state_sha, "rows": 1,
                             "note": "composerHeaders"}]
        if conv_rows:
            source_artifacts.append({"path": str(self.tracking_db),
                                     "sha256": tracking_sha,
                                     "rows": len(conv_rows),
                                     "note": "ai_code_hashes"})

        # Row-scoped content hash: whole-DB hashes change with any unrelated
        # activity; idempotency needs a hash over exactly this record's rows.
        content_hash = sha256_json({
            "header": {k: row.get(k) for k in
                       ("composerId", "workspaceId", "createdAt", "lastUpdatedAt",
                        "isArchived", "isSubagent")},
            "value": {k: value.get(k) for k in
                      ("totalLinesAdded", "totalLinesRemoved", "filesChangedCount",
                       "unifiedMode", "numSubComposers", "trackedGitRepos",
                       "workspaceIdentifier")},
            "hash_rows": sorted((r["hash"], r.get("source"), r.get("model"),
                                 r.get("fileExtension"), r.get("createdAt"))
                                for r in conv_rows),
        })

        record = prune({
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": cid,
            "source_tool": "cursor",
            "provenance": {
                "log_format": "cursor_state_db",
                "connector_version": CONNECTOR_VERSION,
                "extracted_at": now_iso(),
                "content_hash": content_hash,
                "source_artifacts": source_artifacts,
            },
            "project_ref": project_ref(self.salt, ws_path) if ws_path else None,
            "git_branch": branch,
            "started_at": started_at,
            "ended_at": ended_at,
            "end_observed": False,
            "wall_clock_ms": ms_between(started_at, ended_at),
            "models": self._models_from_rows(conv_rows) or None,
            "diff_stats": diff,
            "languages": languages_from_extensions(exts) or None,
            "subagents": prune({
                "count": n_sub if isinstance(n_sub, int) else None,
                "is_sidechain": bool(row.get("isSubagent")) or None,
            }) or None,
            # isSubagent composers are agent-spawned; no marker for the rest
            "automated": True if row.get("isSubagent") else None,
        })
        return Emission(record=record)

    def _emit_orphan(self, cid: str, conv_rows: list[dict],
                     tracking_sha: str | None) -> Emission:
        times = sorted(t for t in (r.get("createdAt") for r in conv_rows) if t)
        started_at = iso_utc(times[0]) if times else None
        if started_at is None:
            self.skip(f"ai_code_hashes:{cid}", "no timestamps on attribution rows")
            return None
        ended_at = iso_utc(times[-1]) if times else None
        exts = {r.get("fileExtension") for r in conv_rows if r.get("fileExtension")}

        content_hash = sha256_json({
            "hash_rows": sorted((r["hash"], r.get("source"), r.get("model"),
                                 r.get("fileExtension"), r.get("createdAt"))
                                for r in conv_rows),
        })
        record = prune({
            "schema_version": SESSION_SCHEMA_VERSION,
            "session_id": cid,
            "source_tool": "cursor",
            "provenance": {
                "log_format": "cursor_tracking_db",
                "connector_version": CONNECTOR_VERSION,
                "extracted_at": now_iso(),
                "content_hash": content_hash,
                "source_artifacts": [{"path": str(self.tracking_db),
                                      "sha256": tracking_sha,
                                      "rows": len(conv_rows),
                                      "note": "ai_code_hashes only; no composer header"}],
            },
            "started_at": started_at,
            "ended_at": ended_at,
            "end_observed": False,
            "wall_clock_ms": ms_between(started_at, ended_at),
            "models": self._models_from_rows(conv_rows) or None,
            "languages": languages_from_extensions(exts) or None,
        })
        return Emission(record=record)
