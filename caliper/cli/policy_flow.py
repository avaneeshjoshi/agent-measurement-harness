"""The policy conversation: scan verdict → charts and per-tier stats → the
apply question. All numbers come from records on disk; the dashboard link
and apply engine are labeled stubs."""

from __future__ import annotations

from pathlib import Path

from .policy import analyze, record_decision
from .style import S, bar, box, sep, spinner, step

TIER_COLOR = {}  # populated lazily from S


TIERS = ("frontier", "mid", "small", "open_weight")


def _tier_colors():
    return {"frontier": S.cyan, "mid": S.accent, "small": S.yellow,
            "open_weight": S.green}


def _tier_label(t: str) -> str:
    return t.replace("_", " ")


def _chart(rows, width: int = 22):
    """rows: (label, frac, color, right_text). Aligned bar block. Empty rows
    render nothing — never a crash (the empty-machine case, ADR-0014)."""
    if not rows:
        return ""
    label_w = max(len(r[0]) for r in rows)
    out = []
    for label, frac, color, right in rows:
        out.append(f"    {S.dim(label.ljust(label_w))}  "
                   f"{bar(frac, width, color)}  {right}")
    return "\n".join(out)


def run_policy_flow(repo_root: Path, yes: bool = False, no: bool = False) -> int:
    from .paths import checkout_root, has_own_eval_evidence
    if not has_own_eval_evidence() and checkout_root() is None:
        # ADR-0014: never hand a stranger a recommendation built from the
        # author's shipped evidence
        print("No routing policy yet — a policy needs eval evidence from "
              "your own traffic, which Caliper cannot generate yet.")
        return 0
    with spinner("Scanning your traffic against the draft policy"):
        a = analyze(repo_root)
    if a is None:
        print(S.dim("no routing_policy record found — run the eval pipeline first"))
        return 1
    print(box(S.bold("caliper policy"),
              sep(S.accent(a["policy"]["policy_id"]),
                  S.dim(f"status {a['policy']['status']}"),
                  S.dim(a["policy"]["scope"]["task_type"].replace("_", " ")))))
    print()
    return present_policy(repo_root, a, yes=yes, no=no)


def present_policy(repo_root: Path, a: dict, yes: bool = False,
                   no: bool = False) -> int:
    """The verdict -> evidence -> question sequence. Called by the standalone
    `caliper policy` and inline by `caliper setup` after the first look."""
    p = a["policy"]
    o = a["overspend"]
    rec = p["recommendation"]
    scope = p["scope"]["task_type"].replace("_", " ")
    colors = _tier_colors()

    # ---- the verdict ----------------------------------------------------
    netted = a.get("fork_netted") or 0
    print(step(f"Scanned {a['n_sessions']} sessions "
               + S.dim(f"· {a['in_scope']} in scope ({scope})")
               + (S.dim(f" · {netted} fork "
                        f"{'child' if netted == 1 else 'children'} netted")
                  if netted else "")))
    print()
    if o["sessions"]:
        peak = max(o["actual"], o["at_mid"]) or 1
        delta_s = S.byellow(f"${o['delta']:,.2f} overspend")
        detail_s = S.dim(f"· {o['sessions']} frontier sessions on work the "
                         "policy routes to mid")
        print(f"    {delta_s} {detail_s}")
        print()
        print(_chart([
            ("actual (frontier)", o["actual"] / peak, colors["frontier"],
             S.bold(f"${o['actual']:,.2f}")),
            ("at mid tier", o["at_mid"] / peak, colors["mid"],
             S.bold(f"${o['at_mid']:,.2f}")),
        ]))
        print()
        if o["eval_sessions"]:
            print(S.dim(f"    {o['eval_sessions']} of {o['sessions']} are "
                        "Caliper's own eval runs"))
            print()
    if a["below_floor"]["sessions"]:
        print(f"    {S.yellow(f'{a['below_floor']['sessions']} sessions below the floor')} "
              + S.dim("· small-tier runs on floored work · quality risk, not savings"))
        print()

    # ---- quality per tier -----------------------------------------------
    tiers = a.get("tiers") or {}
    access = a.get("access") or {}
    order = [t for t in TIERS if t in tiers]
    if order:
        n = tiers[order[0]]["n"]
        print(step(f"Quality per tier "
                   + S.dim(f"· {n} tasks each · hidden-test replay · ADR-0007")))
        print()
        rows = []
        for t in order:
            d = tiers[t]
            frac = d["solved"] / d["n"]
            ci = a["curve"].get(t, {}).get("ci") or {}
            ci_s = (S.dim(f"CI {ci['lower']:.0%}–{ci['upper']:.0%}")
                    if ci else "")
            right = sep(S.bold(f"{frac:.0%}"), f"{d['solved']}/{d['n']}", ci_s)
            rows.append((f"{_tier_label(t)} · {d['model']}", frac, colors[t], right))
        print(_chart(rows))
        print()
        for t in TIERS:  # unmeasured tiers stay visible, never silently absent
            if t in tiers:
                continue
            name = colors[t](_tier_label(t))
            if t in access:
                models = ", ".join(access[t][:2])
                print("    " + sep(name,
                                   S.dim(f"access proven ({models})"),
                                   S.yellow("quality not measured"),
                                   S.dim("excluded from the recommendation "
                                         "until evaluated")))
            else:
                print("    " + sep(name,
                                   S.dim("no access proven in your traffic — "
                                         "excluded from routing (ADR-0010)"),
                                   S.dim("prove it by connecting an account: ")
                                   + S.accent("caliper connect")
                                   + " " + S.yellow("(future)")))
        print()
        print(S.dim("    frontier vs mid: not statistically distinguishable "
                    "(p=0.645) · mid vs small: real drop (p=0.026) · ADR-0008"))
        print()

        # ---- cost per tier ----------------------------------------------
        print(step("Cost per tier " + S.dim("· billed rates · sonnet restated "
                                            "per ADR-0007 postscript")))
        print()
        peak_cost = max(d["cost_billed"] for d in tiers.values()) or 1
        rows = []
        for t in order:
            d = tiers[t]
            per_solve = (S.dim(f"${d['per_solve']:.2f}/solve")
                         if d["per_solve"] else S.dim("no solves"))
            turns = (S.dim(f"{d['mean_turns']:.1f} turns avg")
                     if d["mean_turns"] else "")
            right = sep(S.bold(f"${d['cost_billed']:,.2f}"), per_solve, turns)
            rows.append((_tier_label(t), d["cost_billed"] / peak_cost, colors[t], right))
        print(_chart(rows))
        print()

    # ---- recommendation -------------------------------------------------
    print(step(f"Draft policy: route {scope} to "
               + S.accent(rec["model_tier"]) + S.dim(f" ({rec['model_id_example']})")
               + S.dim(f" · escalate {rec['escalation_tier']} · floor at mid")))
    print()
    print(S.dim("    caveats: " )
          + S.dim(sep("replay-only evidence", "contaminated public-repo tasks",
                      "solo traffic", f"ADRs {', '.join(p['adr_refs'])}")))
    print()
    print(S.dim("→ full curve, task grid, per-repo spend: ")
          + S.accent("caliper serve"))
    print()

    # ---- the question ---------------------------------------------------
    if yes:
        answer = True
    elif no:
        answer = False
    else:
        from .interactive import choose
        options = [f"Apply — route {scope} to {rec['model_tier']}", "Not yet"]
        try:
            picked = choose("Question",
                            f"Apply {p['policy_id']} to your agent configs?",
                            options)
        except KeyboardInterrupt:
            print()
            picked = 1
        if picked is None:
            print(box(S.dim("Question"), "",
                      S.bold(f"Apply {p['policy_id']} to your agent configs?"),
                      "", f"  {S.accent('[x]')} {options[0]}",
                      f"  {S.dim('[ ] ' + options[1])}"))
            print()
            try:
                raw = input(f"  apply? {S.dim('[y/N]')} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                raw = ""
            answer = raw in ("y", "yes")
        else:
            answer = picked == 0
    print()

    out = record_decision(repo_root, p["policy_id"], answer)
    if answer:
        print(step(sep(S.bgreen("Policy accepted"),
                       S.dim("decision recorded — the apply engine (native "
                             "config writes) is future work; no agent config "
                             "was modified"))))
    else:
        print(step(sep(f"{p['policy_id']} stays ready",
                       S.dim("apply it anytime with")
                       + " " + S.accent("caliper policy apply"))))
    print()
    print(S.dim(f"→ {out.name} (local only)"))
    return 0
