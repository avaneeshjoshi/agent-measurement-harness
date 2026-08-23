# ADR-0012: ~/.caliper is the single home for user data — structurally, not conventionally

**Date:** 2026-08-23 · **Status:** accepted · **Extends:** ADR-0011 decision 1 (which moved `extracted/` only)

## Context

ADR-0011 moved extracted traffic to `~/.caliper`, but derived data still wrote
into the repo — which is exactly how a regenerated `task_classes.jsonl` got
swept into a documentation commit by `git add -A` the same day. A convention
that depends on remembering breaks the same way every time, and once Caliper
is pip-installed without a clone there is no repo to write into at all.

## The rule

**User data never touches the git tree.** If Caliper computed it from
someone's traffic, their repos, or their machine, it lives under `~/.caliper`.
If it is a contract, a fixture, or evidence an ADR cites, it lives in the
repo. There is no third category, and no code path may write user data to a
repo-relative path.

## Write-path audit (2026-08-23, before the change)

Every write in `cli/`, `harness/`, `connectors/`:

| Writer | Wrote (before) | Classification |
|---|---|---|
| `SessionStore.write` / `ContentStore` (cli/store.py) | `<data_dir>/<tool>/{sessions,prompt_units,content}.jsonl` | user data — already home-side since ADR-0011 |
| `extract()` / `signals()` manifests (cli/main.py) | `<data_dir>/manifests/` | user data — home-side |
| `signals()` records | `<data_dir>/git_history/production_signals.jsonl` | user data — home-side |
| `caliper classify` + setup `do_classify` | **repo** `data/derived/classes/task_classes.jsonl` | **user data in the repo — the violation that triggered this ADR** |
| `caliper replay run` default `--out` (runner.py appends) | **repo** `data/derived/replay/eval_results.jsonl` | **user data in the repo — and it appends into ADR-0007's frozen evidence** |
| `caliper report` + setup `do_report` | `<extracted>/report/first_look.html` | user data → `reports/` |
| `record_decision` (cli/policy.py) | `<extracted>/.policy_decisions.jsonl` | user state → `state/` |
| `save_state` / lock (cli/collection.py) | `<extracted>/.collection.json`, `.extract.lock` | user state → `state/` |
| `evaluate_canaries` manifest patch (cli/health.py) | `<extracted>/manifests/` | user data — home-side |
| name map (harness/report/names.py) | `<extracted>/.project_names.json` | user state → `state/` |
| `load_salt` (connectors/util.py) | `<data_dir>/.salt` | user data — the join key; gets its own decision below |
| `mining.py` / `runner.py` workspaces | `~/caliper-eval/{tasks,runs,scratch}` | disposable workspace — outside both trees, stays (below) |
| `pricing_update.py` | **repo** `harness/replay/pricing_snapshots/<date>.json` | **sanctioned repo write** — versioned reference data fetched at build time, not derived from user traffic; never-rewrite guard already enforced |
| `schedule.py` | `~/Library/LaunchAgents/<label>.plist`, `~/.caliper/logs/` | OS-required location; logs home-side |
| migration (cli/paths.py) | `~/.caliper/**` | home-side by definition |

Committed derived files, classified against "evidence an ADR cites":

- **Frozen evidence (stay in repo, moved under `data/evidence/adr-*/`, never
  regenerated):** `eval_results.jsonl` + `eval_results_pilot.jsonl` +
  `tasks.jsonl` + `predictions.json` (ADR-0007), `eval_results_variance.jsonl`
  + `routing_policies.jsonl`/rp-0001 (ADR-0008), `validation_report.json` +
  `traffic_report.json` (ADR-0009 — verified: no production writer exists;
  committed once at the ADR commit and never touched).
- **Live user data (out of git, migrated home):** `task_classes.jsonl` — it
  has been regenerated twice since ADR-0009 (1,446 → 1,571 → current) and no
  longer matches the cited snapshot; the cited version lives in git history.

## Layout

```
~/.caliper/
  .salt          the ref join key — top level, chmod 0400
  extracted/     sessions, prompt units, git_history signals, manifests, sidecars
  derived/       classes/, replay/, routing/ — regenerable outputs
  reports/       generated HTML
  state/         .collection.json, .policy_decisions.jsonl, .project_names.json, lock
  logs/          scheduled job output
```

**`.salt` sits at the top of the tree, not inside any subtree.** It is the
one file that can never be regenerated: lose it and no future extraction ever
joins to existing history again (every `project_ref`/`repo_ref` is salted
with it). Every subtree beside it is clearable — `extracted/` re-extracts
(within retention), `derived/` recomputes, `state/` resets, `reports/` and
`logs/` regenerate — so the salt must not be buried where a subtree wipe
takes it. It is written once, `chmod 0400`, and never opened for write again.
With `--data-dir` overrides the salt is override-local (`<data_dir>/.salt`) —
an override tree is a self-contained experiment, and mixing its refs with the
home salt would neither join nor stay isolated cleanly.

`--data-dir` semantics, made explicit: an override scopes the *extraction
tree only*, and override runs do not touch home `state/` (coverage,
watermarks, decisions describe the default home; a side experiment must not
advance them).

## Migration

Extends the ADR-0011 migration, same guarantees per step (non-destructive,
populated-target-refusing with a printed notice, rename-first with
copy-verify-then-delete fallback, idempotent):

1. repo `data/extracted/` → `~/.caliper/extracted/` (ADR-0011, unchanged)
2. repo `data/derived/classes/task_classes.jsonl` → `~/.caliper/derived/classes/`
3. `extracted/.collection.json`, `.policy_decisions.jsonl`,
   `.project_names.json` → `state/`
4. `extracted/.salt` → `~/.caliper/.salt` (byte-verified when both exist;
   differing salts refuse loudly and keep both — never a silent winner)
5. `extracted/report/first_look.html` → `reports/`

The refs-identical test (`tests/test_paths.py`) extends across the full
migration: refs computed before and after must match byte-for-byte — that
test is the point; without it a migration can silently sever every join.

## Reads and fallbacks

Readers resolve through `cli/paths.py` candidates, first-existing wins:
home `derived/` → repo `data/evidence/adr-*/` (the shipped baseline — e.g.
rp-0001 and the ADR-0007 curve power the policy flow on a fresh install) →
legacy repo path (transitional). Reading repo evidence is fine; writing is
the sin.

## Enforcement — structural, not remembered

- `cli/paths.py` is the only module allowed to name Caliper's data
  locations. A source-scan test fails if any other production module
  constructs a repo-relative `data/...` path.
- A runtime write-audit test runs the extract→classify→report pipeline under
  a sandboxed `CALIPER_HOME` and asserts the repo tree is byte-identical
  afterward — nothing may write into the clone, whatever path expression it
  used.
- The one sanctioned repo writer (`pricing_update.py`, build-time reference
  data) is allowlisted by name in both tests, with this ADR as the citation.

## ~/caliper-eval stays separate

It holds multi-GB cloned repos and run trees — rebuildable workspace, not
collection state. The canonical mined task set and predictions are committed
as ADR-0007 evidence (`data/evidence/adr-0007/tasks.jsonl` — verified
byte-identical to the workspace copy before deciding), so the workspace is
genuinely disposable. Folding it into `~/.caliper` would put gigabytes of
clones inside a tree users should be able to back up cheaply.

## Consequences

- `git add -A` can never again sweep user data into a commit: the repo tree
  contains no writable data paths, and the tests fail if one reappears.
- Fresh installs work with no repo-side data: the policy flow falls back to
  shipped evidence; everything else starts empty and fills from extraction.
- The repo's `data/` is now: `evidence/` (frozen, per-ADR), `calibration/`
  (human-labeled), `fixtures/` (test inputs) — plus gitignored legacy guards.
- ADRs 0007/0008/0009 gain one-line pointers to the relocated evidence paths;
  their bodies stay unrewritten.
