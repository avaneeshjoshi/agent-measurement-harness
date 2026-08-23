"""`caliper schedule` — install/uninstall/status for the launchd collection
agent (ADR-0011, macOS only; Linux needs a systemd user timer, see the ADR).

Full Disk Access is a choice the user makes, never an assumption: extraction
reads only dotfiles and Cursor's Application Support tree (no TCC), but
scheduled *signals* reads git repos that may live under ~/Documents etc.
Install detects that, states plainly what FDA grants, and offers
extraction-only as the no-permission path. After install the job is
kickstarted once and verified from its own context — a job that installs
green and silently collects nothing is the worst failure mode.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .collection import load_state, save_state
from .paths import extracted_dir, logs_dir, state_dir
from .style import S, box, child, sep, step

LABEL = "dev.caliper.extract"
START_INTERVAL_S = 3600  # hourly while awake; launchd never fires in sleep
                         # and coalesces missed ticks to one run on wake

# TCC-protected roots (path-prefix heuristic, recorded as such in ADR-0011)
_TCC_ROOTS = ("Documents", "Desktop", "Downloads", "Library/Mobile Documents")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def caliper_executable() -> list[str]:
    """Absolute program for launchd (it has no useful PATH). The console
    script's shebang is absolute; fall back to `python -m cli.main`."""
    exe = shutil.which("caliper")
    if exe:
        return [str(Path(exe).resolve())]
    return [sys.executable, "-m", "cli.main"]


def generate_plist(program: list[str], repo_root: Path, log_path: Path) -> bytes:
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [*program, "extract", "--scheduled"],
        "StartInterval": START_INTERVAL_S,
        "RunAtLoad": True,  # login catch-up; the activity gate makes it cheap
        "ProcessType": "Background",
        "LowPriorityBackgroundIO": True,
        "Nice": 10,
        "WorkingDirectory": str(repo_root),
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        # no KeepAlive: a failing job must not respawn-loop (ADR-0011)
    })


def tcc_protected(path: str | Path) -> bool:
    try:
        rel = Path(path).expanduser().resolve().relative_to(Path.home())
    except ValueError:
        return False  # outside the home dir: not user-TCC territory
    return any(str(rel).startswith(root + "/") or str(rel) == root
               for root in _TCC_ROOTS)


def discover_repo_paths() -> list[str]:
    """The git repos the extracted sessions reference — what scheduled
    signals would need to read."""
    from connectors.git_history import GitHistoryConnector
    from connectors.util import load_salt
    try:
        from .paths import salt_path
        conn = GitHistoryConnector(salt=load_salt(salt_path()))
        repos, _ = conn.discover_repos()
        return sorted(str(r) for r in repos)
    except Exception:
        return []


def _launchctl(runner, *args) -> subprocess.CompletedProcess:
    return runner(["launchctl", *args], capture_output=True, text=True)


def choose_mode(repo_paths: list[str], choose=None) -> str | None:
    """The FDA conversation. Returns 'full' | 'extract_only' | None
    (declined). Non-interactive default: extract_only — never assume a
    broad permission grant."""
    protected = [p for p in repo_paths if tcc_protected(p)]
    if protected:
        print(step(f"{len(protected)} of {len(repo_paths)} session repos "
                   "live in macOS-protected folders "
                   + S.dim("(Documents/Desktop/Downloads/iCloud)")))
        print()
        print("    Scheduled outcome signals would need "
              + S.bold("Full Disk Access") + " for the Python runtime —")
        print("    and FDA grants read access to "
              + S.bold("everything on this machine") + ", not just these repos.")
        print()
    options = ["Full collection — hourly sessions + daily git signals"
               + (" (needs Full Disk Access)" if protected else ""),
               "Extraction only — hourly sessions, signals stays manual "
               "(no special permission)"]
    if choose is None:
        from .interactive import choose as choose_fn
        choose = choose_fn
    picked = choose("Question", "How should scheduled collection run?", options)
    if picked is None:  # non-TTY: never silently take the broad grant
        picked = 1
    return "full" if picked == 0 else "extract_only"


def _fda_instructions(runner) -> None:
    binary = str(Path(sys.executable).resolve())
    print(step("Grant Full Disk Access " + S.dim("(System Settings → "
               "Privacy & Security → Full Disk Access)")))
    print()
    print(child("add this binary", S.dim(binary)))
    print()
    _launchctl_ignore = runner(  # best-effort: open the settings pane
        ["open", "x-apple.systempreferences:com.apple.preference"
                 ".security?Privacy_AllFiles"],
        capture_output=True, text=True)
    del _launchctl_ignore


def install(repo_root: Path, mode: str | None = None,
            runner=subprocess.run, choose=None,
            verify_timeout_s: float = 25.0) -> int:
    if sys.platform != "darwin":
        print(S.dim("scheduling is macOS-only for now — Linux needs a "
                    "systemd user timer (ADR-0011)"))
        return 1
    sdir = state_dir()
    if mode is None:
        mode = choose_mode(discover_repo_paths(), choose=choose)
    if mode not in ("full", "extract_only"):
        print(step(sep("Not installed", S.dim("run `caliper schedule "
                                              "install` anytime"))))
        return 0

    log_path = logs_dir() / "extract.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    program = caliper_executable()
    pp = plist_path()
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_bytes(generate_plist(program, repo_root, log_path))

    uid = os.getuid()
    _launchctl(runner, "bootout", f"gui/{uid}/{LABEL}")  # replace-safe
    boot = _launchctl(runner, "bootstrap", f"gui/{uid}", str(pp))
    if boot.returncode != 0:
        print(box(S.bred("launchctl bootstrap failed"), "",
                  S.dim((boot.stderr or boot.stdout or "").strip()[:200])))
        return 1

    state = load_state(sdir)
    state["mode"] = mode
    state["schedule"] = {
        "label": LABEL, "plist_path": str(pp),
        "program": program, "log_path": str(log_path),
        "repo_paths": discover_repo_paths() if mode == "full" else [],
        "installed_at": datetime.now(timezone.utc)
            .isoformat(timespec="seconds"),
    }
    save_state(sdir, state)

    if mode == "full":
        _fda_instructions(runner)
        print()

    # verify from the job's own context: kickstart, then wait for the run's
    # heartbeat to land in state
    before = state.get("last_heartbeat")
    _launchctl(runner, "kickstart", "-k", f"gui/{uid}/{LABEL}")
    deadline = time.monotonic() + verify_timeout_s
    heartbeat = None
    while time.monotonic() < deadline:
        current = load_state(sdir).get("last_heartbeat")
        if current and current != before:
            heartbeat = current
            break
        time.sleep(0.5)

    if heartbeat:
        alarms = load_state(sdir).get("pending_alarms", [])
        checks = [a for a in alarms if a.get("kind") == "self_check"]
        if checks:
            print(box(S.byellow("Installed, but the job reported problems"),
                      "", *(S.dim(a["detail"]) for a in checks), "",
                      S.dim(f"log: {log_path}")))
            return 1
        print(step(sep(S.bgreen("Scheduled collection verified"),
                       S.dim(f"hourly · {'full' if mode == 'full' else 'extraction only'}"),
                       S.dim(f"log: {log_path}"))))
        print()
        return 0
    print(box(S.bred("Installed but NOT verified — the job has not "
                     "reported back"),
              "",
              S.dim("A job that installs green and silently collects "
                    "nothing is the failure this check exists for."),
              S.dim(f"Check the log: {log_path}"),
              S.dim("Or fall back: caliper schedule install "
                    "--extract-only")))
    return 1


def uninstall(runner=subprocess.run) -> int:
    data_dir = state_dir()
    _launchctl(runner, "bootout", f"gui/{os.getuid()}/{LABEL}")
    pp = plist_path()
    if pp.exists():
        pp.unlink()
    state = load_state(data_dir)
    state["schedule"] = None
    save_state(data_dir, state)
    print(step(sep("Scheduled collection removed",
                   S.dim("state and collected data are untouched"))))
    return 0


def status(runner=subprocess.run) -> int:
    data_dir = state_dir()
    state = load_state(data_dir)
    sched = state.get("schedule")
    if not sched:
        print(step(sep("No scheduled collection",
                       S.dim("install with") + " "
                       + S.accent("caliper schedule install"))))
        return 0
    problems = []
    if not Path(sched["plist_path"]).exists():
        problems.append("plist file is missing — reinstall")
    prog = sched.get("program") or [""]
    if prog and not Path(prog[0]).exists():
        problems.append(f"program vanished ({prog[0]}) — a Python upgrade? "
                        "reinstall")
    # the job must still be able to write where it should (ADR-0012)
    from .paths import extracted_dir as _ex
    for tree_name, d in (("extracted", _ex()), ("state", state_dir())):
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_probe"
            probe.write_text("")
            probe.unlink()
        except OSError as exc:
            problems.append(f"cannot write the {tree_name} tree ({d}): {exc}")
    out = _launchctl(runner, "print", f"gui/{os.getuid()}/{sched['label']}")
    run_state = exit_code = None
    if out.returncode == 0:
        for line in out.stdout.splitlines():
            line = line.strip()
            if line.startswith("state ="):
                run_state = line.split("=", 1)[1].strip()
            elif line.startswith("last exit code ="):
                exit_code = line.split("=", 1)[1].strip()
    else:
        problems.append("job is not loaded in launchd — reinstall")
    if exit_code not in (None, "0", "(never exited)"):
        problems.append(f"last run exited {exit_code} — see the log")

    print(box(S.bold("caliper schedule"),
              sep(S.accent(sched["label"]),
                  S.dim(f"mode {state.get('mode') or 'extract_only'}"),
                  S.dim(run_state or "not loaded"))))
    print()
    print(child("heartbeat", S.dim(state.get("last_heartbeat") or "never")))
    print()
    for src, ts in sorted((state.get("last_covered") or {}).items()):
        print(child(src, S.dim(f"covered {ts}")))
        print()
    for a in state.get("pending_alarms", []):
        print(child(a.get("source", "?"),
                    S.byellow(a.get("kind", "alarm")),
                    S.dim(str(a.get("detail", ""))[:80])))
        print()
    print(S.dim(f"→ log: {sched.get('log_path')}"))
    if problems:
        print()
        for p in problems:
            print(step(S.bred(p)))
        return 1
    return 0
