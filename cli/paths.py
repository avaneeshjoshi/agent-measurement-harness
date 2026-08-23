"""Where Caliper's collected data lives (ADR-0011).

Extracted traffic is user data, not repo data: it must survive without a git
tree present, and a background collector must not write into a repo path.
Default home: ~/.caliper (CALIPER_HOME overrides; --data-dir still wins where
a command offers it). Committed evidence (data/derived/, calibration,
fixtures) stays in the repo.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def data_root() -> Path:
    return Path(os.environ.get("CALIPER_HOME") or Path.home() / ".caliper")


def extracted_dir() -> Path:
    return data_root() / "extracted"


def logs_dir() -> Path:
    return data_root() / "logs"


def _populated(d: Path) -> bool:
    return d.is_dir() and any(d.iterdir())


def _file_count(d: Path) -> int:
    return sum(1 for p in d.rglob("*") if p.is_file())


def migrate_legacy(repo_root: Path) -> dict | None:
    """One-time move of a populated <repo>/data/extracted tree to the data
    home. Idempotent and non-destructive: a populated target is never
    overwritten; the cross-device fallback removes the source only after the
    copy verifies (.salt bytes + file count), and a failed verify cleans the
    partial target and leaves the legacy tree untouched.

    Returns {"moved": n, ...} on migration, {"skipped": "both-populated", ...}
    when both trees hold data, None when there is nothing to do.
    """
    legacy = repo_root / "data" / "extracted"
    target = extracted_dir()
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
        # Cross-device: copy, verify, and only then remove the source.
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
