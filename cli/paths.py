"""The single authority for where Caliper's data lives (ADR-0011, ADR-0012).

THE RULE: user data never touches the git tree. If Caliper computed it from
someone's traffic, repos, or machine, it lives under ~/.caliper; if it is a
contract, a fixture, or evidence an ADR cites, it lives in the repo. No
third category. No other module may construct a repo-relative data path —
a source-scan test and a runtime write-audit test enforce it.

Layout:
    ~/.caliper/
      .salt        the ref join key — top level, chmod 0400, never rewritten
      extracted/   sessions, prompt units, git signals, manifests, sidecars
      derived/     classes/, replay/, routing/ — regenerable outputs
      reports/     generated HTML
      state/       collection state, decisions, name map, lock
      logs/        scheduled job output

CALIPER_HOME overrides the root (tests sandbox with it); --data-dir overrides
the *extracted tree only* and is self-contained (its own .salt beside it) —
override runs never touch home state.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def data_root() -> Path:
    return Path(os.environ.get("CALIPER_HOME") or Path.home() / ".caliper")


def extracted_dir() -> Path:
    return data_root() / "extracted"


def derived_dir() -> Path:
    return data_root() / "derived"


def reports_dir() -> Path:
    return data_root() / "reports"


def state_dir() -> Path:
    return data_root() / "state"


def logs_dir() -> Path:
    return data_root() / "logs"


def salt_path(data_dir: Path | None = None) -> Path:
    """The salt is the one unregenerable file: lose it and nothing new ever
    joins to existing history. It sits at the TOP of the home tree, beside —
    not inside — the clearable subtrees (ADR-0012). An explicit --data-dir
    tree is a self-contained experiment and keeps its own salt."""
    if data_dir is not None and Path(data_dir) != extracted_dir():
        return Path(data_dir) / ".salt"
    return data_root() / ".salt"


# ---- read fallbacks --------------------------------------------------------
# Reading repo-side evidence is fine; writing is the sin. First existing
# candidate wins: home derived -> shipped ADR evidence -> legacy repo path
# (transitional, pre-ADR-0012 checkouts).

def _first_existing(candidates: list[Path]) -> Path:
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # the canonical write target, even if absent yet


def task_classes_path(repo_root: Path) -> Path:
    return _first_existing([
        derived_dir() / "classes" / "task_classes.jsonl",
        repo_root / "data" / "derived" / "classes" / "task_classes.jsonl",
    ])


def eval_results_path(repo_root: Path) -> Path:
    return _first_existing([
        derived_dir() / "replay" / "eval_results.jsonl",
        repo_root / "data" / "evidence" / "adr-0007" / "eval_results.jsonl",
        repo_root / "data" / "derived" / "replay" / "eval_results.jsonl",
    ])


def routing_policies_path(repo_root: Path) -> Path:
    return _first_existing([
        derived_dir() / "routing" / "routing_policies.jsonl",
        repo_root / "data" / "evidence" / "adr-0008" / "routing_policies.jsonl",
        repo_root / "data" / "derived" / "routing" / "routing_policies.jsonl",
    ])


# ---- migration (ADR-0011 + ADR-0012) --------------------------------------

def _populated(d: Path) -> bool:
    return d.is_dir() and any(d.iterdir())


def _file_count(d: Path) -> int:
    return sum(1 for p in d.rglob("*") if p.is_file())


def _move_tree(legacy: Path, target: Path) -> dict | None:
    """Whole-tree move: rename, or copy → verify (.salt bytes + file count)
    → only then delete. Never overwrites a populated target."""
    if not _populated(legacy):
        return None
    if _populated(target):
        return {"skipped": "both-populated",
                "legacy": str(legacy), "target": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        target.rmdir()  # exists but empty — clear the way for a rename
    n_files = _file_count(legacy)
    try:
        os.rename(legacy, target)
    except OSError:
        shutil.copytree(legacy, target)
        salt_src, salt_dst = legacy / ".salt", target / ".salt"
        salt_ok = (not salt_src.exists()
                   or (salt_dst.exists()
                       and salt_src.read_bytes() == salt_dst.read_bytes()))
        copied = _file_count(target)
        if copied != n_files or not salt_ok:
            shutil.rmtree(target, ignore_errors=True)
            raise RuntimeError(
                f"migration verify failed ({copied}/{n_files} files, "
                f"salt_ok={salt_ok}); legacy tree left untouched at {legacy}")
        shutil.rmtree(legacy)
    return {"moved": n_files, "legacy": str(legacy), "target": str(target)}


def _move_file(legacy: Path, target: Path) -> dict | None:
    """Single-file move with the same guarantees at file grain."""
    if not legacy.is_file():
        return None
    if target.exists():
        return {"skipped": "target-exists",
                "legacy": str(legacy), "target": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(legacy, target)
    except OSError:
        data = legacy.read_bytes()
        target.write_bytes(data)
        if target.read_bytes() != data:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"migration verify failed for {legacy}; "
                               "source left untouched")
        legacy.unlink()
    return {"moved": 1, "legacy": str(legacy), "target": str(target)}


def migrate_legacy(repo_root: Path) -> list[dict]:
    """All layout migrations, ordered, each idempotent and non-destructive.
    Returns the list of actions taken/skipped (empty = nothing to do)."""
    actions: list[dict] = []

    def note(a: dict | None) -> None:
        if a:
            actions.append(a)

    # 1. ADR-0011: repo data/extracted -> home extracted
    note(_move_tree(repo_root / "data" / "extracted", extracted_dir()))

    # 2. ADR-0012: live task classes out of the repo tree
    note(_move_file(
        repo_root / "data" / "derived" / "classes" / "task_classes.jsonl",
        derived_dir() / "classes" / "task_classes.jsonl"))

    ex = extracted_dir()
    # 3. state files out of the extracted tree
    for name in (".collection.json", ".policy_decisions.jsonl",
                 ".project_names.json"):
        note(_move_file(ex / name, state_dir() / name))

    # 4. the salt lifts to the top of the tree
    legacy_salt, home_salt = ex / ".salt", data_root() / ".salt"
    if legacy_salt.is_file():
        if not home_salt.exists():
            note(_move_file(legacy_salt, home_salt))
            os.chmod(home_salt, 0o400)
        elif home_salt.read_bytes() == legacy_salt.read_bytes():
            legacy_salt.unlink()  # verified duplicate
            actions.append({"deduped": str(legacy_salt)})
        else:
            # two different salts should be impossible; never pick silently
            actions.append({"CONFLICT": "two different salts",
                            "legacy": str(legacy_salt),
                            "target": str(home_salt),
                            "detail": "kept both; home salt is used — "
                                      "resolve manually"})

    # 5. the report moves to reports/
    note(_move_file(ex / "report" / "first_look.html",
                    reports_dir() / "first_look.html"))
    try:
        (ex / "report").rmdir()  # only if now empty
    except OSError:
        pass

    return actions
