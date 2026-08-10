"""Local-only display names for salted project refs.

Rebuilds the ref -> short-name mapping the same way the connectors hash:
re-derive candidate cwds from the sources, hash with the extraction salt,
keep only the LAST path component as the display name. The mapping file
lives inside data/extracted/ (gitignored); raw paths never enter any
committed artifact."""

from __future__ import annotations

import json
from pathlib import Path

from connectors.git_history import GitHistoryConnector
from connectors.util import load_salt, project_ref


def build_name_map(data_dir: Path) -> dict[str, str]:
    salt = load_salt(data_dir)
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
    out = data_dir / ".project_names.json"
    out.write_text(json.dumps(names, indent=2))
    return names


def load_name_map(data_dir: Path) -> dict[str, str]:
    p = data_dir / ".project_names.json"
    if p.exists():
        return json.loads(p.read_text())
    return build_name_map(data_dir)
