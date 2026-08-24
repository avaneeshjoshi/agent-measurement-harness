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


def load_salt(salt_file: Path) -> str:
    """env override -> existing file -> create once (0400: the salt is the
    join key for every ref and is never rewritten — ADR-0012). Callers
    resolve the location through cli.paths.salt_path()."""
    env = os.environ.get(_SALT_ENV)
    if env:
        return env
    if salt_file.exists():
        return salt_file.read_text().strip()
    salt = os.urandom(16).hex()
    salt_file.parent.mkdir(parents=True, exist_ok=True)
    salt_file.write_text(salt)
    os.chmod(salt_file, 0o400)
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


_TEST_PATH_RE = None
_DOCS_EXT = {"md", "mdx", "rst", "txt", "adoc"}
_CONFIG_EXT = {"json", "jsonl", "yaml", "yml", "toml", "ini", "cfg", "conf",
               "properties", "env", "lock", "gradle", "xml"}
_CONFIG_NAMES = {"dockerfile", "makefile", "gemfile", "rakefile", "procfile",
                 ".gitignore", ".gitattributes", ".editorconfig", ".env"}
# Narrow deliberately: generic dirs like /memory/ or /skills/ appear in
# ordinary repos (rules-0.1.1 fix — they misflagged product work as
# agent_meta_work). Only unambiguous agent-tooling paths qualify.
_AGENT_MARKERS = (".claude/", ".claude\\", "claude.md", ".cursorrules",
                  ".cursor/", ".mcp.json", ".codex/")


def path_flags(raw_path: str) -> dict:
    """Content-free booleans derived from a raw path AT THE CONNECTOR.
    The raw path never leaves; only these flags and salted hashes do."""
    import re
    p = raw_path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else None
    is_test = bool(re.search(r"(^|/)(tests?|__tests__|spec|specs)(/|$)", p)
                   or re.search(r"(_test|\.test|_spec|\.spec|test_)[^/]*$", name)
                   or name.endswith("test.java"))
    is_docs = (ext in _DOCS_EXT) or bool(re.search(r"(^|/)(docs?|documentation)(/|$)", p))
    is_agent = any(m in p or name == m.strip("/") for m in _AGENT_MARKERS) \
        or name in ("claude.md", "agents.md")
    is_config = (not is_docs and not is_agent
                 and (ext in _CONFIG_EXT or name in _CONFIG_NAMES
                      or bool(re.search(r"(^|/)(\.github|\.circleci|config|configs)(/|$)", p))))
    return {"extension": ext, "is_test_path": is_test, "is_docs_path": is_docs,
            "is_config_path": is_config, "is_agent_config_path": is_agent}


def file_refs(salt: str, raw_path: str) -> dict:
    """Salted refs for a file and its top-level directory."""
    import hashlib
    norm = raw_path.replace("\\", "/")
    top = norm.lstrip("/").split("/", 1)[0] if "/" in norm.lstrip("/") else "<root>"
    def h(v):
        return "f_" + hashlib.sha256((salt + "|" + v).encode()).hexdigest()[:12]
    return {"file_ref": h(norm), "top_dir_ref": h("dir:" + top)}


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
