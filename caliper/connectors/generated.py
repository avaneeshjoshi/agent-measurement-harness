"""Generated-path classification for the durability signals (ADR-0015).

A lockfile regeneration is a real diff — 3,013,346 lines in one observed
commit — but it isn't work anyone did, and unfiltered it dominates every
line-weighted figure its repo produces (the ADR-0006 finding). Signals
therefore exclude known-generated paths from line counting, visibly: the
pattern list below is versioned and stated in the report, both filtered and
unfiltered counts travel on every record, and a repo's own
`.gitattributes linguist-generated` declaration overrides the heuristic in
BOTH directions.

Known limitation (ADR-0015): `git check-attr` reads the working tree's
attributes, not each commit's — a file marked generated today filters
historical commits too.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

GENERATED_PATTERNS_VERSION = "gen-0.1.0"

# Basename globs
_NAME_PATTERNS = (
    # lockfiles across ecosystems
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "Cargo.lock", "poetry.lock", "uv.lock", "Pipfile.lock", "Gemfile.lock",
    "composer.lock", "go.sum", "Podfile.lock", "flake.lock",
    "packages.lock.json", "gradle.lockfile",
    # minified / derived assets
    "*.min.js", "*.min.css", "*.js.map", "*.css.map",
    # codegen markers
    "*.pb.go", "*_pb2.py", "*_pb2_grpc.py", "*.generated.*",
)

# Any path containing one of these as a directory segment
_DIR_SEGMENTS = frozenset({
    "node_modules", "dist", "build", "out", "target", ".next",
    "vendor", "__pycache__", "venv", ".venv",
})


def is_generated(path: str) -> bool:
    """Pattern verdict only — callers wanting the repo's own say use
    classify_paths, which lets .gitattributes override this."""
    parts = path.split("/")
    if any(seg in _DIR_SEGMENTS for seg in parts[:-1]):
        return True
    name = parts[-1]
    return any(fnmatch.fnmatch(name, pat) for pat in _NAME_PATTERNS)


def classify_paths(root: Path, paths: list[str]) -> dict[str, bool]:
    """path -> generated?, honoring `.gitattributes linguist-generated`:
    attribute set → generated; explicitly unset (`-linguist-generated`) →
    NOT generated even when a pattern matches (the repo's declaration is the
    escape hatch for over-broad patterns); unspecified → pattern verdict."""
    verdict = {p: is_generated(p) for p in paths}
    if not paths:
        return verdict
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "check-attr", "linguist-generated",
             "--stdin", "-z"],
            input="\0".join(paths), capture_output=True, text=True,
            timeout=60)
        if r.returncode == 0:
            fields = r.stdout.split("\0")
            # -z output: path, attr, value, path, attr, value, ...
            for i in range(0, len(fields) - 2, 3):
                p, value = fields[i], fields[i + 2]
                if value in ("set", "true"):
                    verdict[p] = True
                elif value == "unset":
                    verdict[p] = False
    except (OSError, subprocess.TimeoutExpired):
        pass  # patterns alone; attribute support is additive
    return verdict
