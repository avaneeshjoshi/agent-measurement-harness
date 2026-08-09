"""Git-history connector: production signals from LOCAL repos, read-only.

Computes, per commit reachable from HEAD (production_signal.schema 0.2.0):

- survival at 30/60/90 days: lines the commit added that are still attributed
  to it by `git blame` at a snapshot commit taken at authored_time + horizon.
  A commit younger than a horizon is `not_yet_measurable`; a commit that added
  no lines (merges excluded, pure deletions, binary) is `unmeasurable`.
- rework within 14 days: lines added that are NO LONGER attributed to the
  commit at +14d — i.e. changed OR deleted; the metric is honest about that
  conflation (blame cannot distinguish them), see ADR-0006.
- revert linkage: only explicit `This reverts commit <sha>` markers
  (`revert_detection: git_revert_marker`) — no content-similarity guessing.
- review friction: local git shows merge/squash PR patterns
  ("Merge pull request #N", subject "(#N)") -> pr_number; iteration counts
  need a forge API and stay null. GitHub is NOT called.
- AI attribution, never from code content:
  * Cursor's ai-code-tracking.db `scored_commits` (vendor_tracking_db):
    known when tab/composer/human line counts are populated, partial when the
    row exists but counts are null;
  * Co-Authored-By trailers naming an AI tool (self_report) -> partial;
  * otherwise unknown/none.

Repo discovery starts from what the extracted sessions reference: candidate
working directories are re-read from the same sources the session extractor
uses (Claude Code cwd, Codex session_meta.cwd, Cursor workspace fsPath +
trackedGitRepos), resolved to git toplevels, deduplicated. Hashing each
candidate cwd with the extraction salt reproduces the sessions' project_ref,
which is what joins session records to repos (ADR-0005 §3).

Read-only guarantee: only `git rev-parse / log / rev-list / blame /
merge-base` are executed; the Cursor DB is snapshot-copied (cursor.py rule).

Known v0 limitations (documented, not patched): blame does not follow renames
(a renamed file counts as non-surviving); survival is measured against HEAD's
lineage only; rework lines include deletions.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .base import sha256_json
from .cursor import _snapshot_db
from .util import now_iso, project_ref

GIT_CONNECTOR_VERSION = "0.1.0"
SIGNAL_SCHEMA_VERSION = "0.2.0"

_AI_TRAILER_RE = re.compile(
    r"co-authored-by:.*\b(claude|codex|cursor|copilot|gpt|openai|anthropic|"
    r"devin|aider|ai)\b", re.IGNORECASE)
_REVERT_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})")
_PR_MERGE_RE = re.compile(r"^Merge pull request #(\d+)")
_PR_SQUASH_RE = re.compile(r"\(#(\d+)\)\s*$")

_HORIZONS = (30, 60, 90)
_REWORK_WINDOW_DAYS = 14
_DAY_S = 86400


def _git(root: Path, *args: str, timeout: int = 120) -> str | None:
    """Run a read-only git command; None on failure (caller logs)."""
    try:
        res = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return res.stdout if res.returncode == 0 else None


class GitHistoryConnector:
    def __init__(self, claude_root: Path | None = None,
                 codex_root: Path | None = None,
                 cursor_tracking_db: Path | None = None,
                 cursor_state_db: Path | None = None,
                 extra_repos: list[Path] | None = None,
                 salt: str = "", now: datetime | None = None,
                 max_commits: int = 1000) -> None:
        home = Path.home()
        self.claude_root = Path(claude_root) if claude_root else home / ".claude" / "projects"
        self.codex_root = Path(codex_root) if codex_root else home / ".codex" / "sessions"
        self.cursor_tracking_db = Path(cursor_tracking_db) if cursor_tracking_db \
            else home / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
        self.cursor_state_db = Path(cursor_state_db) if cursor_state_db \
            else home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        self.extra_repos = [Path(p) for p in (extra_repos or [])]
        self.salt = salt
        self.now = now or datetime.now(timezone.utc)
        self.max_commits = max_commits
        self.skips: list[dict] = []
        self._blame_cache: dict[tuple[str, str], Counter] = {}
        self._scored_commits: dict[str, dict] | None = None

    def skip(self, path, reason: str) -> None:
        self.skips.append({"path": str(path), "reason": reason})

    # ---------------------------------------------------------- discovery

    def collect_candidate_paths(self) -> dict[str, set[str]]:
        """Working directories referenced by each tool's logs (raw paths stay
        inside the connector; only refs leave)."""
        cands: dict[str, set[str]] = {}

        def add(path, tool):
            if path:
                cands.setdefault(str(path), set()).add(tool)

        if self.claude_root.is_dir():
            for f in self.claude_root.glob("*/*.jsonl"):
                try:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            try:
                                d = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if d.get("cwd"):
                                add(d["cwd"], "claude_code")
                                break
                except OSError as exc:
                    self.skip(f, f"unreadable: {exc!r}")

        if self.codex_root.is_dir():
            for f in self.codex_root.glob("*/*/*/rollout-*.jsonl"):
                try:
                    with open(f, encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            try:
                                d = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            p = d.get("payload") or {}
                            if d.get("type") == "session_meta" and p.get("cwd"):
                                add(p["cwd"], "codex")
                                break
                except OSError as exc:
                    self.skip(f, f"unreadable: {exc!r}")

        if self.cursor_state_db.is_file():
            with tempfile.TemporaryDirectory(prefix="caliper-git-") as td:
                snap = _snapshot_db(self.cursor_state_db, Path(td))
                conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
                try:
                    for (v,) in conn.execute("SELECT value FROM composerHeaders"):
                        try:
                            val = json.loads(v or "{}")
                        except json.JSONDecodeError:
                            continue
                        ws = (val.get("workspaceIdentifier") or {}).get("uri") or {}
                        add(ws.get("fsPath"), "cursor")
                        for repo in val.get("trackedGitRepos") or []:
                            add(repo.get("repoPath"), "cursor")
                except sqlite3.Error as exc:
                    self.skip(self.cursor_state_db, f"state db read failed: {exc!r}")
                finally:
                    conn.close()

        for p in self.extra_repos:
            add(p, "manual")
        return cands

    def discover_repos(self):
        """Resolve candidates to git toplevels. Returns
        (repos: {root: {tools}}, cwd_to_root: {cwd: root})."""
        cands = self.collect_candidate_paths()
        repos: dict[str, set[str]] = {}
        cwd_to_root: dict[str, str] = {}
        for cwd, tools in sorted(cands.items()):
            if not Path(cwd).is_dir():
                self.skip(cwd, "directory no longer exists")
                continue
            out = _git(Path(cwd), "rev-parse", "--show-toplevel")
            if not out or not out.strip():
                self.skip(cwd, "not a git repository")
                continue
            root = out.strip()
            repos.setdefault(root, set()).update(tools)
            cwd_to_root[cwd] = root
        return repos, cwd_to_root

    # ------------------------------------------------------- cursor scores

    def _load_scored_commits(self) -> dict[str, dict]:
        if self._scored_commits is not None:
            return self._scored_commits
        scores: dict[str, dict] = {}
        if self.cursor_tracking_db.is_file():
            with tempfile.TemporaryDirectory(prefix="caliper-git-") as td:
                snap = _snapshot_db(self.cursor_tracking_db, Path(td))
                conn = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
                try:
                    cur = conn.execute(
                        "SELECT commitHash, tabLinesAdded, composerLinesAdded, "
                        "humanLinesAdded, v1AiPercentage, v2AiPercentage "
                        "FROM scored_commits")
                    for sha, tab, comp, human, v1, v2 in cur:
                        scores[sha] = {"tab": tab, "composer": comp,
                                       "human": human, "v1": v1, "v2": v2}
                except sqlite3.Error as exc:
                    self.skip(self.cursor_tracking_db, f"scored_commits read failed: {exc!r}")
                finally:
                    conn.close()
        self._scored_commits = scores
        return scores

    # ----------------------------------------------------------- analysis

    def _snapshot_at(self, root: Path, ts: int) -> str | None:
        out = _git(root, "rev-list", "-1", f"--before={ts}", "HEAD")
        return out.strip() if out and out.strip() else None

    def _blame_counts(self, root: Path, snapshot: str, path: str) -> Counter:
        key = (snapshot, path)
        cached = self._blame_cache.get(key)
        if cached is not None:
            return cached
        counts: Counter = Counter()
        out = _git(root, "blame", "--line-porcelain", snapshot, "--", path)
        if out:
            for line in out.splitlines():
                # line-porcelain: header lines start '<sha40> <orig> <final>'
                if len(line) > 40 and line[40] == " " and not line.startswith("\t"):
                    sha = line[:40]
                    if all(c in "0123456789abcdef" for c in sha):
                        counts[sha] += 1
        self._blame_cache[key] = counts
        return counts

    def _surviving_lines(self, root: Path, commit: str, files: list[str],
                         snapshot: str) -> int:
        return sum(self._blame_counts(root, snapshot, f)[commit] for f in files)

    def analyze_repo(self, root_str: str) -> list[dict]:
        root = Path(root_str)
        head_out = _git(root, "rev-parse", "HEAD")
        if not head_out:
            self.skip(root, "cannot resolve HEAD (empty or corrupt repo)")
            return []
        head = head_out.strip()
        repo_ref = "r_" + hashlib.sha256(
            (self.salt + "|" + root_str).encode()).hexdigest()[:16]

        # one pass for shas/times/subject+body(for reverts)+trailer scan
        log = _git(root, "log", "HEAD", "--no-merges",
                   "--format=%x1e%H%x1f%ct%x1f%B")
        if log is None:
            self.skip(root, "git log failed")
            return []
        commits: list[dict] = []
        reverted_by: dict[str, str] = {}
        for block in log.split("\x1e"):
            if not block.strip():
                continue
            sha, ct, body = block.split("\x1f", 2)
            commits.append({"sha": sha.strip(), "time": int(ct), "body": body})
            for target in _REVERT_RE.findall(body):
                reverted_by.setdefault(target, sha.strip())
        commits.sort(key=lambda c: c["time"])
        truncated = 0
        if len(commits) > self.max_commits:
            truncated = len(commits) - self.max_commits
            commits = commits[-self.max_commits:]
            self.skip(root, f"truncated to newest {self.max_commits} commits "
                            f"({truncated} older commits not analyzed)")

        # numstat per commit (insertions per file)
        numstat = _git(root, "log", "HEAD", "--no-merges",
                       "--format=%x1e%H", "--numstat") or ""
        files_by_sha: dict[str, dict[str, int]] = {}
        for block in numstat.split("\x1e"):
            lines = [l for l in block.splitlines() if l.strip()]
            if not lines:
                continue
            sha = lines[0].strip()
            fmap: dict[str, int] = {}
            deleted = 0
            for l in lines[1:]:
                parts = l.split("\t")
                if len(parts) == 3 and parts[0] != "-":  # '-' = binary
                    try:
                        fmap[parts[2]] = int(parts[0])
                        deleted += int(parts[1])
                    except ValueError:
                        continue
            files_by_sha[sha] = {"files": fmap, "deleted": deleted}

        # PR patterns: merge commits map their second-parent commits to a PR
        pr_by_sha: dict[str, int] = {}
        merges = _git(root, "log", "HEAD", "--merges", "--format=%H%x1f%P%x1f%s") or ""
        for line in merges.splitlines():
            if not line.strip():
                continue
            sha, parents, subject = line.split("\x1f", 2)
            m = _PR_MERGE_RE.match(subject)
            if m:
                pr = int(m.group(1))
                ps = parents.split()
                if len(ps) == 2:
                    merged = _git(root, "rev-list", f"{ps[0]}..{ps[1]}") or ""
                    for msha in merged.split():
                        pr_by_sha[msha] = pr

        scores = self._load_scored_commits()
        now_ts = int(self.now.timestamp())
        records: list[dict] = []

        for c in commits:
            sha = c["sha"]
            entry = files_by_sha.get(sha, {"files": {}, "deleted": 0})
            fmap = entry["files"]
            files = [f for f, ins in fmap.items() if ins > 0]
            lines_added = sum(fmap.values())
            lines_deleted = entry["deleted"]
            subject = c["body"].splitlines()[0] if c["body"] else ""

            # survival per horizon
            survival = []
            for h in _HORIZONS:
                target_ts = c["time"] + h * _DAY_S
                if lines_added == 0:
                    survival.append({"horizon_days": h, "status": "unmeasurable",
                                     "lines_surviving": None,
                                     "lines_original": 0,
                                     "surviving_fraction": None})
                    continue
                if now_ts < target_ts:
                    survival.append({"horizon_days": h,
                                     "status": "not_yet_measurable",
                                     "lines_surviving": None,
                                     "lines_original": lines_added,
                                     "surviving_fraction": None})
                    continue
                snap = self._snapshot_at(root, target_ts)
                if not snap:
                    survival.append({"horizon_days": h, "status": "unmeasurable",
                                     "lines_surviving": None,
                                     "lines_original": lines_added,
                                     "surviving_fraction": None})
                    continue
                surviving = self._surviving_lines(root, sha, files, snap)
                survival.append({
                    "horizon_days": h, "status": "measured",
                    "lines_surviving": surviving,
                    "lines_original": lines_added,
                    "surviving_fraction": round(surviving / lines_added, 4),
                })

            # rework within 14d (changed-or-deleted; see module docstring)
            rework_target = c["time"] + _REWORK_WINDOW_DAYS * _DAY_S
            if lines_added == 0:
                rework = None
            elif now_ts < rework_target:
                rework = {"window_days": _REWORK_WINDOW_DAYS,
                          "status": "not_yet_measurable",
                          "occurred": None, "lines_reworked": None,
                          "rework_commit_shas": []}
            else:
                snap14 = self._snapshot_at(root, rework_target)
                surviving14 = self._surviving_lines(root, sha, files, snap14) \
                    if snap14 else lines_added
                reworked = max(0, lines_added - surviving14)
                shas: list[str] = []
                if reworked and files:
                    out = _git(root, "log", "HEAD", "--no-merges", "--format=%H",
                               f"--since={c['time'] + 1}",
                               f"--until={rework_target}", "--", *files) or ""
                    shas = [s for s in out.split() if s != sha][:20]
                rework = {"window_days": _REWORK_WINDOW_DAYS, "status": "measured",
                          "occurred": reworked > 0, "lines_reworked": reworked,
                          "rework_commit_shas": shas}

            # attribution — evidence only, never content
            score = scores.get(sha)
            trailer_ai = bool(_AI_TRAILER_RE.search(c["body"]))
            if score is not None and score["tab"] is not None \
                    and score["composer"] is not None and score["human"] is not None:
                ai_lines = int(score["tab"]) + int(score["composer"])
                human_lines = int(score["human"])
                denom = ai_lines + human_lines
                attribution = {
                    "status": "known", "evidence_source": "vendor_tracking_db",
                    "ai_lines": ai_lines, "human_lines": human_lines,
                    "ai_fraction": round(ai_lines / denom, 4) if denom else None,
                    "vendor_score_version":
                        "v2" if score["v2"] is not None else
                        ("v1" if score["v1"] is not None else None),
                }
            elif score is not None:
                attribution = {"status": "partial",
                               "evidence_source": "vendor_tracking_db",
                               "ai_lines": None, "human_lines": None,
                               "ai_fraction": None,
                               "vendor_score_version": None}
            elif trailer_ai:
                attribution = {"status": "partial", "evidence_source": "self_report",
                               "ai_lines": None, "human_lines": None,
                               "ai_fraction": None, "vendor_score_version": None}
            else:
                attribution = {"status": "unknown", "evidence_source": "none",
                               "ai_lines": None, "human_lines": None,
                               "ai_fraction": None, "vendor_score_version": None}

            pr = pr_by_sha.get(sha)
            if pr is None:
                m = _PR_SQUASH_RE.search(subject)
                if m:
                    pr = int(m.group(1))

            # revert markers may carry abbreviated shas
            rv = reverted_by.get(sha) or next(
                (r for t, r in reverted_by.items() if sha.startswith(t)), None)
            if rv:
                revert = {"reverted": True, "revert_commit_sha": rv,
                          "revert_detection": "git_revert_marker"}
            else:
                revert = {"reverted": False, "revert_commit_sha": None,
                          "revert_detection": None}

            core = {
                "schema_version": SIGNAL_SCHEMA_VERSION,
                "signals_version": GIT_CONNECTOR_VERSION,
                "change_ref": {
                    "repo_ref": repo_ref,
                    "commit_sha": sha,
                    "pr_number": pr,
                    "branch": None,
                    "authored_at": datetime.fromtimestamp(
                        c["time"], tz=timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "lines_added": lines_added,
                    "lines_deleted": lines_deleted,
                },
                "ai_attribution": attribution,
                "survival": survival,
                "rework": rework,
                "review": None,  # iteration counts need a forge API; local git
                                 # only shows the PR pattern (change_ref.pr_number)
                "revert": revert,
            }
            core["provenance"] = {
                "connector_version": GIT_CONNECTOR_VERSION,
                "content_hash": sha256_json(core),
                "repo_path": root_str,
                "head_sha": head,
            }
            core["measured_at"] = now_iso()
            records.append(core)
        return records

    # ---------------------------------------------------------- join stats

    def session_join_stats(self, sessions_by_tool: dict[str, list[dict]],
                           cwd_to_root: dict[str, str],
                           signal_records: list[dict]) -> dict:
        """How many extracted sessions reach a repo / a commit. The join key
        is project_ref == salted hash of the session cwd (ADR-0005 §3)."""
        ref_to_root = {project_ref(self.salt, cwd): root
                       for cwd, root in cwd_to_root.items()}
        commits_by_root: dict[str, list[dict]] = {}
        for rec in signal_records:
            commits_by_root.setdefault(rec["provenance"]["repo_path"], []).append(rec)
        stats: dict[str, dict] = {}
        for tool, sessions in sessions_by_tool.items():
            n = len(sessions)
            repo_joined = 0
            commit_window_joined = 0
            for s in sessions:
                root = ref_to_root.get(s.get("project_ref"))
                if not root:
                    continue
                repo_joined += 1
                start = s.get("started_at")
                end = s.get("ended_at") or start
                if not start:
                    continue
                for rec in commits_by_root.get(root, []):
                    at = rec["change_ref"]["authored_at"]
                    if at and start <= at <= end:
                        commit_window_joined += 1
                        break
            stats[tool] = {
                "sessions": n,
                "repo_join": repo_joined,
                "repo_join_rate": round(repo_joined / n, 3) if n else None,
                "commit_in_session_window": commit_window_joined,
                "commit_window_rate": round(commit_window_joined / n, 3) if n else None,
            }
        return stats
