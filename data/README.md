# data/

**The rule (ADR-0012): user data never touches the git tree.** If Caliper
computed it from someone's traffic, their repos, or their machine, it lives
under `~/.caliper/` — extracted records, derived outputs, reports, state,
logs, and the salt. If it is a contract, a fixture, or evidence an ADR cites,
it lives here. There is no third category, and no code path may write user
data to a repo-relative path — `cli/paths.py` is the single path authority
and boundary tests fail if anything bypasses it.

## What's here

| Subdir | Contents |
|---|---|
| `evidence/` | Frozen per-ADR snapshots — never regenerated, never written by code. See [`evidence/README.md`](evidence/README.md) |
| `calibration/` | The human-labeled sets — today the ADR-0002 unit-comparison labels; the 100–200 task judge-calibration set is planned and needs human raters |
| `fixtures/` | Small hand-built source-log samples used by `tests/` |

`extracted/` and `derived/` no longer exist here — both live under
`~/.caliper/` and both are gitignored as a guard against stragglers. A
populated legacy tree from an older checkout is migrated automatically,
salt-preserving (`tests/test_paths.py`).

## Rules

- **No customer data, ever, in this repo.** Development runs entirely on
  public OSS repos and this machine's own traffic — which stays in
  `~/.caliper`, never here.
- Evidence files are append-never: corrections are restatements in ADR
  postscripts (the ADR-0007 pricing-postscript pattern), not rewrites.
- Records are versioned by the schema that produced them; re-runs write new
  artifacts under `~/.caliper`, so every committed number stays reproducible
  from the frozen bytes beside its ADR.
