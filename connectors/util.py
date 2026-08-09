"""Shared helpers: opaque refs, timestamps, extension->language mapping."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

# Salt for project_ref hashing. Env override keeps tests deterministic; the
# file default keeps refs stable across runs on one machine while staying
# out of the repo (data/extracted/ is not committed).
_SALT_ENV = "CALIPER_HASH_SALT"


def load_salt(data_dir: Path) -> str:
    env = os.environ.get(_SALT_ENV)
    if env:
        return env
    salt_file = data_dir / ".salt"
    if salt_file.exists():
        return salt_file.read_text().strip()
    salt = os.urandom(16).hex()
    salt_file.parent.mkdir(parents=True, exist_ok=True)
    salt_file.write_text(salt)
    return salt


def project_ref(salt: str, raw_path: str) -> str:
    """Opaque, salted ref for a cwd / repo root. Raw paths never leave the
    connector (docs/conventions.md)."""
    return "p_" + hashlib.sha256((salt + "|" + raw_path).encode()).hexdigest()[:16]


def iso_utc(ts: str | int | float | None) -> str | None:
    """Normalize a source timestamp to ISO-8601 UTC. Accepts ISO strings and
    epoch millis/seconds. Returns None for None — absence stays absent."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        # Heuristic only for epoch magnitude, not for data content: ms vs s.
        if ts > 1e11:
            ts = ts / 1000.0
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        s = str(ts).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ms_between(start_iso: str | None, end_iso: str | None) -> int | None:
    if not start_iso or not end_iso:
        return None
    a = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    b = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    return max(0, int((b - a).total_seconds() * 1000))


_EXT_LANG = {
    "py": "python", "ts": "typescript", "tsx": "typescript", "js": "javascript",
    "jsx": "javascript", "mjs": "javascript", "cjs": "javascript", "json": "json",
    "jsonl": "json", "md": "markdown", "mdx": "markdown", "html": "html",
    "css": "css", "scss": "css", "toml": "toml", "yaml": "yaml", "yml": "yaml",
    "sh": "shell", "zsh": "shell", "bash": "shell", "rs": "rust", "go": "go",
    "java": "java", "kt": "kotlin", "swift": "swift", "c": "c", "h": "c",
    "cpp": "cpp", "hpp": "cpp", "cc": "cpp", "rb": "ruby", "php": "php",
    "sql": "sql", "svelte": "svelte", "vue": "vue", "txt": "text",
}


def languages_from_paths(paths) -> list[str]:
    """Extension-based only — never inferred from content (conventions.md)."""
    exts = set()
    for p in paths:
        suffix = Path(str(p)).suffix.lstrip(".").lower()
        if suffix:
            exts.add(suffix)
    langs = {_EXT_LANG.get(e, e) for e in exts}
    return sorted(langs)


def languages_from_extensions(exts) -> list[str]:
    langs = {_EXT_LANG.get(str(e).lstrip(".").lower(), str(e).lstrip(".").lower())
             for e in exts if e}
    return sorted(l for l in langs if l)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def prune(obj):
    """Drop None values and empty dicts/lists so 'cannot provide' fields are
    ABSENT, never null-defaulted. Explicit nulls the schema wants (e.g.
    fork_of: null) are set after pruning by the caller."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            pv = prune(v)
            if pv is None:
                continue
            if isinstance(pv, (dict, list)) and not pv:
                continue
            out[k] = pv
        return out
    if isinstance(obj, list):
        return [prune(v) for v in obj if prune(v) is not None]
    return obj
