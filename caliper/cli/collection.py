"""Continuous-collection runtime (ADR-0011): the collection state file, the
extraction lock, the activity gate / mtime watermark, and the scheduled
runner behind `caliper extract --scheduled`.

Scheduled output is plain timestamped lines — stdout goes to the launchd log
(~/.caliper/logs/extract.log), not a terminal.
"""

from __future__ import annotations

import fcntl
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .health import STATE_FILENAME

# ADR-0011: clock-skew slack on the mtime gate — artifacts stamped up to an
# hour before the watermark are still re-examined.
WATERMARK_SLACK_S = 3600
# ADR-0011: incremental runs cannot see cross-file fork families; a daily
# full (no-watermark) pass re-derives them, bounding fork_of staleness <24h.
FULL_PASS_INTERVAL_S = 24 * 3600

LOCK_FILENAME = ".extract.lock"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- state ----------------------------------------------------------------

def _default_state() -> dict:
    return {"version": 1, "include_content": False, "schedule": None,
            "last_heartbeat": None, "last_full_pass": None,
            "last_covered": {}, "watermark": {}, "pending_alarms": []}


def load_state(data_dir: Path) -> dict:
    p = data_dir / STATE_FILENAME
    if p.exists():
        try:
            state = json.loads(p.read_text())
            return {**_default_state(), **state}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"warning: corrupt {p.name} ({exc!r}) — starting fresh")
    return _default_state()


def save_state(data_dir: Path, state: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = data_dir / (STATE_FILENAME + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    os.replace(tmp, data_dir / STATE_FILENAME)


def mark_covered(data_dir: Path, source_names: list[str],
                 run_start: datetime, full: bool) -> None:
    """Record that a run fully covered these sources — manual runs count
    exactly like scheduled ones (a manual full run is the best coverage
    evidence there is)."""
    state = load_state(data_dir)
    iso = run_start.isoformat(timespec="seconds")
    for name in source_names:
        state["last_covered"][name] = iso
        state["watermark"][name] = run_start.timestamp()
    state["last_heartbeat"] = iso
    if full:
        state["last_full_pass"] = iso
    save_state(data_dir, state)


# ---- lock -----------------------------------------------------------------

def acquire_lock(data_dir: Path):
    """Non-blocking flock on the shared extract lock. The kernel releases it
    on process death — no stale-pid detection needed. Returns the open file
    (hold it for the run's duration) or None if another extract holds it.
    Also serializes content.jsonl appends, which are not atomic."""
    data_dir.mkdir(parents=True, exist_ok=True)
    fh = open(data_dir / LOCK_FILENAME, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps({"pid": os.getpid(),
                         "started_at": _now().isoformat(timespec="seconds")}))
    fh.flush()
    return fh


# ---- activity gate / watermark -------------------------------------------

def artifact_mtime(path: Path) -> float:
    """mtime including SQLite -wal/-shm siblings: Cursor's WAL can absorb
    hours of writes without touching the main DB file's mtime."""
    mt = path.stat().st_mtime
    for suffix in ("-wal", "-shm"):
        sib = Path(str(path) + suffix)
        if sib.exists():
            mt = max(mt, sib.stat().st_mtime)
    return mt


def _any_activity(discovered: dict[str, list | None],
                  watermark: dict[str, float]) -> bool:
    """True when any source has an artifact newer than its watermark (minus
    slack), has never been covered, or could not be checked — only a
    verified-idle scan may claim there is nothing to do."""
    for name, artifacts in discovered.items():
        if artifacts is None:
            return True  # discover failed: cannot verify idle
        wm = watermark.get(name)
        if wm is None:
            if artifacts:
                return True  # never covered, artifacts exist
            continue
        for a in artifacts:
            try:
                if artifact_mtime(a.path) >= wm - WATERMARK_SLACK_S:
                    return True
            except OSError:
                return True
    return False


# ---- the scheduled runner -------------------------------------------------

def _log(msg: str) -> None:
    print(f"[{_now():%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def run_scheduled(root: Path, plugins_override: dict | None = None) -> int:
    """`caliper extract --scheduled`: lock → self-check → activity gate →
    (watermarked or daily-full) extract → state update. Exit 0 on no-op or
    success; 1 on failure (visible in `launchctl print` and the log)."""
    from caliper.connectors import PLUGINS
    from caliper.connectors.util import load_salt

    from .main import extract, repo_root
    from .paths import extracted_dir, state_dir

    data_dir = extracted_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    sdir = state_dir()
    lock = acquire_lock(sdir)
    if lock is None:
        _log("skip: another extract holds the lock")
        return 0
    try:
        state = load_state(sdir)
        now = _now()
        iso = now.isoformat(timespec="seconds")

        # self-check: a job that installs green and silently collects
        # nothing is the worst failure mode (ADR-0011) — verify we can
        # write, and that every source can at least be discovered
        alarms = [a for a in state.get("pending_alarms", [])
                  if a.get("kind") != "self_check"]
        try:
            probe = data_dir / ".write_probe"
            probe.write_text("")
            probe.unlink()
        except OSError as exc:
            _log(f"FAILED self-check: data dir not writable: {exc!r}")
            return 1

        from .paths import salt_path
        salt = load_salt(salt_path(data_dir))
        plugins = plugins_override or \
            {name: cls(salt=salt) for name, cls in PLUGINS.items()}
        discovered: dict[str, list | None] = {}
        for name, plugin in plugins.items():
            try:
                discovered[name] = plugin.discover()
            except Exception as exc:
                discovered[name] = None
                alarms.append({"key": f"{name}:self_check:discover",
                               "source": name, "kind": "self_check",
                               "detail": f"discover() failed: {exc!r}",
                               "raised_at": iso})
                _log(f"{name}: discover failed: {exc!r}")

        # FDA read check (ADR-0011 decision 6): in full mode, verify the
        # background context can actually read the repos signals needs —
        # TCC denials never prompt from launchd, they just fail
        if state.get("mode") == "full":
            for repo in ((state.get("schedule") or {})
                         .get("repo_paths") or [])[:5]:
                try:
                    os.scandir(repo).close()
                except PermissionError:
                    alarms.append({
                        "key": f"signals:self_check:fda:{repo}",
                        "source": "signals", "kind": "self_check",
                        "detail": (f"cannot read {repo} from the background "
                                   "job — grant Full Disk Access to the "
                                   "Python runtime, or reinstall with "
                                   "`caliper schedule install --extract-only`"),
                        "raised_at": iso})
                    _log(f"self-check: cannot read {repo} (TCC) — "
                         "Full Disk Access missing")
                except OSError:
                    pass  # deleted/moved repo is not a permission problem
        state["pending_alarms"] = alarms

        last_full = state.get("last_full_pass")
        full = (last_full is None
                or (now - datetime.fromisoformat(last_full)).total_seconds()
                > FULL_PASS_INTERVAL_S)

        if not full and not _any_activity(discovered,
                                          state.get("watermark") or {}):
            state["last_heartbeat"] = iso
            for name, arts in discovered.items():
                if arts is not None:
                    # a verified-idle scan IS coverage: nothing new existed
                    state["last_covered"][name] = iso
            save_state(sdir, state)
            _log("idle: no new activity across sources — heartbeat only")
            return 0

        since = None if full else dict(state.get("watermark") or {})
        from .paths import schema_path
        schema = schema_path("session.schema.json")
        manifest = extract(list(plugins), data_dir, schema,
                           include_content=bool(state.get("include_content")),
                           plugins_override=plugins_override,
                           since=since, trigger="scheduled")

        for name, src in manifest["sources"].items():
            bad_discover = any(s.get("path") == "<discover>"
                               for s in src["skipped"])
            if not bad_discover:
                state["last_covered"][name] = iso
                state["watermark"][name] = now.timestamp()
        state["last_heartbeat"] = iso
        if full:
            state["last_full_pass"] = iso
        save_state(sdir, state)

        # canaries run after the state save — evaluate_canaries reloads and
        # merges state itself, so this order never clobbers its alarms
        from .health import evaluate_canaries
        for alarm in evaluate_canaries(data_dir, manifest, now=now):
            _log(f"DRIFT ALARM {alarm['key']}: {alarm['detail']}")

        # full mode: the daily full pass also refreshes outcome signals —
        # the FDA-gated half of scheduled collection (ADR-0011 decision 6)
        if full and state.get("mode") == "full":
            try:
                from .main import signals as run_signals
                sm = run_signals(data_dir,
                                 schema_path("production_signal.schema.json"))
                _log(f"signals: {sm['records']['emitted']} records across "
                     f"{len(sm['repos'])} repos")
            except Exception as exc:
                _log(f"signals FAILED: {exc!r}")
                st2 = load_state(sdir)
                st2["pending_alarms"] = [
                    a for a in st2.get("pending_alarms", [])
                    if a.get("key") != "signals:self_check:run"]
                st2["pending_alarms"].append({
                    "key": "signals:self_check:run", "source": "signals",
                    "kind": "self_check",
                    "detail": f"scheduled signals run failed: {exc!r}",
                    "raised_at": iso})
                save_state(sdir, st2)

        parts = []
        for name, src in manifest["sources"].items():
            r = src["records"]
            parts.append(f"{name} {r['new']}n/{r['updated']}u/"
                         f"{r['unchanged']}=")
        _log(("extracted (full pass): " if full else "extracted: ")
             + ", ".join(parts)
             + f" — manifest {manifest['run_id']}")
        return 0
    except Exception:
        _log("FAILED:\n" + traceback.format_exc())
        return 1
    finally:
        lock.close()
