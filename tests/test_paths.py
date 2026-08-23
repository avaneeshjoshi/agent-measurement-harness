"""Data-home layout and migration guarantees (ADR-0011, ADR-0012): the move
preserves the salt — and therefore every ref joined against history — never
overwrites a populated target, covers state files, the salt lift, and the
report, and is idempotent."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from cli.paths import (data_root, derived_dir, extracted_dir, migrate_legacy,
                       reports_dir, salt_path, state_dir)
from tests.conftest import FIXTURES, SCHEMA


def _legacy_tree(repo: Path, files: dict[str, str]) -> Path:
    legacy = repo / "data" / "extracted"
    for rel, content in files.items():
        p = legacy / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return legacy


BASIC = {".salt": "abc123", "claude_code/sessions.jsonl": '{"session_id":"s1"}\n',
         "manifests/20260801T000000Z-aaaa.json": "{}",
         ".collection.json": '{"version": 1}',
         ".policy_decisions.jsonl": '{"policy_id":"rp-0001","applied":false}\n',
         "report/first_look.html": "<title>x</title>"}


def _moved_total(actions: list[dict]) -> int:
    return sum(a.get("moved", 0) for a in actions)


def test_migration_moves_full_layout(tmp_path):
    _legacy_tree(tmp_path / "repo", BASIC)
    (tmp_path / "repo" / "data" / "derived" / "classes").mkdir(parents=True)
    (tmp_path / "repo" / "data" / "derived" / "classes" /
     "task_classes.jsonl").write_text('{"unit":"prompt"}\n')

    actions = migrate_legacy(tmp_path / "repo")
    assert _moved_total(actions) >= 6
    # extracted tree
    assert (extracted_dir() / "claude_code" / "sessions.jsonl").exists()
    # live derived data out of the repo tree (ADR-0012)
    assert (derived_dir() / "classes" / "task_classes.jsonl").exists()
    assert not (tmp_path / "repo" / "data" / "derived" / "classes"
                / "task_classes.jsonl").exists()
    # state files out of the extracted tree
    assert (state_dir() / ".collection.json").exists()
    assert (state_dir() / ".policy_decisions.jsonl").exists()
    assert not (extracted_dir() / ".collection.json").exists()
    # the salt lifts to the top of the tree, read-only
    home_salt = data_root() / ".salt"
    assert home_salt.read_text() == "abc123"
    assert not (extracted_dir() / ".salt").exists()
    assert oct(home_salt.stat().st_mode)[-3:] == "400"
    # the report moves to reports/
    assert (reports_dir() / "first_look.html").exists()
    assert not (extracted_dir() / "report").exists()


def test_migration_idempotent_second_run_noop(tmp_path):
    _legacy_tree(tmp_path / "repo", BASIC)
    assert migrate_legacy(tmp_path / "repo")
    assert migrate_legacy(tmp_path / "repo") == []


def test_migration_never_overwrites_populated_target(tmp_path):
    _legacy_tree(tmp_path / "repo", BASIC)
    target = extracted_dir()
    target.mkdir(parents=True)
    (target / "claude_code").mkdir()
    (target / "claude_code" / "sessions.jsonl").write_text("existing\n")
    actions = migrate_legacy(tmp_path / "repo")
    assert any(a.get("skipped") == "both-populated" for a in actions)
    assert (target / "claude_code" / "sessions.jsonl").read_text() == "existing\n"
    assert (tmp_path / "repo" / "data" / "extracted" / ".salt").exists()


def test_migration_nothing_to_do(tmp_path):
    assert migrate_legacy(tmp_path / "repo") == []


def test_salt_conflict_never_picks_silently(tmp_path):
    _legacy_tree(tmp_path / "repo", {".salt": "legacy-salt", "x/y.jsonl": "{}\n"})
    data_root().mkdir(parents=True, exist_ok=True)
    (data_root() / ".salt").write_text("different-salt")
    actions = migrate_legacy(tmp_path / "repo")
    assert any("CONFLICT" in a for a in actions)
    # both salts kept; nothing deleted
    assert (data_root() / ".salt").read_text() == "different-salt"
    assert (extracted_dir() / ".salt").read_text() == "legacy-salt"


def test_exdev_fallback_verifies_before_removing_source(tmp_path, monkeypatch):
    legacy = _legacy_tree(tmp_path / "repo", BASIC)
    monkeypatch.setattr(os, "rename",
                        lambda *a: (_ for _ in ()).throw(OSError("EXDEV")))
    real_copytree = shutil.copytree

    def lossy_copytree(src, dst, *args, **kw):
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


def test_salt_path_semantics(tmp_path):
    # default tree -> the protected top-level salt (ADR-0012)
    assert salt_path() == data_root() / ".salt"
    assert salt_path(extracted_dir()) == data_root() / ".salt"
    # an explicit --data-dir tree is self-contained
    assert salt_path(tmp_path / "elsewhere") == tmp_path / "elsewhere" / ".salt"


def test_migration_preserves_salt_and_refs_match(tmp_path, monkeypatch):
    """The load-bearing case: refs computed before and after the move must
    join. Uses the real file-salt path (env salt removed) and the full
    migration including the salt lift to the top of the tree."""
    monkeypatch.delenv("CALIPER_HASH_SALT")
    from cli.main import extract
    from connectors.claude_code import ClaudeCodePlugin
    from connectors.util import load_salt

    repo = tmp_path / "repo"
    legacy = repo / "data" / "extracted"
    legacy.mkdir(parents=True)

    def run(data_dir):
        plugin = ClaudeCodePlugin(salt=load_salt(salt_path(data_dir)),
                                  root=FIXTURES / "claude_code")
        extract(["claude_code"], data_dir, SCHEMA, include_content=False,
                plugins_override={"claude_code": plugin})
        recs = [json.loads(l) for l in
                (data_dir / "claude_code" / "sessions.jsonl")
                .read_text().splitlines()]
        return {r["session_id"]: r["project_ref"] for r in recs}

    before = run(legacy)  # legacy tree is self-contained: salt beside it
    salt_before = (legacy / ".salt").read_bytes()

    assert _moved_total(migrate_legacy(repo)) >= 2
    # after migration the default tree resolves to the lifted top-level salt
    assert (data_root() / ".salt").read_bytes() == salt_before

    after = run(extracted_dir())
    assert before == after  # same salt -> same refs -> history still joins


def test_caliper_home_env_override():
    assert str(data_root()).startswith(str(Path(os.environ["CALIPER_HOME"])))
