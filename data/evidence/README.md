# data/evidence/

Frozen snapshots that ADRs cite — **never regenerated, never written by any
code path** (ADR-0012; the same pattern as the dated price snapshots in
`harness/replay/pricing_snapshots/`). Each subdirectory is named for the ADR
whose claims its files back. If a number in an ADR needs re-deriving, it is
re-derived from these bytes.

| File | Backs | Former path |
|---|---|---|
| `adr-0007/eval_results.jsonl` | the 30×3 quality-per-tier grid | `data/derived/replay/` |
| `adr-0007/eval_results_pilot.jsonl` | the pilot gate | `data/derived/replay/` |
| `adr-0007/tasks.jsonl` | the mined task set (canonical copy; `~/caliper-eval` holds a disposable working copy) | `data/derived/replay/` |
| `adr-0007/predictions.json` | the pre-registered predictions | `data/derived/replay/` |
| `adr-0008/eval_results_variance.jsonl` | the n_runs=3 variance subset | `data/derived/replay/` |
| `adr-0008/routing_policies.jsonl` | rp-0001, the hand-written draft policy — also read at runtime as the shipped fallback when no user-local policy exists | `data/derived/routing/` |
| `adr-0009/validation_report.json` | classifier agreement (53.1%, κ 0.41) | `data/derived/classes/` |
| `adr-0009/traffic_report.json` | the first real-traffic mix | `data/derived/classes/` |

Not here, deliberately: `task_classes.jsonl` — it is regenerated over every
extraction and had already drifted from the ADR-0009 snapshot (1,446 → 1,571
→ …); the cited version lives in git history at the ADR commit, and the live
file is user data under `~/.caliper/derived/classes/`.

Reading these at runtime is fine (the policy flow ships rp-0001 and the
ADR-0007 curve as its fresh-install baseline). Writing here is a bug, and the
boundary tests fail on it.
