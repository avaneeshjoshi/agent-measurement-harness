"""Trace layer v0: the first trace_event producers (ADR-0019).

Three edge types, in descending evidence strength:

- commit -> ticket   ticket key found in the commit message
                     (explicit_id_reference, known)
- session -> ticket  ticket key found in the session's git_branch
                     (branch_name_match, inferred)
- session -> commit  file-ref overlap between the files a session edited
                     (prompt_unit.files_edited) and the files a commit
                     changed (git numstat), scoped by project_ref join.
                     Time is a TIEBREAKER only — never the mechanism —
                     and there is deliberately no clock-window constant.

Chunked-commit reality (industry discovery, ADR-0019): enterprise work
lands as many small commits per feature, so one session legitimately maps
to many commits. Edges are therefore emitted per COMMIT, and specificity
is commit-side containment: a small chunk fully contained in the
session's edited set scores high even when the session touched far more.

Read-only over sources: git access is `git log` / `rev-parse` only (via
GitHistoryConnector's _git); session and prompt-unit files are read, never
written. The only write is <data_dir>/trace/trace_events.jsonl plus a run
manifest.

Absence is absence: a commit with no ticket key, or a session with no
matching commit, produces NO edge — never a placeholder record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

TRACER_VERSION = "tracer-0.1.0"
SCHEMA_VERSION = "0.2.0"

# Ticket keys: PROJECT-123 style. Project key starts with a letter,
# 2-10 chars, then 1-6 digits. The blocklist removes prefixes that match
# the shape but are not ticket systems (versioned here; extended only
# with an ADR note — ADR-0019).
_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-([0-9]{1,6})\b")
TICKET_PREFIX_BLOCKLIST = frozenset({
    "UTF", "ISO", "SHA", "MD", "CRC", "AES", "RSA", "TLS", "SSL",
    "RFC", "CVE", "PEP", "ADR", "HTTP", "HTTP2", "API", "ID", "UUID",
    "GUID", "CI", "RC", "V", "X", "UTC", "GMT", "ANSI", "IEEE",
    "OAUTH", "BASE", "ES", "IPV",
})


def ticket_keys(text: str) -> list[str]:
    """Ordered, de-duplicated ticket keys in `text`, blocklist applied."""
    seen: list[str] = []
    for prefix, num in _TICKET_RE.findall(text or ""):
        if prefix in TICKET_PREFIX_BLOCKLIST:
            continue
        key = f"{prefix}-{num}"
        if key not in seen:
            seen.append(key)
    return seen


def _iso_to_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _edge(trace_id: str, from_node: dict, to_node: dict, method: str,
          confidence_class: str, confidence: float | None,
          evidence: str | None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": trace_id,
        "created_at": _now_iso(),
        "tracer_version": TRACER_VERSION,
        "from_node": from_node,
        "to_node": to_node,
        "link": {"method": method, "confidence_class": confidence_class,
                 "confidence": confidence, "evidence": evidence},
        "value_dimensions": None,
    }


class TraceStore:
    """Idempotent edge store: <data_dir>/trace/trace_events.jsonl.

    One record per edge identity (trace_id, from, to, method). A re-run
    that recomputes an identical edge keeps the EXISTING record byte-for-
    byte — created_at is the only per-run stamp and is ignored for
    equality — so unchanged inputs produce an identical file."""

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.path = self.out_dir / "trace_events.jsonl"
        self.existing: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        self.existing[self._key(rec)] = rec
                    except (json.JSONDecodeError, KeyError):
                        continue
        self.counts = {"new": 0, "unchanged": 0, "updated": 0}
        self._merged: dict[str, dict] = dict(self.existing)

    @staticmethod
    def _key(rec: dict) -> str:
        f, t = rec["from_node"], rec["to_node"]
        return "|".join([rec["trace_id"], f["kind"], f["id"],
                         t["kind"], t["id"], rec["link"]["method"]])

    @staticmethod
    def _same(old: dict, new: dict) -> bool:
        strip = lambda r: {k: v for k, v in r.items() if k != "created_at"}
        return strip(old) == strip(new)

    def upsert(self, rec: dict) -> str:
        k = self._key(rec)
        old = self.existing.get(k)
        if old is not None and self._same(old, rec):
            self.counts["unchanged"] += 1
            return "unchanged"
        self._merged[k] = rec
        self.counts["new" if old is None else "updated"] += 1
        return "new" if old is None else "updated"

    def write(self) -> int:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        records = sorted(self._merged.values(), key=self._key)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, sort_keys=True,
                                    separators=(",", ":")) + "\n")
        os.replace(tmp, self.path)
        return len(records)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _score_overlap(session_refs: set[str], commit_refs: set[str],
                   df: dict[str, int]) -> tuple[str, float] | None:
    """(confidence_class, confidence) for a session->commit candidate, or
    None when the overlap does not clear the floor. Specificity scales
    confidence (ADR-0019):

    - full containment (every changed file was edited in the session),
      >=2 files: inferred, 0.85
    - full containment, single file: inferred 0.6 if that file appears in
      only this one commit (df==1), else speculative 0.25 — 'both touched
      main.py in a small repo' is weak evidence
    - partial containment >= 0.5: speculative, 0.4 * containment
    - below 0.5: no edge (absence, not a weak record)
    """
    overlap = session_refs & commit_refs
    if not overlap or not commit_refs:
        return None
    containment = len(overlap) / len(commit_refs)
    if containment == 1.0:
        if len(commit_refs) >= 2:
            return ("inferred", 0.85)
        ref = next(iter(commit_refs))
        if df.get(ref, 0) <= 1:
            return ("inferred", 0.6)
        return ("speculative", 0.25)
    if containment >= 0.5:
        return ("speculative", round(0.4 * containment, 3))
    return None


def run_trace(data_dir: Path, connector=None, validator=None) -> dict:
    """Produce trace edges over extracted data + discovered repos.
    Returns the chain-rate summary (the A3-minimal figures, also written
    as a run manifest). `connector` lets tests inject a
    GitHistoryConnector pointed at fixture roots; `validator` (a
    jsonschema validator) rejects invalid edges before they are stored."""
    import uuid

    from caliper.cli.paths import salt_path
    from caliper.connectors.git_history import GitHistoryConnector, _git
    from caliper.connectors.util import file_refs, load_salt, project_ref

    salt = load_salt(salt_path(data_dir))
    conn = connector or GitHistoryConnector(salt=salt)
    repos, cwd_to_root = conn.discover_repos()

    # session-side inputs: sessions + the file refs their prompt units carry
    tools = ("claude_code", "codex", "cursor")
    sessions: dict[str, dict] = {}
    for tool in tools:
        for r in _jsonl(data_dir / tool / "sessions.jsonl"):
            sessions[r["session_id"]] = r
    unit_refs: dict[str, set[str]] = {}
    for tool in tools:
        for u in _jsonl(data_dir / tool / "prompt_units.jsonl"):
            refs = {f["file_ref"] for f in (u.get("window", {})
                                            .get("files_edited") or [])}
            if refs:
                unit_refs.setdefault(u["session_id"], set()).update(refs)

    # project_ref -> repo root, for both cwd and root spellings
    pref_to_root: dict[str, str] = {}
    for cwd, root in cwd_to_root.items():
        pref_to_root[project_ref(salt, cwd)] = root
        pref_to_root[project_ref(salt, root)] = root
    sessions_by_root: dict[str, list[dict]] = {}
    for s in sessions.values():
        root = pref_to_root.get(s.get("project_ref") or "")
        if root:
            sessions_by_root.setdefault(root, []).append(s)

    store = TraceStore(data_dir / "trace")
    summary = {
        "invalid": 0,
        "tracer_version": TRACER_VERSION,
        "repos": len(repos),
        "commits_analyzed": 0,
        "commits_with_ticket_edge": 0,
        "sessions_in_repo_scope": sum(len(v) for v in sessions_by_root.values()),
        "sessions_total": len(sessions),
        "sessions_with_commit_edge": 0,
        "session_commit_edges_by_class": {"inferred": 0, "speculative": 0},
        "sessions_with_branch_ticket_edge": 0,
        "edges": 0,
    }

    def put(rec: dict) -> None:
        if validator is not None:
            errors = list(validator.iter_errors(rec))
            if errors:
                summary["invalid"] += 1
                return
        store.upsert(rec)

    # session -> ticket via branch name (repo-scope independent)
    for s in sessions.values():
        keys = ticket_keys(s.get("git_branch") or "")
        if keys:
            summary["sessions_with_branch_ticket_edge"] += 1
        for key in keys:
            put(_edge(
                f"s:{s['session_id']}",
                {"kind": "session", "id": s["session_id"],
                 "source_system": s.get("source_tool")},
                {"kind": "ticket", "id": key, "source_system": None},
                "branch_name_match", "inferred", None,
                f"{key} in session git_branch"))

    sessions_with_commit_edge: set[str] = set()

    for root in sorted(repos):
        rp = Path(root)
        head = _git(rp, "rev-parse", "HEAD")
        if not head or not head.strip():
            continue
        repo_ref = "r_" + hashlib.sha256(
            (salt + "|" + root).encode()).hexdigest()[:16]

        log = _git(rp, "log", "HEAD", "--no-merges",
                   "--format=%x1e%H%x1f%ct%x1f%B") or ""
        commits: list[dict] = []
        for block in log.split("\x1e"):
            if not block.strip():
                continue
            sha, ct, body = block.split("\x1f", 2)
            commits.append({"sha": sha.strip(), "time": int(ct), "body": body})

        numstat = _git(rp, "log", "HEAD", "--no-merges",
                       "--format=%x1e%H", "--numstat") or ""
        paths_by_sha: dict[str, list[str]] = {}
        for block in numstat.split("\x1e"):
            lines = [l for l in block.splitlines() if l.strip()]
            if not lines:
                continue
            sha = lines[0].strip()
            paths = []
            for l in lines[1:]:
                parts = l.split("\t")
                if len(parts) == 3:
                    paths.append(parts[2])
            paths_by_sha[sha] = paths

        # commit-side refs: reconstruct the absolute path the session-side
        # hash used (numstat is repo-relative; sessions hash absolute —
        # the ref-join contract, tested in tests/test_trace.py)
        refs_by_sha: dict[str, set[str]] = {}
        df: dict[str, int] = {}
        for sha, paths in paths_by_sha.items():
            refs = {file_refs(salt, f"{root}/{rel}")["file_ref"]
                    for rel in paths}
            refs_by_sha[sha] = refs
            for ref in refs:
                df[ref] = df.get(ref, 0) + 1

        candidates = [s for s in sessions_by_root.get(root, [])
                      if unit_refs.get(s["session_id"])]

        for c in commits:
            summary["commits_analyzed"] += 1
            trace_id = f"{repo_ref}:{c['sha']}"

            # commit -> ticket
            keys = ticket_keys(c["body"])
            if keys:
                summary["commits_with_ticket_edge"] += 1
            for key in keys:
                put(_edge(
                    trace_id,
                    {"kind": "commit", "id": c["sha"],
                     "source_system": "git"},
                    {"kind": "ticket", "id": key, "source_system": None},
                    "explicit_id_reference", "known", None,
                    f"{key} in commit message"))

            # session -> commit: file overlap, causality-constrained
            # (a session cannot produce a commit authored before it began
            # — a direction check, not a clock window)
            commit_refs = refs_by_sha.get(c["sha"]) or set()
            if not commit_refs:
                continue
            scored: list[tuple] = []
            for s in candidates:
                started = _iso_to_ts(s.get("started_at"))
                if started is None or started > c["time"]:
                    continue
                srefs = unit_refs[s["session_id"]]
                result = _score_overlap(srefs, commit_refs, df)
                if result is None:
                    continue
                cls, conf = result
                overlap_n = len(srefs & commit_refs)
                ended = _iso_to_ts(s.get("ended_at")) or started
                gap = abs(c["time"] - ended)
                scored.append((0 if cls == "inferred" else 1, -conf,
                               -overlap_n, gap, s["session_id"], cls, conf))
            if not scored:
                continue
            scored.sort()
            rank0, _nc, _no, _gap, sid, cls, conf = scored[0]
            overlap_n = len(unit_refs[sid] & commit_refs)
            evidence = (f"{overlap_n}/{len(commit_refs)} changed files "
                        f"edited in session; {len(scored)} candidate "
                        f"session(s), closest-preceding chosen"
                        if len(scored) > 1 else
                        f"{overlap_n}/{len(commit_refs)} changed files "
                        f"edited in session")
            put(_edge(
                trace_id,
                {"kind": "session", "id": sid,
                 "source_system": sessions[sid].get("source_tool")},
                {"kind": "commit", "id": c["sha"], "source_system": "git"},
                "file_overlap", cls, conf, evidence))
            sessions_with_commit_edge.add(sid)
            summary["session_commit_edges_by_class"][cls] += 1

    summary["sessions_with_commit_edge"] = len(sessions_with_commit_edge)
    summary["edges"] = store.write()
    summary["store_counts"] = dict(store.counts)

    run_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
              + "-" + uuid.uuid4().hex[:8])
    manifest_dir = data_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "kind": "trace",
                    "finished_at": _now_iso(), **summary}, indent=2))
    return summary
