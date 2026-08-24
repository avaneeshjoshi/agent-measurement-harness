"""The stranger's first run (ADR-0014): an empty or partial machine gets
sentences, never crashes, never fabricated figures, never phantom coverage.
These are the first tests setup_flow has ever had."""

from __future__ import annotations

from pathlib import Path

import pytest

from caliper.connectors.claude_code import ClaudeCodePlugin
from caliper.connectors.codex import CodexPlugin
from caliper.connectors.cursor import CursorPlugin


@pytest.fixture()
def empty_plugins(tmp_path, monkeypatch):
    """PLUGINS wired to roots that don't exist — a machine with no agents."""
    import caliper.connectors as connectors
    fake = {
        "claude_code": lambda salt="": ClaudeCodePlugin(
            root=tmp_path / "no-claude", salt=salt),
        "cursor": lambda salt="": CursorPlugin(
            tracking_db=tmp_path / "no.db", state_db=tmp_path / "no2.db",
            salt=salt),
        "codex": lambda salt="": CodexPlugin(
            root=tmp_path / "no-codex", salt=salt),
    }
    monkeypatch.setattr(connectors, "PLUGINS", fake)
    import caliper.cli.main as main_mod
    monkeypatch.setattr(main_mod, "PLUGINS", fake)
    return fake


def test_setup_on_empty_machine_exits_clean(empty_plugins, capsys):
    """The crash Explorer B found (max() on an empty chart) plus the
    fabricated $1.00 — a truly empty machine must end with one sentence."""
    from caliper.cli.setup_flow import run_setup
    from tests.conftest import REPO

    assert run_setup(REPO, mode="quick") == 0
    out = capsys.readouterr().out
    assert "No agent logs found" in out
    assert "$1.00" not in out          # never a fabricated figure
    assert "$0.00" not in out          # never a zero where absence is meant
    assert "Traceback" not in out
    assert "source not present on this machine" in out


def test_extract_on_empty_machine_says_so(empty_plugins, capsys):
    from caliper.cli.main import main
    assert main(["extract"]) == 0
    out = capsys.readouterr().out
    assert "No agent logs found" in out
    assert "all unchanged" not in out  # absent is not "unchanged"


def test_rotated_logs_read_differently_from_not_installed(tmp_path, capsys):
    """S2 fourth case: the tool exists but its logs rotated away — a
    materially different sentence from 'not installed'."""
    from caliper.cli.main import extract
    from tests.conftest import SCHEMA

    root = tmp_path / "claude"
    (root / "some-project").mkdir(parents=True)  # installed, but no *.jsonl
    m = extract(["claude_code"], tmp_path / "out", SCHEMA,
                include_content=False,
                plugins_override={"claude_code": ClaudeCodePlugin(
                    root=root, salt="test-salt")})
    note = m["sources"]["claude_code"]["notes"]["status"]
    assert "installed" in note and "rotates" in note


def test_report_and_classify_empty_states(empty_plugins, capsys):
    from caliper.cli.main import main
    assert main(["report"]) == 0
    assert "No sessions extracted yet. Run caliper extract." \
        in capsys.readouterr().out
    assert main(["classify"]) == 0
    assert "No prompt units to classify yet" in capsys.readouterr().out
