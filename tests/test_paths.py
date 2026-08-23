"""Data-home migration guarantees (ADR-0011): the move preserves the salt —
and therefore every ref joined against history — never overwrites a populated
target, and is idempotent."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from cli.paths import data_root, extracted_dir, migrate_legacy
from tests.conftest import FIXTURES, SCHEMA


def _legacy_tree(repo: Path, files: dict[str, str]) -> Path:
    legacy = repo / "data" / "extracted"
    for rel, content in files.items():
        p = legacy / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return legacy


BASIC = {".salt": "abc123", "claude_code/sessions.jsonl": '{"session_id":"s1"}\n',
         "manifests/20260801T000000Z-aaaa.json": "{}"}


def test_migration_moves_populated_legacy_tree(tmp_path):
    legacy = _legacy_tree(tmp_path / "repo", BASIC)
    result = migrate_legacy(tmp_path / "repo")
    assert result["moved"] == 3
    assert not legacy.exists()
    assert (extracted_dir() / ".salt").read_text() == "abc123"
    assert (extracted_dir() / "claude_code" / "sessions.jsonl").exists()


def test_migration_idempotent_second_run_noop(tmp_path):
    _legacy_tree(tmp_path / "repo", BASIC)
    assert migrate_legacy(tmp_path / "repo")["moved"] == 3
    assert migrate_legacy(tmp_path / "repo") is None


def test_migration_never_overwrites_populated_target(tmp_path):
    _legacy_tree(tmp_path / "repo", BASIC)
    target = extracted_dir()
    target.mkdir(parents=True)
    (target / ".salt").write_text("existing-salt")
    result = migrate_legacy(tmp_path / "repo")
    assert result["skipped"] == "both-populated"
    assert (target / ".salt").read_text() == "existing-salt"
    assert (tmp_path / "repo" / "data" / "extracted" / ".salt").exists()


def test_migration_nothing_to_do_without_legacy(tmp_path):
    assert migrate_legacy(tmp_path / "repo") is None


def test_exdev_fallback_verifies_before_removing_source(tmp_path, monkeypatch):
    legacy = _legacy_tree(tmp_path / "repo", BASIC)
    monkeypatch.setattr(os, "rename",
                        lambda *a: (_ for _ in ()).throw(OSError("EXDEV")))
    result = migrate_legacy(tmp_path / "repo")
    assert result["moved"] == 3
    assert not legacy.exists()
    assert (extracted_dir() / ".salt").read_text() == "abc123"


def test_exdev_verify_failure_leaves_legacy_and_cleans_target(tmp_path, monkeypatch):
    legacy = _legacy_tree(tmp_path / "repo", BASIC)
    monkeypatch.setattr(os, "rename",
                        lambda *a: (_ for _ in ()).throw(OSError("EXDEV")))
    real_copytree = shutil.copytree

    def lossy_copytree(src, dst, *args, **kw):
        # copytree recurses through the module-global name, so the wrapper
        # must match the full signature and only drop the file at top level
        result = real_copytree(src, dst, *args, **kw)
        victim = Path(dst) / "claude_code" / "sessions.jsonl"
        if victim.exists():
            victim.unlink()
        return result

    monkeypatch.setattr(shutil, "copytree", lossy_copytree)
    with pytest.raises(RuntimeError, match="verify failed"):
        migrate_legacy(tmp_path / "repo")
    assert (legacy / ".salt").read_text() == "abc123"  # source untouched
    assert not extracted_dir().exists()  # partial target cleaned


def test_migration_preserves_salt_and_refs_match(tmp_path, monkeypatch):
    """The load-bearing case: refs computed before and after the move must
    join. Uses the real file-salt path (env salt removed)."""
    monkeypatch.delenv("CALIPER_HASH_SALT")
    from cli.main import extract
    from connectors.claude_code import ClaudeCodePlugin
    from connectors.util import load_salt

    repo = tmp_path / "repo"
    legacy = repo / "data" / "extracted"
    legacy.mkdir(parents=True)

    def run(data_dir):
        plugin = ClaudeCodePlugin(salt=load_salt(data_dir),
                                  root=FIXTURES / "claude_code")
        extract(["claude_code"], data_dir, SCHEMA, include_content=False,
                plugins_override={"claude_code": plugin})
        recs = [__import__("json").loads(l) for l in
                (data_dir / "claude_code" / "sessions.jsonl").read_text().splitlines()]
        return {r["session_id"]: r["project_ref"] for r in recs}

    before = run(legacy)
    salt_before = (legacy / ".salt").read_bytes()
    assert migrate_legacy(repo)["moved"] >= 2

    after = run(extracted_dir())
    assert (extracted_dir() / ".salt").read_bytes() == salt_before
    assert before == after  # same salt -> same refs -> history still joins


def test_caliper_home_env_override():
    assert str(data_root()).startswith(str(Path(os.environ["CALIPER_HOME"])))
