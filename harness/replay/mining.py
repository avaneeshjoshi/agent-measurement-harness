"""Task mining: real bug-fix commits -> validated replay tasks.

A candidate fix commit C qualifies as a task when:
- its subject is fix-like (and not build/docs/typo noise);
- it changes 1..5 files under src/main/java with modest churn (bug-fix scale,
  not a feature or refactor);
- it changes at least one *Test.java under src/test/java (the hidden tests);
- VALIDATION: at C~1 with C's test changes overlaid, the hidden test classes
  compile and at least one hidden test FAILS (the bug reproduces); at C they
  all PASS (the fix + tests are ground truth). Candidates whose tests don't
  compile at C~1 are rejected — those are API-addition tasks, not behavioral
  bug fixes, and grading them by hidden test would mostly measure exact-name
  guessing.

The task carries: repo, fix sha, pre sha, problem statement (commit message),
hidden test classes, and the test diff. The agent never sees the fix commit,
its message's diff, or the hidden tests (enforced by the runner: history-free
snapshot at C~1, network tools disabled).
"""

from __future__ import annotations

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

_FIX_RE = re.compile(r"\b(fix|Fix|LANG-\d+|bug|Bug)\b")
_NOISE_RE = re.compile(
    r"Bump|dependabot|[Jj]avadoc|[Tt]ypo|spelling|checkstyle|CHANGES|README|"
    r"[Tt]est coverage|[Aa]dd missing test|[Ss]implify|[Rr]efactor|[Dd]eprecate|"
    r"[Rr]ename|[Ff]ormat|[Ss]tyle|PMD|SpotBugs|[Cc]omment")


def _git(repo: Path, *args: str, timeout: int = 120) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {res.stderr[:300]}")
    return res.stdout


@dataclass
class Task:
    task_id: str
    repo_url: str
    fix_sha: str
    pre_sha: str
    subject: str
    problem_statement: str
    hidden_test_classes: list
    main_files_changed: list
    main_lines_changed: int
    authored_at: str
    validation: dict


def _changed_files(repo: Path, sha: str) -> list[tuple[str, str]]:
    out = _git(repo, "show", "--numstat", "--format=", sha)
    files = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] != "-":
            files.append((parts[2], int(parts[0]) + int(parts[1])))
    return files


def _fqcn(test_path: str) -> str | None:
    m = re.match(r"src/test/java/(.+)\.java$", test_path)
    return m.group(1).replace("/", ".") if m else None


def find_candidates(repo: Path, since: str = "2023-01-01",
                    max_main_files: int = 5, max_churn: int = 250):
    """Yield candidate fix shas, newest first, deduped by normalized subject."""
    log = _git(repo, "log", f"--since={since}", "--no-merges",
               "--pretty=%H|%as|%s", timeout=60)
    seen_subjects = set()
    for line in log.splitlines():
        sha, date, subj = line.split("|", 2)
        norm = re.sub(r"[^a-z0-9]", "", subj.lower())
        if norm in seen_subjects:
            continue
        if not _FIX_RE.search(subj) or _NOISE_RE.search(subj):
            continue
        seen_subjects.add(norm)
        try:
            files = _changed_files(repo, sha)
        except RuntimeError:
            continue
        main = [(f, n) for f, n in files if f.startswith("src/main/java/")]
        tests = [f for f, _ in files
                 if f.startswith("src/test/java/") and f.endswith("Test.java")]
        other = [f for f, _ in files
                 if not f.startswith(("src/main/java/", "src/test/java/"))]
        churn = sum(n for _, n in main)
        if not main or not tests or len(main) > max_main_files \
                or churn > max_churn or len(other) > 2:
            continue
        yield {
            "sha": sha, "date": date, "subject": subj,
            "main_files": [f for f, _ in main], "main_churn": churn,
            "test_classes": sorted({c for c in map(_fqcn, tests) if c}),
        }


def _surefire_totals(workdir: Path) -> tuple[int, int] | None:
    """(passed, total) summed over surefire XML reports; None if no reports
    (compile failure or nothing ran)."""
    reports = list((workdir / "target" / "surefire-reports").glob("TEST-*.xml"))
    if not reports:
        return None
    total = failed = 0
    for r in reports:
        try:
            root = ET.parse(r).getroot()
        except ET.ParseError:
            continue
        t = int(root.get("tests", 0))
        f = int(root.get("failures", 0)) + int(root.get("errors", 0))
        total += t
        failed += f
    return (total - failed, total)


def run_hidden_tests(workdir: Path, test_classes: list[str],
                     timeout: int = 600) -> tuple[int, int] | None:
    """mvn test restricted to the hidden classes. Returns (passed, total),
    or None on compile failure / no reports."""
    reports_dir = workdir / "target" / "surefire-reports"
    if reports_dir.exists():
        for f in reports_dir.iterdir():
            f.unlink()
    short = ",".join(c.rsplit(".", 1)[-1] for c in test_classes)
    try:
        subprocess.run(
            ["mvn", "-q", "test", f"-Dtest={short}", "-DfailIfNoTests=false",
             "-Dsurefire.failIfNoSpecifiedTests=false", "-Drat.skip=true",
             "-Dspotbugs.skip=true", "-Dpmd.skip=true", "-Dcheckstyle.skip=true",
             "-Dspotless.check.skip=true", "-Danimal.sniffer.skip=true"],
            cwd=workdir, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return _surefire_totals(workdir)


def validate_candidate(repo: Path, cand: dict, scratch: Path) -> Task | None:
    """The Defects4J-style gate: bug reproduces at pre, fix passes at fix."""
    sha, pre = cand["sha"], cand["sha"] + "~1"
    pre_sha = _git(repo, "rev-parse", pre).strip()
    test_diff = _git(repo, "diff", f"{pre}..{sha}", "--", "src/test")

    wt = scratch / f"validate-{sha[:10]}"
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
                   capture_output=True)
    try:
        _git(repo, "worktree", "add", "--detach", str(wt), pre)
        # overlay the fix commit's test changes onto the pre state
        apply = subprocess.run(["git", "apply", "-"], input=test_diff, text=True,
                               cwd=wt, capture_output=True)
        if apply.returncode != 0:
            return None
        pre_result = run_hidden_tests(wt, cand["test_classes"])
        if pre_result is None:
            return None  # tests don't compile at pre -> API-addition, reject
        pre_passed, pre_total = pre_result
        if pre_total == 0 or pre_passed == pre_total:
            return None  # bug does not reproduce
        # fix side
        _git(repo, "worktree", "remove", "--force", str(wt))
        _git(repo, "worktree", "add", "--detach", str(wt), sha)
        fix_result = run_hidden_tests(wt, cand["test_classes"])
        if fix_result is None:
            return None
        fix_passed, fix_total = fix_result
        if fix_total == 0 or fix_passed != fix_total:
            return None  # ground truth itself is red -> unusable
        body = _git(repo, "show", "-s", "--format=%B", sha).strip()
        return Task(
            task_id=f"commons-lang-{sha[:10]}",
            repo_url="https://github.com/apache/commons-lang",
            fix_sha=sha, pre_sha=pre_sha,
            subject=cand["subject"], problem_statement=body,
            hidden_test_classes=cand["test_classes"],
            main_files_changed=cand["main_files"],
            main_lines_changed=cand["main_churn"],
            authored_at=cand["date"],
            validation={
                "pre": {"passed": pre_passed, "total": pre_total},
                "fix": {"passed": fix_passed, "total": fix_total},
            },
        )
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(wt)],
                       capture_output=True)


def mine(repo: Path, out_path: Path, target_n: int = 30,
         scratch: Path | None = None, log=print) -> list[Task]:
    scratch = scratch or repo.parent / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    tasks: list[Task] = []
    examined = 0
    for cand in find_candidates(repo):
        if len(tasks) >= target_n:
            break
        examined += 1
        log(f"[{len(tasks)}/{target_n}] validating {cand['sha'][:10]} {cand['subject'][:70]}")
        try:
            task = validate_candidate(repo, cand, scratch)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            log(f"  error: {exc}")
            continue
        if task:
            tasks.append(task)
            log(f"  VALID (pre {task.validation['pre']['passed']}/"
                f"{task.validation['pre']['total']} -> fix "
                f"{task.validation['fix']['passed']}/{task.validation['fix']['total']})")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as fh:
                for t in tasks:
                    fh.write(json.dumps(asdict(t)) + "\n")
        else:
            log("  rejected")
    log(f"mined {len(tasks)} tasks from {examined} candidates")
    return tasks
