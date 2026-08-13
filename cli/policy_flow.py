"""The policy conversation: scan verdict → policy evidence → dashboard tease
→ the apply question. Reference-styled (boxed question, hex bullets)."""

from __future__ import annotations

from pathlib import Path

from .policy import analyze, record_decision
from .style import S, box, child, sep, spinner, step

DASHBOARD_URL = "https://caliper.dev/dashboard"


def run_policy_flow(repo_root: Path, yes: bool = False, no: bool = False) -> int:
    with spinner("Scanning your traffic against the draft policy"):
        a = analyze(repo_root)
    if a is None:
        print(S.dim("no routing_policy record found — run the eval pipeline first"))
        return 1

    p = a["policy"]
    o = a["overspend"]
    rec = p["recommendation"]
    scope = p["scope"]["task_type"].replace("_", " ")

    print(box(S.bold("caliper policy"),
              sep(S.accent(p["policy_id"]), S.dim(f"status {p['status']}"),
                  S.dim(scope))))
    print()

    # ---- the verdict ----------------------------------------------------
    print(step(f"Scanned {a['n_sessions']} sessions "
               + S.dim(f"· {a['in_scope']} in scope ({scope})")))
    print()
    if o["sessions"]:
        delta = o["delta"]
        organic = o["sessions"] - o["eval_sessions"]
        cohort_note = (S.dim(f"{o['eval_sessions']} of these are Caliper's own "
                             "eval runs") if o["eval_sessions"] else "")
        print(child("overspend",
                    S.byellow(f"${delta:,.2f}"),
                    f"{o['sessions']} frontier sessions on work the policy routes to mid",
                    S.dim(f"${o['actual']:,.2f} actual vs ${o['at_mid']:,.2f} at mid")))
        print()
        if cohort_note:
            print(f"    {cohort_note}")
            print()
    else:
        print(child("overspend", S.green("none"),
                    "no frontier sessions on in-scope work"))
        print()
    if a["below_floor"]["sessions"]:
        print(child("below floor",
                    S.yellow(f"{a['below_floor']['sessions']} sessions"),
                    "small-tier runs on work the policy floors at mid",
                    S.dim("quality risk, not savings")))
        print()

    # ---- the policy -----------------------------------------------------
    print(step(f"Draft policy: route {scope} to "
               + S.accent(rec["model_tier"]) + S.dim(f" ({rec['model_id_example']})")
               + S.dim(f" · escalate {rec['escalation_tier']}")))
    print()
    c = a["curve"]
    if "frontier" in c and "mid" in c:
        f_, m_ = c["frontier"], c["mid"]
        print(child("quality",
                    f"frontier {f_['value']:.0%} vs mid {m_['value']:.0%}",
                    S.dim(f"n={f_['n']} tasks each · not statistically "
                          "distinguishable (ADR-0008)")))
        print()
    cp = p["evidence"]["cost_projection"]
    if cp and cp["current_cost_per_task_usd"]:
        ratio = cp["projected_cost_per_task_usd"] / cp["current_cost_per_task_usd"]
        print(child("cost",
                    f"mid runs at {ratio:.0%} of frontier per task",
                    S.dim(f"${cp['current_cost_per_task_usd']:.2f} → "
                          f"${cp['projected_cost_per_task_usd']:.2f}")))
        print()
    if "small" in c and "mid" in c:
        drop = c["mid"]["value"] - c["small"]["value"]
        print(child("floor",
                    f"small tier loses {drop:.0f} pts" if drop > 1
                    else f"small tier loses {drop:.0%}",
                    S.dim("p=0.026 — do not route below mid (ADR-0008)")))
        print()
    print(child("caveats", S.dim(sep("replay-only evidence", "contaminated tasks",
                                     "solo traffic", f"ADRs {', '.join(p['adr_refs'])}"))))
    print()
    print(S.dim(f"→ full curve, task grid, per-repo spend: {DASHBOARD_URL} ")
          + S.yellow("(preview — dashboard not live yet)"))
    print()

    # ---- the question ---------------------------------------------------
    print(box(S.dim("Question"), "",
              S.bold(f"Apply {p['policy_id']} to your agent configs?"), "",
              f"  {S.accent('[x]')} Apply — route {scope} to {rec['model_tier']}",
              f"  {S.dim('[ ] Not yet')}"))
    print()

    if yes:
        answer = True
    elif no:
        answer = False
    else:
        try:
            raw = input(f"  apply? {S.dim('[y/N]')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = ""
        answer = raw in ("y", "yes")

    out = record_decision(repo_root, p["policy_id"], answer)
    print()
    if answer:
        print(step(sep(S.bgreen("Decision recorded: apply"),
                       S.dim("the apply engine (native config writes) is "
                             "future work — no agent config was modified"))))
    else:
        print(step(sep("Decision recorded: not yet",
                       S.dim("re-run `caliper policy` anytime"))))
    print()
    print(S.dim(f"→ {out.name} (local only)"))
    return 0
