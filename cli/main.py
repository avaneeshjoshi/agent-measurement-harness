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
            if content_store and emission.content_rows:
                content_store.add(emission.content_rows)

            s, e = rec.get("started_at"), rec.get("ended_at")
            dr = src_manifest["date_range"]
            if s and (dr["earliest_started_at"] is None or s < dr["earliest_started_at"]):
                dr["earliest_started_at"] = s
            if e and (dr["latest_ended_at"] is None or e > dr["latest_ended_at"]):
                dr["latest_ended_at"] = e

        src_manifest["sessions_on_disk"] = store.write()
        if content_store:
            src_manifest["content_rows_written"] = content_store.write()
        src_manifest["skipped"] = [asdict(s) for s in plugin.skips]

    manifest["finished_at"] = now_iso()
    manifest_dir = data_dir / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / f"{run_id}.json").write_text(json.dumps(manifest, indent=2))
    return manifest


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

    args = parser.parse_args(argv)
    if args.command != "extract":
        parser.print_help()
        return 1

    root = repo_root()
    schema_path = root / "schemas" / "session.schema.json"
    data_dir = Path(args.data_dir) if args.data_dir else root / "data" / "extracted"

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
