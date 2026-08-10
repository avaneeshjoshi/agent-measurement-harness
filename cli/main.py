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

from connectors import PLUGINS, normalize_source_name
from connectors.util import load_salt, now_iso

from .store import ContentStore, SessionStore


def repo_root() -> Path:
    """The repo this package was installed (editable) from."""
    return Path(__file__).resolve().parent.parent


def load_validator(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def extract(sources: list[str], data_dir: Path, schema_path: Path,
            include_content: bool, plugins_override: dict | None = None) -> dict:
    """Run extraction. Returns the manifest dict. plugins_override lets tests
    inject plugins pointed at fixture roots."""
    validator = load_validator(schema_path)
    salt = load_salt(data_dir)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]

    manifest: dict = {
        "run_id": run_id,
        "started_at": now_iso(),
        "include_content": include_content,
        "schema": schema_path.name,
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
            src_manifest["notes"]["status"] = "source not present on this machine"
            continue

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
    from connectors.git_history import GitHistoryConnector

    validator = load_validator(schema_path)
    salt = load_salt(data_dir)
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
                                     description="Caliper: coding-agent traffic measurement.")
    sub = parser.add_subparsers(dest="command")

    p_extract = sub.add_parser("extract", help="Extract sessions from local agent logs.")
    p_extract.add_argument("--source", default=None,
                           help="Comma-separated: claude-code,cursor,codex. Default: all detected.")
    p_extract.add_argument("--include-content",
                           action="store_true",
                           help="Also write prompt text to a content sidecar "
                                "(dropped by default; session records stay content-free).")
    p_extract.add_argument("--data-dir", default=None,
                           help="Output root (default: <repo>/data/extracted).")

    p_signals = sub.add_parser("signals",
                               help="Compute production signals from local git "
                                    "repos referenced by extracted sessions.")
    p_signals.add_argument("--data-dir", default=None,
                           help="Output root (default: <repo>/data/extracted).")
    p_signals.add_argument("--repo", action="append", default=[],
                           help="Additional repo path(s) to analyze.")

    p_replay = sub.add_parser("replay",
                              help="Replay mined tasks across model tiers "
                                   "(harness/replay).")
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

    p_report = sub.add_parser("report",
                              help="Generate the self-contained first-look HTML.")
    p_report.add_argument("--out", default=None)

    p_pricing = sub.add_parser("pricing",
                               help="Price-sheet management (build-time fetch).")
    p_pricing.add_argument("action", choices=["update"])

    args = parser.parse_args(argv)
    if args.command not in ("extract", "signals", "replay", "classify",
                            "report", "pricing"):
        parser.print_help()
        return 1

    if args.command == "pricing":
        from harness.replay.pricing_update import update
        update()
        return 0

    if args.command == "report":
        from harness.report.generate import collect
        from harness.report.render import render
        root_dir = repo_root()
        summary = collect(root_dir)
        html = render(summary)
        out = Path(args.out) if args.out else \
            root_dir / "data" / "extracted" / "report" / "first_look.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        print(f"first-look report -> {out} ({len(html) / 1024:.0f} KB)")
        return 0

    if args.command == "classify":
        from jsonschema import Draft202012Validator
        from harness.classifier.classify import classify_all
        root_dir = repo_root()
        data_dir = Path(args.data_dir) if args.data_dir else root_dir / "data" / "extracted"
        units = ("prompt", "segment", "session") if args.unit == "all" else (args.unit,)
        records = classify_all(data_dir, units)
        validator = load_validator(root_dir / "schemas" / "task_class.schema.json")
        for r in records:
            validator.validate(r)
        out = Path(args.out) if args.out else root_dir / "data" / "derived" / "classes" / "task_classes.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        from collections import Counter
        by_unit = Counter(r["unit"] for r in records)
        uncls = Counter(r["unit"] for r in records if r["status"] == "unclassified")
        print(f"{len(records)} task_class records -> {out}")
        for u, n in sorted(by_unit.items()):
            print(f"  {u}: {n} ({uncls.get(u, 0)} unclassified)")
        return 0

    if args.command == "replay":
        from harness.replay import mining, runner
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
            repo_root() / "data" / "derived" / "replay" / "eval_results.jsonl"
        runner.run_matrix(tasks, models, repo, Path.home() / "caliper-eval" / "runs", out)
        print(f"results appended to {out}")
        return 0

    root = repo_root()
    data_dir = Path(args.data_dir) if args.data_dir else root / "data" / "extracted"

    if args.command == "signals":
        from connectors.git_history import GitHistoryConnector
        schema_path = root / "schemas" / "production_signal.schema.json"
        conn = GitHistoryConnector(salt=load_salt(data_dir),
                                   extra_repos=[Path(p) for p in args.repo])
        manifest = signals(data_dir, schema_path, connector=conn)
        for ref, m in manifest["repos"].items():
            print(f"{ref}  commits={m['commits_analyzed']}"
                  f"  rework_rate={m['rework']['rate']}"
                  f"  reverted={m['reverted_commits']}"
                  f"  attribution={m['attribution']}"
                  f"  tools={','.join(m['tools_referencing'])}")
        for tool, j in manifest["session_join"].items():
            print(f"join {tool:12s} sessions={j['sessions']}"
                  f" repo_join={j['repo_join']} ({j['repo_join_rate']})"
                  f" commit_window={j['commit_in_session_window']}"
                  f" ({j['commit_window_rate']})")
        print(f"manifest: {data_dir / 'manifests' / (manifest['run_id'] + '.json')}")
        return 0

    schema_path = root / "schemas" / "session.schema.json"

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

    manifest = extract(sources, data_dir, schema_path, args.include_content)

    for name, m in manifest["sources"].items():
        rng = m["date_range"]
        span = ""
        if rng["earliest_started_at"]:
            span = f"  [{rng['earliest_started_at'][:10]} .. {(rng['latest_ended_at'] or '')[:10]}]"
        print(f"{name:12s} artifacts={m['artifacts_read']}/{m['artifacts_discovered']}"
              f"  emitted={m['records']['emitted']}"
              f" (new={m['records']['new']} updated={m['records']['updated']}"
              f" unchanged={m['records']['unchanged']} invalid={m['records']['invalid']})"
              f"  skipped={len(m['skipped'])}{span}")
    print(f"manifest: {data_dir / 'manifests' / (manifest['run_id'] + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
