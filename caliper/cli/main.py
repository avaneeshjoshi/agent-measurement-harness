"""caliper — Caliper's CLI. v0 ships one subcommand: extract.

    caliper extract                          # all detected sources
    caliper extract --source claude-code
    caliper extract --source claude-code,cursor,codex
    caliper extract --include-content        # also write content sidecars

Hard rules enforced here:
- Read-only on all sources (plugins never mutate originals; SQLite is
  snapshot-copied before opening).
- Every emitted record must validate against schemas/session.schema.json;
  invalid records are logged to the manifest and NOT written.
- Idempotent: re-runs dedupe by provenance.content_hash.
- Prompt text / file contents are dropped unless --include-content, and even
  then go to a sidecar file, never into session records.
- Malformed files are logged and skipped, never fatal.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from caliper.connectors import PLUGINS, normalize_source_name
from caliper.connectors.util import load_salt, now_iso

from .store import ContentStore, SessionStore


def repo_root() -> Path:
    """The repo this package was installed (editable) from — three levels up
    from caliper/cli/main.py. Under a wheel install this points into
    site-packages and the repo-side paths simply don't exist there."""
    return Path(__file__).resolve().parent.parent.parent


def load_validator(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def extract(sources: list[str], data_dir: Path, schema_path: Path,
            include_content: bool, plugins_override: dict | None = None,
            since: dict[str, float] | None = None,
            trigger: str = "manual") -> dict:
    """Run extraction. Returns the manifest dict. plugins_override lets tests
    inject plugins pointed at fixture roots. `since` is the per-source mtime
    watermark (ADR-0011): artifacts older than it (minus slack) are filtered
    so scheduled runs are O(new) — safe because the store merges from
    existing records, so filtered files lose nothing."""
    from caliper.connectors.base import CONNECTOR_VERSION, SESSION_SCHEMA_VERSION

    from .collection import WATERMARK_SLACK_S, artifact_mtime
    from .paths import salt_path

    validator = load_validator(schema_path)
    from .paths import schema_path as _schema_by_name
    unit_validator = load_validator(_schema_by_name("prompt_unit.schema.json"))
    salt = load_salt(salt_path(data_dir))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]

    manifest: dict = {
        "run_id": run_id,
        "started_at": now_iso(),
        "include_content": include_content,
        "schema": schema_path.name,
        # version stamps: canary baselines only pool same-version runs, so a
        # contract bump's re-emit storm resets the baseline, never trips it
        "trigger": trigger,
        "connector_version": CONNECTOR_VERSION,
        "schema_version": SESSION_SCHEMA_VERSION,
        "sources": {},
    }

    for name in sources:
        if plugins_override and name in plugins_override:
            plugin = plugins_override[name]
        else:
            plugin = PLUGINS[name](salt=salt)

        src_manifest = {
            "artifacts_discovered": 0,
            "artifacts_read": 0,
            "records": {"emitted": 0, "new": 0, "updated": 0, "unchanged": 0,
                        "invalid": 0},
            "skipped": [],
            "validation_errors": [],
            "date_range": {"earliest_started_at": None, "latest_ended_at": None},
            "notes": {},
        }
        manifest["sources"][name] = src_manifest

        try:
            artifacts = plugin.discover()
        except Exception as exc:  # discovery failure is per-source, never fatal
            src_manifest["skipped"].append({"path": "<discover>", "reason": repr(exc)})
            continue
        src_manifest["artifacts_discovered"] = len(artifacts)
        if not artifacts:
            if getattr(plugin, "root_present", False):
                # the tool exists here; its logs don't (S2 fourth case) —
                # for claude code that usually means rotation (ADR-0011)
                if name == "claude_code":
                    src_manifest["notes"]["status"] = (
                        "installed, but no session logs remain — claude code "
                        "rotates logs after ~30 days; collecting forward "
                        "from now")
                else:
                    src_manifest["notes"]["status"] = (
                        "installed, but no session logs were found")
            else:
                src_manifest["notes"]["status"] =                     "source not present on this machine"
            continue

        if since is not None and since.get(name) is not None:
            cutoff = since[name] - WATERMARK_SLACK_S
            fresh = []
            for a in artifacts:
                try:
                    stale = artifact_mtime(a.path) < cutoff
                except OSError:
                    stale = False  # can't stat: examine it rather than skip
                if not stale:
                    fresh.append(a)
            filtered = len(artifacts) - len(fresh)
            if filtered:
                src_manifest["notes"]["artifacts_filtered_by_watermark"] = filtered
            artifacts = fresh
            if not artifacts:
                continue  # nothing new; records on disk are untouched

        store = SessionStore(data_dir / name)
        unit_store = SessionStore(data_dir / name, filename="prompt_units.jsonl",
                                  key=lambda r: f"{r['session_id']}#{r['turn_index']}")
        content_store = ContentStore(data_dir / name) if include_content else None

        emissions = []
        for artifact in artifacts:
            try:
                emissions.extend(plugin.emit(artifact, include_content=include_content))
                src_manifest["artifacts_read"] += 1
            except Exception as exc:  # unreadable artifact: logged, skipped
                plugin.skip(artifact.path, f"emit failed: {exc!r}")
            for key, val in artifact.extra.items():
                if key in ("scored_commits", "ai_code_hash_rows"):
                    src_manifest["notes"][key] = val

        emissions = plugin.finalize(emissions)

        for emission in emissions:
            rec = emission.record
            errors = sorted(validator.iter_errors(rec), key=lambda e: e.json_path)
            if errors:
                src_manifest["records"]["invalid"] += 1
                src_manifest["validation_errors"].append({
                    "session_id": rec.get("session_id"),
                    "errors": [f"{e.json_path}: {e.message}" for e in errors[:5]],
                })
                continue
            outcome = store.upsert(rec)
            src_manifest["records"]["emitted"] += 1
            src_manifest["records"][outcome] += 1
            for unit in emission.prompt_units:
                # write-time validation, same contract as session records —
                # units used to skip this entirely, which let foreign log
                # shapes write schema-invalid rows silently (ADR-0014 / C4)
                if any(True for _ in unit_validator.iter_errors(unit)):
                    n = src_manifest["notes"].get("prompt_units_invalid", 0)
                    src_manifest["notes"]["prompt_units_invalid"] = n + 1
                    continue
                # units ride the session's idempotency: unchanged sessions
                # were skipped upstream, so any unit reaching here is fresh
                unit_store._merged[unit_store.key(unit)] = unit
            if content_store and emission.content_rows:
                content_store.add(emission.content_rows)

            s, e = rec.get("started_at"), rec.get("ended_at")
            dr = src_manifest["date_range"]
            if s and (dr["earliest_started_at"] is None or s < dr["earliest_started_at"]):
                dr["earliest_started_at"] = s
            if e and (dr["latest_ended_at"] is None or e > dr["latest_ended_at"]):
                dr["latest_ended_at"] = e

        src_manifest["sessions_on_disk"] = store.write()
        if unit_store._merged:
            src_manifest["prompt_units_on_disk"] = unit_store.write()
        if content_store:
            src_manifest["content_rows_written"] = content_store.write()
        src_manifest["skipped"] = [asdict(s) for s in plugin.skips]
        partial = getattr(plugin, "partial_note", None)
        if partial:
            src_manifest["notes"]["status"] = partial
        # drift instrumentation (ADR-0011): shapes the connector didn't
        # recognize, and the denominator for rate comparisons
        if getattr(plugin, "unknowns", None):
            src_manifest["notes"]["unknown_record_types"] = \
                dict(sorted(plugin.unknowns.items()))
        if getattr(plugin, "raw_records_seen", 0):
            src_manifest["notes"]["raw_records_seen"] = plugin.raw_records_seen

    manifest["finished_at"] = now_iso()
    manifest_dir = data_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{run_id}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def signals(data_dir: Path, schema_path: Path,
            connector=None) -> dict:
    """Run the git-history connector: production signals for the repos the
    extracted sessions reference. Returns the manifest. `connector` lets
    tests inject one pointed at fixture roots."""
    from caliper.connectors.git_history import GitHistoryConnector

    from .paths import salt_path

    validator = load_validator(schema_path)
    from .paths import schema_path as _schema_by_name
    unit_validator = load_validator(_schema_by_name("prompt_unit.schema.json"))
    salt = load_salt(salt_path(data_dir))
    conn = connector or GitHistoryConnector(salt=salt)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    manifest: dict = {"run_id": run_id, "kind": "signals",
                      "started_at": now_iso(), "schema": schema_path.name,
                      "repos": {}, "records": {"emitted": 0, "new": 0,
                                               "updated": 0, "unchanged": 0,
                                               "invalid": 0},
                      "validation_errors": [], "skipped": []}

    repos, cwd_to_root = conn.discover_repos()
    store = SessionStore(data_dir / "git_history",
                         filename="production_signals.jsonl",
                         key=lambda r: r["change_ref"]["repo_ref"] + ":" +
                                       r["change_ref"]["commit_sha"])
    all_records: list[dict] = []
    for root, tools in sorted(repos.items()):
        try:
            records = conn.analyze_repo(root)
        except Exception as exc:  # malformed repo: logged, never fatal
            conn.skip(root, f"analysis failed: {exc!r}")
            continue
        repo_ref = records[0]["change_ref"]["repo_ref"] if records else None
        agg = _aggregate_repo(records)
        manifest["repos"][repo_ref or root] = {
            "tools_referencing": sorted(tools),
            "commits_analyzed": len(records), **agg,
        }
        all_records.extend(records)

    for rec in all_records:
        errors = sorted(validator.iter_errors(rec), key=lambda e: e.json_path)
        if errors:
            manifest["records"]["invalid"] += 1
            manifest["validation_errors"].append({
                "key": rec["change_ref"]["commit_sha"],
                "errors": [f"{e.json_path}: {e.message}" for e in errors[:5]]})
            continue
        outcome = store.upsert(rec)
        manifest["records"]["emitted"] += 1
        manifest["records"][outcome] += 1

    manifest["signals_on_disk"] = store.write()

    # session -> repo/commit join, per tool
    sessions_by_tool: dict[str, list[dict]] = {}
    for tool in ("claude_code", "cursor", "codex"):
        path = data_dir / tool / "sessions.jsonl"
        if path.exists():
            sessions_by_tool[tool] = [json.loads(l) for l in
                                      path.read_text().splitlines() if l.strip()]
    manifest["session_join"] = conn.session_join_stats(
        sessions_by_tool, cwd_to_root, all_records)

    manifest["skipped"] = conn.skips
    manifest["finished_at"] = now_iso()
    manifest_dir = data_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{run_id}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _aggregate_repo(records: list[dict]) -> dict:
    """Per-repo aggregate for the manifest: rates over measured commits only."""
    def frac(n, d):
        return round(n / d, 3) if d else None

    surv = {h: {"lines_orig": 0, "lines_surv": 0, "commits": 0} for h in (30, 60, 90)}
    rework_measured = rework_occurred = 0
    reverted = 0
    attr = {"known": 0, "partial": 0, "unknown": 0}
    for r in records:
        for s in r["survival"]:
            if s["status"] == "measured":
                h = s["horizon_days"]
                surv[h]["commits"] += 1
                surv[h]["lines_orig"] += s["lines_original"]
                surv[h]["lines_surv"] += s["lines_surviving"]
        rw = r.get("rework")
        if rw and rw["status"] == "measured":
            rework_measured += 1
            if rw["occurred"]:
                rework_occurred += 1
        if r["revert"]["reverted"]:
            reverted += 1
        attr[r["ai_attribution"]["status"]] += 1
    return {
        "survival": {str(h): {"commits_measured": v["commits"],
                              "line_survival_rate": frac(v["lines_surv"], v["lines_orig"])}
                     for h, v in surv.items()},
        "rework": {"commits_measured": rework_measured,
                   "occurred": rework_occurred,
                   "rate": frac(rework_occurred, rework_measured)},
        "reverted_commits": reverted,
        "attribution": attr,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caliper",
                                     description="Caliper: coding-agent traffic measurement.",
                                     epilog="start with: caliper setup")
    from importlib.metadata import version as _pkg_version
    parser.add_argument("--version", action="version",
                        version=f"caliper {_pkg_version('caliper')}")
    sub = parser.add_subparsers(dest="command")

    p_extract = sub.add_parser("extract", help="Extract sessions from local agent logs.")
    p_extract.add_argument("--source", default=None,
                           help="Comma-separated: claude-code,cursor,codex. Default: all detected.")
    p_extract.add_argument("--include-content",
                           action="store_true",
                           help="Also write prompt text to a content sidecar "
                                "(dropped by default; session records stay content-free).")
    p_extract.add_argument("--data-dir", default=None,
                           help="Output root (default: ~/.caliper/extracted).")
    p_extract.add_argument("--scheduled", action="store_true",
                           help=argparse.SUPPRESS)  # the launchd entry (ADR-0011)

    p_signals = sub.add_parser("signals",
                               help="Compute production signals from local git "
                                    "repos referenced by extracted sessions.")
    p_signals.add_argument("--data-dir", default=None,
                           help="Output root (default: ~/.caliper/extracted).")
    p_signals.add_argument("--repo", action="append", default=[],
                           help="Additional repo path(s) to analyze.")

    p_replay = sub.add_parser("replay",
                              help="Replay mined tasks across model tiers "
                                   "(dev: source checkout + real API spend).")
    p_replay.add_argument("action", choices=["mine", "run"])
    p_replay.add_argument("--repo", default=str(Path.home() / "caliper-eval" / "commons-lang"))
    p_replay.add_argument("--tasks", default=str(Path.home() / "caliper-eval" / "tasks" / "tasks.jsonl"))
    p_replay.add_argument("--models", default="claude-fable-5:frontier,claude-haiku-4-5:small",
                          help="Comma list of model_id:tier pairs.")
    p_replay.add_argument("--limit", type=int, default=None,
                          help="Run only the first N tasks (pilot gate).")
    p_replay.add_argument("--target-n", type=int, default=30)
    p_replay.add_argument("--out", default=None)

    p_classify = sub.add_parser("classify",
                                help="Label extracted traffic (harness/classifier).")
    p_classify.add_argument("--unit", default="all",
                            choices=["prompt", "segment", "session", "all"])
    p_classify.add_argument("--data-dir", default=None)
    p_classify.add_argument("--out", default=None)
    p_classify.add_argument("--validate", action="store_true",
                            help="after classifying, measure agreement "
                                 "against the human calibration labels and "
                                 "write the report (ADR-0009/0013)")

    p_report = sub.add_parser("report",
                              help="Generate the self-contained first-look HTML.")
    p_report.add_argument("--out", default=None)

    p_pricing = sub.add_parser("pricing",
                               help="Price-sheet management (dev: source checkout).")
    p_pricing.add_argument("action", choices=["update"])

    p_setup = sub.add_parser("setup", help="First-run setup: trust screen, "
                                            "backfill, first look.")
    p_setup.add_argument("--full", action="store_true",
                         help="full backfill without asking (incl. git signals)")
    p_setup.add_argument("--quick", action="store_true",
                         help="quick backfill without asking (sessions only)")

    p_schedule = sub.add_parser("schedule",
                                help="Manage the hourly background "
                                     "collection job (launchd, ADR-0011).")
    p_schedule.add_argument("action", nargs="?", default="status",
                            choices=["install", "uninstall", "status"])
    sgrp = p_schedule.add_mutually_exclusive_group()
    sgrp.add_argument("--full", action="store_true",
                      help="hourly sessions + daily git signals "
                           "(may need Full Disk Access)")
    sgrp.add_argument("--extract-only", action="store_true",
                      help="hourly sessions only; no special permission")

    sub.add_parser("uninstall",
                   help="Remove the scheduled job and show where your data "
                        "lives and how to delete it.")

    p_policy = sub.add_parser("policy",
                              help="Review the routing policy against your "
                                   "traffic (dev preview: needs eval "
                                   "evidence from your own traffic).")
    p_policy.add_argument("action", nargs="?", choices=["apply"],
                          help="'apply' accepts the policy without the review flow")
    grp = p_policy.add_mutually_exclusive_group()
    grp.add_argument("--yes", action="store_true", help="apply without asking")
    grp.add_argument("--no", action="store_true", help="decline without asking")

    args = parser.parse_args(argv)

    from .paths import (data_root, derived_dir, extracted_dir,
                        migrate_legacy, reports_dir, state_dir)
    actions = migrate_legacy(repo_root())
    if actions:
        from .style import S as _S, sep as _sep, step as _step
        moved = sum(a.get("moved", 0) for a in actions) \
            + sum(1 for a in actions if "deduped" in a)
        if moved:
            print(_step(_sep("Migrated data home",
                             _S.dim(str(data_root())),
                             _S.dim(f"{moved} files"))))
            print()
        for a in actions:
            if "skipped" in a:
                print(_S.dim(f"note: {a['legacy']} and {a['target']} are both "
                             "populated — using the latter; remove the legacy "
                             "copy to silence this"))
                print()
            elif "CONFLICT" in a:
                print(_S.bred(f"CONFLICT: {a['CONFLICT']} — {a['detail']} "
                              f"({a['legacy']} vs {a['target']})"))
                print()

    if args.command == "extract" and args.scheduled:
        from .collection import run_scheduled
        return run_scheduled(repo_root())

    # Gap warning on every interactive invocation (ADR-0011). Suppressed for
    # setup (it is about to backfill) and scheduled runs (they ARE the
    # collector — the gap still lands in their log via state).
    if args.command != "setup":
        from .health import health_nudge
        health_nudge()

    if args.command == "setup":
        from .setup_flow import run_setup
        mode = "full" if args.full else ("quick" if args.quick else None)
        return run_setup(repo_root(), mode=mode)

    if args.command == "policy":
        from .policy_flow import run_policy_flow
        apply_now = args.yes or args.action == "apply"
        return run_policy_flow(repo_root(), yes=apply_now, no=args.no)

    if args.command == "uninstall":
        from .schedule import full_uninstall
        return full_uninstall()

    if args.command == "schedule":
        from .schedule import install, status, uninstall
        if args.action == "install":
            mode = "full" if args.full else \
                ("extract_only" if args.extract_only else None)
            return install(mode=mode)
        if args.action == "uninstall":
            return uninstall()
        return status()

    if args.command not in ("extract", "signals", "replay", "classify",
                            "report", "pricing", "policy", "setup",
                            "schedule", "uninstall"):
        parser.print_help()
        return 1

    if args.command == "pricing":
        from .paths import checkout_root
        if checkout_root() is None:
            print("caliper pricing is a development instrument — price "
                  "snapshots are maintained in a source checkout of Caliper, "
                  "not in an installed copy.")
            return 1
        from caliper.harness.replay.pricing_update import update
        update()
        return 0

    if args.command == "report":
        from caliper.harness.report.generate import collect
        from caliper.harness.report.render import render
        from .paths import salt_path, task_classes_path
        root_dir = repo_root()
        from .style import spinner as _spin
        with _spin("Reading records and building the project name map"):
            summary = collect(extracted_dir(),
                              task_classes_path(root_dir),
                              state_dir() / ".project_names.json", salt_path())
        if not summary["n_sessions"]:
            print("No sessions extracted yet. Run caliper extract.")
            return 0
        html = render(summary)
        out = Path(args.out) if args.out else \
            reports_dir() / "first_look.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        from .style import S, box, relpath, sep, step
        h = summary["headline"]
        total = h["total_cost"]
        unpriced = h["unpriced_sessions"] + h["no_token_sessions"]
        total_s = S.bold(f"${total:,.2f}")
        print(box(S.bold("caliper report"),
                  sep(f"{summary['n_sessions']} sessions",
                      f"{total_s} list-equivalent",
                      S.dim(f"{unpriced} not priced"))))
        print()
        kb = f"{len(html) / 1024:.0f} KB"
        print(step(sep("Wrote first-look report", S.dim(kb))))
        print()
        print(S.dim(f"→ {relpath(out, root_dir)}"))
        return 0

    if args.command == "classify":
        from jsonschema import Draft202012Validator
        from caliper.harness.classifier.classify import classify_all
        root_dir = repo_root()
        data_dir = Path(args.data_dir) if args.data_dir else extracted_dir()
        units = ("prompt", "segment", "session") if args.unit == "all" else (args.unit,)
        records = classify_all(data_dir, units)
        if not records:
            print("No prompt units to classify yet. Run caliper extract first.")
            return 0
        from .paths import schema_path as _sp2
        validator = load_validator(_sp2("task_class.schema.json"))
        for r in records:
            validator.validate(r)
        out = Path(args.out) if args.out else \
            derived_dir() / "classes" / "task_classes.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        from collections import Counter
        from .style import S, box, child, relpath, sep, step
        by_unit = Counter(r["unit"] for r in records)
        uncls = Counter(r["unit"] for r in records if r["status"] == "unclassified")
        rules_v = records[0]["classifier_version"] if records else "—"
        print(box(S.bold("caliper classify"),
                  sep(f"{S.bold(str(len(records)))} records",
                      S.dim(f"rules {rules_v}"))))
        print()
        print(step("Classified 3 unit grains"))
        print()
        for u, n in sorted(by_unit.items()):
            un = uncls.get(u, 0)
            share = (S.yellow(f"{un} unclassified ({un / n:.0%})") if un
                     else S.dim("0 unclassified"))
            print(child(u, f"{n} records", share))
            print()
        print(S.dim(f"→ {relpath(out, root_dir)}"))
        if args.validate:
            from .paths import checkout_root
            if checkout_root() is None:
                print("classify --validate is a development instrument — the "
                      "calibration set ships with a source checkout of "
                      "Caliper, not with an installed copy.")
                return 1
            from caliper.harness.classifier import CLASSIFIER_VERSION
            from caliper.harness.classifier.validation import print_report, validate

            from .paths import calibration_dir, validation_report_path
            report = validate(out, calibration_dir(root_dir))
            print_report(report)
            vr = validation_report_path(CLASSIFIER_VERSION)
            vr.parent.mkdir(parents=True, exist_ok=True)
            vr.write_text(json.dumps(report, indent=2))
            print()
            print(S.dim(f"→ {vr}"))
        return 0

    if args.command == "replay":
        from .paths import checkout_root
        if checkout_root() is None:
            print("caliper replay is a development instrument — it needs a "
                  "source checkout of Caliper, a mined task workspace, and "
                  "real API spend.")
            return 1
        from caliper.harness.replay import mining, runner
        repo = Path(args.repo)
        tasks_path = Path(args.tasks)
        if args.action == "mine":
            mining.mine(repo, tasks_path, target_n=args.target_n)
            return 0
        tasks = [json.loads(l) for l in tasks_path.read_text().splitlines() if l.strip()]
        if args.limit:
            tasks = tasks[:args.limit]
        models = [tuple(m.split(":")) for m in args.models.split(",")]
        out = Path(args.out) if args.out else \
            derived_dir() / "replay" / "eval_results.jsonl"
        runner.run_matrix(tasks, models, repo, Path.home() / "caliper-eval" / "runs", out)
        print(f"results appended to {out}")
        return 0

    root = repo_root()
    data_dir = Path(args.data_dir) if args.data_dir else extracted_dir()

    if args.command == "signals":
        from caliper.connectors.git_history import GitHistoryConnector
        from .paths import schema_path as _sp3
        schema_path = _sp3("production_signal.schema.json")
        from .paths import salt_path as _sp
        conn = GitHistoryConnector(salt=load_salt(_sp(data_dir)),
                                   extra_repos=[Path(p) for p in args.repo])
        from .style import S, box, child, relpath, sep, spinner, step
        with spinner("Analyzing repos (blame is slow on big files)"):
            manifest = signals(data_dir, schema_path, connector=conn)
        n_commits = sum(m["commits_analyzed"] for m in manifest["repos"].values())
        if not manifest["repos"]:
            print("No repos referenced by extracted sessions yet. "
                  "Run caliper extract first.")
            return 0
        print(box(S.bold("caliper signals"),
                  sep(f"{S.bold(str(n_commits))} commits",
                      f"{len(manifest['repos'])} repos")))
        print()
        print(step(f"Analyzed {len(manifest['repos'])} repos"))
        print()
        for ref, m in manifest["repos"].items():
            rw = m["rework"]["rate"]
            details = [f"{m['commits_analyzed']} commits"]
            if rw is not None:
                details.append(f"rework {rw:.0%} "
                               f"(n={m['rework']['commits_measured']})")
            if m["reverted_commits"]:
                details.append(S.red(f"{m['reverted_commits']} reverted"))
            a = m["attribution"]
            details.append(S.dim(f"attr {a.get('known', 0)}k/"
                                 f"{a.get('partial', 0)}p/{a.get('unknown', 0)}u"))
            print(child(ref[:13], *details))
            print()
        print(step("Joined sessions to repos"))
        print()
        for tool, j in manifest["session_join"].items():
            rate = j["repo_join_rate"] or 0
            cw = S.dim(f"commit-window {j['commit_window_rate'] or 0:.0%} "
                       f"({j['commit_in_session_window']}/{j['sessions']})")
            print(child(tool, f"{rate:.0%} repo",
                        f"{j['repo_join']}/{j['sessions']}", cw))
            print()
        mpath = relpath(data_dir / "manifests" / (manifest["run_id"] + ".json"), root)
        print(S.dim(f"→ {mpath}"))
        return 0

    from .paths import schema_path as _sp4
    schema_path = _sp4("session.schema.json")

    if args.source:
        sources = []
        for raw in args.source.split(","):
            name = normalize_source_name(raw)
            if name not in PLUGINS:
                print(f"error: unknown source '{raw}' (known: {', '.join(PLUGINS)})",
                      file=sys.stderr)
                return 2
            sources.append(name)
    else:
        sources = list(PLUGINS)

    from .collection import acquire_lock, mark_covered
    from .style import S, box, child, count, relpath, sep, spinner, step

    lock_dir = state_dir() if data_dir == extracted_dir() else data_dir
    lock = acquire_lock(lock_dir)
    if lock is None:
        print(S.byellow("another extract is already running")
              + S.dim(" — the scheduled job, or a second terminal; "
                      "try again in a moment"))
        return 1
    run_start = datetime.now(timezone.utc)
    manifest = {"run_id": None, "sources": {}}
    run_ids: set[str] = set()
    for src_name in sources:
        with spinner(f"Extracting {src_name}"):
            m = extract([src_name], data_dir, schema_path, args.include_content)
        manifest["run_id"] = m["run_id"]
        manifest["connector_version"] = m.get("connector_version")
        manifest["schema_version"] = m.get("schema_version")
        run_ids.add(m["run_id"])
        manifest["sources"].update(m["sources"])
        sm = m["sources"][src_name]
        r = sm["records"]
        status_note = sm["notes"].get("status")
        discover_fail = next((s for s in sm["skipped"]
                              if s.get("path") == "<discover>"), None)
        if discover_fail:
            reason = discover_fail["reason"]
            what = ("permission denied reading the source"
                    if "PermissionError" in reason else "could not read the source")
            print(child(src_name, S.bred(what),
                        S.dim("fix access, then rerun caliper extract")))
        elif status_note:
            # status in words, never "0 records" for a tool that isn't
            # here or has nothing left (DESIGN.md)
            print(child(src_name, S.dim(status_note)))
        else:
            changes = [c for c in (count(r["new"], "new"),
                                   count(r["updated"], "updated"),
                                   count(r["invalid"], "invalid"),
                                   count(len(sm["skipped"]), "skipped")) if c]
            change_s = " · ".join(changes) if changes else S.dim("all unchanged")
            print(child(src_name, f"{r['emitted']} records", change_s))
        print()

    total_sessions = sum(m.get("sessions_on_disk", 0)
                         for m in manifest["sources"].values())
    n_tools = sum(1 for m in manifest["sources"].values()
                  if m["artifacts_discovered"])
    starts = [m["date_range"]["earliest_started_at"]
              for m in manifest["sources"].values()
              if m["date_range"]["earliest_started_at"]]
    ends = [m["date_range"]["latest_ended_at"]
            for m in manifest["sources"].values()
            if m["date_range"]["latest_ended_at"]]
    span_all = f"{min(starts)[:10]} → {max(ends)[:10]}" if starts and ends else ""
    tool_word = "tool" if n_tools == 1 else "tools"
    if total_sessions == 0 and n_tools == 0:
        print("No agent logs found. Caliper reads Claude Code (~/.claude), "
              "Cursor, and Codex; use one of them, then run caliper extract.")
        print()
    else:
        print(step(sep(f"Extracted {S.bold(str(total_sessions))} sessions",
                       f"{n_tools} {tool_word}", S.dim(span_all))))
        print()
    mpath = relpath(data_dir / "manifests" / (manifest["run_id"] + ".json"), root)
    print(S.dim(f"→ {mpath}"))
    print()
    # a manual run is coverage evidence exactly like a scheduled one
    covered = [n for n, m in manifest["sources"].items()
               if m.get("artifacts_discovered", 0) > 0
               and not any(s.get("path") == "<discover>" for s in m["skipped"])]
    absent = [n for n, m in manifest["sources"].items()
              if m.get("artifacts_discovered", 0) == 0
              and not any(s.get("path") == "<discover>" for s in m["skipped"])]
    if data_dir != extracted_dir():
        covered = []  # an override tree is a side experiment: home
        #               coverage/watermark state must not advance (ADR-0012)
    else:
        mark_covered(state_dir(), covered, run_start,
                     full=set(sources) == set(PLUGINS), absent=absent)
    from .health import evaluate_canaries
    for alarm in evaluate_canaries(data_dir, manifest,
                                   exclude_run_ids=run_ids, patch_file=False):
        print(step(S.byellow(f"drift alarm · {alarm['source']}")
                   + " " + S.dim(alarm["detail"])))
        print()
    lock.close()
    from .policy_nudge import policy_nudge
    policy_nudge(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
