# cli/

The `caliper` command-line tool. Installed by `pip install -e .` from the repo root
(console script `caliper` → `cli.main:main`).

## Commands

```bash
caliper extract                          # all detected sources
caliper extract --source claude-code     # one source
caliper extract --source claude-code,cursor,codex
caliper extract --include-content        # also write prompt-text sidecars
caliper extract --data-dir /elsewhere    # output root (default: data/extracted/)
```

## What extract does

For each source plugin in `connectors/` (Claude Code, Cursor, Codex — ADR-0003):
discover artifacts → read raw records → emit session records → validate against
`schemas/session.schema.json` → merge into `data/extracted/<source_tool>/sessions.jsonl`.
Every run writes `data/extracted/manifests/<run_id>.json`: what was read, what was
skipped and why, per-source counts and date ranges.

Guarantees (enforced by `tests/test_extractor.py`):

- **Read-only** on all sources; SQLite is snapshot-copied before opening.
- **Schema-valid or not written** — invalid records land in the manifest, not the data.
- **Idempotent** — re-runs dedupe by `provenance.content_hash`; unchanged sources
  produce byte-identical output.
- **Content-free by default** — prompt text and file contents are dropped at
  extraction; `--include-content` writes them to a `content.jsonl` sidecar, never
  into session records.
- **Malformed files are logged and skipped, never fatal.**

Rationale and format findings: ADR-0004.
