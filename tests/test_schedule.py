"""launchd scheduling (ADR-0011) — plist generation, install/uninstall
against an injectable launchctl runner, TCC detection, and the loud
not-verified path. No test ever calls the real launchctl or touches the
real ~/Library."""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

import caliper.cli.schedule as schedule
from caliper.cli.collection import load_state, save_state
from caliper.cli.paths import state_dir


class FakeRunner:
    def __init__(self, fail_verbs=(), print_stdout="", side_effect=None):
        self.calls: list[list[str]] = []
        self.fail_verbs = set(fail_verbs)
        self.print_stdout = print_stdout
        self.side_effect = side_effect

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.side_effect:
            self.side_effect(cmd)
        verb = cmd[1] if cmd[0] == "launchctl" else cmd[0]
        rc = 1 if verb in self.fail_verbs else 0
        out = self.print_stdout if verb == "print" else ""
        return subprocess.CompletedProcess(cmd, rc, out, "")

    def verbs(self):
        return [c[1] for c in self.calls if c[0] == "launchctl"]


@pytest.fixture()
def darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(schedule, "plist_path",
                        lambda: tmp_path / f"{schedule.LABEL}.plist")
    monkeypatch.setattr(schedule, "discover_repo_paths", lambda: [])
    return tmp_path


def test_plist_roundtrips_with_expected_keys(tmp_path):
    raw = schedule.generate_plist(["/usr/local/bin/caliper"],
                                  tmp_path / "x.log")
    p = plistlib.loads(raw)
    assert p["Label"] == schedule.LABEL
    assert p["ProgramArguments"] == ["/usr/local/bin/caliper",
                                     "extract", "--scheduled"]
    assert p["StartInterval"] == schedule.START_INTERVAL_S
    assert p["ProcessType"] == "Background"
    assert p["LowPriorityBackgroundIO"] is True
    assert "KeepAlive" not in p  # failures must not respawn-loop


def test_caliper_executable_is_absolute():
    prog = schedule.caliper_executable()
    assert Path(prog[0]).is_absolute()


def test_tcc_prefix_detection():
    home = Path.home()
    assert schedule.tcc_protected(home / "Documents" / "work" / "repo")
    assert schedule.tcc_protected(home / "Desktop")
    assert schedule.tcc_protected(home / "Library" / "Mobile Documents" / "x")
    assert not schedule.tcc_protected(home / "code" / "repo")
    assert not schedule.tcc_protected("/opt/repo")


def test_install_bootout_then_bootstrap_and_state(darwin):
    def kick_writes_heartbeat(cmd):
        if cmd[:2] == ["launchctl", "kickstart"]:
            st = load_state(state_dir())
            st["last_heartbeat"] = "2026-08-23T12:00:00+00:00"
            save_state(state_dir(), st)

    runner = FakeRunner(side_effect=kick_writes_heartbeat)
    rc = schedule.install(mode="extract_only", runner=runner)
    assert rc == 0
    assert runner.verbs() == ["bootout", "bootstrap", "kickstart"]
    assert schedule.plist_path().exists()
    state = load_state(state_dir())
    assert state["mode"] == "extract_only"
    assert state["schedule"]["label"] == schedule.LABEL


def test_install_unverified_is_loud_nonzero(darwin, capsys):
    rc = schedule.install(mode="extract_only",
                          runner=FakeRunner(), verify_timeout_s=0.1)
    assert rc == 1
    assert "NOT verified" in capsys.readouterr().out


def test_install_bootstrap_failure_reported(darwin, capsys):
    rc = schedule.install(mode="extract_only",
                          runner=FakeRunner(fail_verbs={"bootstrap"}))
    assert rc == 1
    assert "bootstrap failed" in capsys.readouterr().out


def test_install_refuses_off_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert schedule.install(mode="extract_only",
                            runner=FakeRunner()) == 1


def test_uninstall_bootout_unlink_and_state_clear(darwin):
    schedule.plist_path().write_bytes(b"x")
    st = load_state(state_dir())
    st["schedule"] = {"label": schedule.LABEL}
    save_state(state_dir(), st)
    runner = FakeRunner()
    assert schedule.uninstall(runner=runner) == 0
    assert "bootout" in runner.verbs()
    assert not schedule.plist_path().exists()
    assert load_state(state_dir())["schedule"] is None


def _seed_installed(tmp_path, program):
    pp = tmp_path / f"{schedule.LABEL}.plist"
    pp.write_bytes(b"x")
    st = load_state(state_dir())
    st["mode"] = "extract_only"
    st["schedule"] = {"label": schedule.LABEL, "plist_path": str(pp),
                      "program": program, "log_path": "/tmp/x.log"}
    save_state(state_dir(), st)


def test_status_parses_bad_exit_code(darwin, capsys):
    _seed_installed(darwin, [sys.executable])
    runner = FakeRunner(print_stdout="\tstate = waiting\n"
                                     "\tlast exit code = 78\n")
    assert schedule.status(runner=runner) == 1
    assert "exited 78" in capsys.readouterr().out


def test_status_warns_on_vanished_program(darwin, capsys):
    _seed_installed(darwin, ["/no/such/binary"])
    runner = FakeRunner(print_stdout="\tstate = waiting\n"
                                     "\tlast exit code = 0\n")
    assert schedule.status(runner=runner) == 1
    assert "vanished" in capsys.readouterr().out


def test_status_healthy(darwin, capsys):
    _seed_installed(darwin, [sys.executable])
    runner = FakeRunner(print_stdout="\tstate = waiting\n"
                                     "\tlast exit code = 0\n")
    assert schedule.status(runner=runner) == 0


def test_status_verifies_write_access(darwin, capsys, monkeypatch):
    """`caliper schedule status` must prove the job can still write where it
    should (ADR-0012) — an unwritable tree is a loud problem, not a shrug."""
    import os as _os

    from caliper.cli.paths import extracted_dir
    _seed_installed(darwin, [sys.executable])
    runner = FakeRunner(print_stdout="\tstate = waiting\n"
                                     "\tlast exit code = 0\n")
    ex = extracted_dir()
    ex.mkdir(parents=True, exist_ok=True)
    _os.chmod(ex, 0o500)
    try:
        assert schedule.status(runner=runner) == 1
        assert "cannot write the extracted tree" in capsys.readouterr().out
    finally:
        _os.chmod(ex, 0o755)
    assert schedule.status(runner=runner) == 0
