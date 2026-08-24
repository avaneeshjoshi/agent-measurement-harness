"""Local-only display names for salted project refs.

Rebuilds the ref -> short-name mapping the same way the connectors hash:
re-derive candidate cwds from the sources, hash with the extraction salt,
keep only the LAST path component as the display name. The mapping file
lives in the state tree under ~/.caliper (ADR-0012); raw paths never enter
any committed artifact."""

from __future__ import annotations

import json
from pathlib import Path

from caliper.connectors.git_history import GitHistoryConnector
from caliper.connectors.util import load_salt, project_ref


def build_name_map(map_path: Path, salt_file: Path,
                   write: bool = True) -> dict[str, str]:
    """write=False builds the map in memory only — serve's read-only
    guarantee (ADR-0016) forbids it persisting anything, while the report
    path keeps owning the on-disk map."""
    salt = load_salt(salt_file)
    conn = GitHistoryConnector(salt=salt)
    cands = conn.collect_candidate_paths()
    _, cwd_to_root = conn.discover_repos()
    names: dict[str, str] = {}
    for cwd in cands:
        ref = project_ref(salt, cwd)
        if cwd not in cwd_to_root and "caliper-eval" not in cwd:
            # scratch dirs, one-off folders, home dir: real work locations
            # but not projects — grouping them stops the project table
            # filling with directory noise
            names.setdefault(ref, "scratch / no repo")
            continue
        if "caliper-eval" in cwd:
            # eval workdir basenames are model ids — collapse the whole
            # harness cohort to one display name or the project list fills
            # with fake "projects" named claude-*
            short = "eval-harness runs"
        else:
            short = cwd.rstrip("/").rsplit("/", 1)[-1] or cwd
        names.setdefault(ref, short)
    if write:
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(json.dumps(names, indent=2))
    return names


def load_name_map(map_path: Path, salt_file: Path,
                  write: bool = True) -> dict[str, str]:
    if map_path.exists():
        return json.loads(map_path.read_text())
    import os
    if not write and not salt_file.exists() \
            and not os.environ.get("CALIPER_HASH_SALT"):
        # nothing was ever extracted (no salt): an in-memory build would
        # hash with a salt no ref was made with — and load_salt would
        # CREATE the salt file, which a read-only caller must never do
        return {}
    return build_name_map(map_path, salt_file, write=write)
