"""`caliper setup` — the first-run experience (README: trust screen, then
backfill), staged like a product flow: each step spins while it works and
resolves to a completed line before the next begins. Re-running is safe —
every stage is idempotent."""

from __future__ import annotations

import json
from pathlib import Path

from .style import S, box, child, sep, spinner, step


def _trust_screen():
    print(step("What Caliper reads"))
    print()
    print(child("session metadata", S.dim("timing, turn counts, tool patterns, models")))
    print()
    print(child("token counts", S.dim("all four buckets — spend is priced from these")))
    print()
    print(child("git history", S.dim("commit survival, rework, reverts — read-only")))
    print()
    print(step("What Caliper never reads"))
    print()
    print(child("prompt text & code", S.dim("dropped at the extraction boundary; "
                                            "a test enforces the classifier can't see them — "
                                            "unless you opt into local content sidecars at "
                                            "setup, which stay under ~/.caliper and never "
                                            "enter session records")))
    print()
    print(child("raw paths", S.dim("salted-hashed at the connector; "
                                   "display names stay local-only")))
    print()
    print(S.dim("    everything Caliper does afterward is logged and inspectable "
                "(manifests per run, ADRs per decision)"))
    print()


def _stage(label, fn):
    with spinner(label):
        result = fn()
    return result


def run_setup(repo_root: Path, mode: str | None = None) -> int:
    from .main import extract as run_extract, signals as run_signals

    from .paths import extracted_dir
    data_dir = extracted_dir()
    already = (data_dir / "claude_code" / "sessions.jsonl").exists() or \
              (data_dir / "cursor" / "sessions.jsonl").exists()

    print(box(S.bold("caliper setup"),
              sep(S.dim("first run" if not already else "re-run (idempotent)"),
                  S.dim("engineers do not change how they work"))))
    print()
    _trust_screen()

    # ---- backfill choice ------------------------------------------------
    if mode is None:
        from .interactive import choose
        options = ["Full backfill — sessions + git outcome signals (takes minutes)",
                   "Quick backfill — sessions only, signals later",
                   "Not now"]
        picked = choose("Question", "Start the backfill?", options)
        if picked is None:
            picked = 1
            print(step(sep("Quick backfill",
                           S.dim("non-interactive default — rerun with "
                                 "--full for git outcome signals"))))
        if picked == 2:
            print(step(sep("Setup paused", S.dim("run `caliper setup` anytime"))))
            return 0
        mode = "full" if picked == 0 else "quick"
    print()

    # ---- staged pipeline ------------------------------------------------
    from caliper.connectors import PLUGINS
    from .paths import schema_path
    schema = schema_path("session.schema.json")
    total_sessions = 0
    for name in PLUGINS:
        m = _stage(f"Backfilling {name}",
                   lambda n=name: run_extract([n], data_dir, schema, False))
        src = m["sources"][name]
        r = src["records"]
        total_sessions += src.get("sessions_on_disk", 0)
        rng = src["date_range"]
        status_note = src["notes"].get("status")
        if status_note:
            print(step(sep(f"Backfilled {S.bold(name)}", S.dim(status_note))))
        else:
            span = (f"{rng['earliest_started_at'][:10]} → "
                    f"{(rng['latest_ended_at'] or '')[:10]}"
                    if rng["earliest_started_at"] else "no sessions found")
            print(step(sep(f"Backfilled {S.bold(name)}",
                           f"{r['emitted']} sessions", S.dim(span))))
        print()

    if total_sessions == 0:
        print("No agent logs found. Caliper reads Claude Code (~/.claude), "
              "Cursor, and Codex; use one of them, then run caliper setup "
              "again.")
        print()
        return 0

    def do_classify():
        from jsonschema import Draft202012Validator
        from caliper.harness.classifier.classify import classify_all
        records = classify_all(data_dir)
        v = Draft202012Validator(json.loads(
            schema_path("task_class.schema.json").read_text()))
        for rec in records:
            v.validate(rec)
        from .paths import derived_dir
        out = derived_dir() / "classes" / "task_classes.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        return records

    records = _stage("Classifying traffic (content-free)", do_classify)
    n_uncls = sum(1 for r in records if r["status"] == "unclassified")
    print(step(sep("Classified traffic",
                   f"{len(records)} labels across 3 grains",
                   S.dim(f"{n_uncls} unclassified — reported, never hidden"))))
    print()

    if mode == "full":
        m = _stage("Mining git history for outcome signals (blame is slow)",
                   lambda: run_signals(data_dir,
                                       schema_path("production_signal.schema.json")))
        n_commits = sum(r["commits_analyzed"] for r in m["repos"].values())
        print(step(sep("Mined outcome signals",
                       f"{n_commits} commits across {len(m['repos'])} repos",
                       S.dim("survival · rework · reverts · attribution"))))
        print()

    def do_report():
        from caliper.harness.report.generate import collect
        from caliper.harness.report.render import render
        from .paths import reports_dir, salt_path, state_dir, task_classes_path
        summary = collect(data_dir, task_classes_path(repo_root),
                          state_dir() / ".project_names.json", salt_path())
        html = render(summary)
        out = reports_dir() / "first_look.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html)
        return summary, out

    summary, report_path = _stage("Generating your first look", do_report)
    h = summary["headline"]
    print(step(sep("First look ready",
                   f"{summary['n_sessions']} sessions",
                   S.bold(f"${h['total_cost']:,.2f} list-equivalent"),
                   S.dim(f"{h['unpriced_sessions'] + h['no_token_sessions']} not priced"))))
    print()
    print(S.dim(f"    open it: {report_path}"))
    print()

    _highlights(summary)
    _collection_step(repo_root)
    return _policy_step(repo_root)


def _highlights(summary: dict) -> None:
    """The headline cuts, on screen — the first look is the detail view."""
    from .policy_flow import DASHBOARD_URL, _chart

    total = summary["headline"]["total_cost"]
    if not summary["n_sessions"]:
        return  # nothing to summarize; the caller renders the empty state
    shown_total = S.bold(f"${total:,.2f}") if total else "the traffic"
    total = total or 1  # divisor guard only — never shown (ADR-0014)
    print(step(f"Where {shown_total} went "
               + S.dim("· list-equivalent · bars are share of total")))
    print()
    by_tool = summary["spend"]["by_tool"]
    rows = []
    for tool, d in by_tool.items():
        c = d.get("cost_x1000", 0) / 1000
        if c:
            right = sep(S.bold(f"${c:,.2f}"), S.bold(f"{c / total:.0%}"),
                        S.dim(f"{d['sessions']} sessions"))
        else:
            right = sep(S.dim("not recorded"),
                        S.dim(f"{d.get('sessions_no_tokens', 0)} sessions without tokens"))
        rows.append((tool, c / total, S.accent, right))
    print(_chart(rows))
    print()

    by_model = {m: d for m, d in summary["spend"]["by_model"].items()
                if m != "<synthetic>"}
    if by_model:
        print(step("Which models did the work"))
        print()
        ranked = sorted(by_model.items(),
                        key=lambda kv: -(kv[1].get("cost_x1000", 0)))
        top, rest = ranked[:5], ranked[5:]
        rows = []
        for model, d in top:
            c = d.get("cost_x1000")
            if c is not None:
                right = sep(S.bold(f"${c / 1000:,.2f}"),
                            S.bold(f"{c / 1000 / total:.0%}"),
                            S.dim(f"{d['sessions']} sessions"))
            else:
                right = sep(S.dim("not priced"), S.dim(f"{d['sessions']} sessions"))
            rows.append((model, (c or 0) / 1000 / total, S.accent, right))
        print(_chart(rows))
        print()
        if rest:
            rest_cost = sum(d.get("cost_x1000") or 0 for _, d in rest) / 1000
            n_sess = sum(d["sessions"] for _, d in rest)
            n_unpriced = sum(1 for _, d in rest if d.get("cost_x1000") is None)
            tail = S.dim(f"    + {len(rest)} more models · "
                         f"${rest_cost:,.2f} · {rest_cost / total:.0%} · "
                         f"{n_sess} sessions")
            if n_unpriced:
                tail += S.dim(f" · {n_unpriced} not priced")
            print(tail)
            print()

    counts: dict[str, int] = {}
    for cohort, mix in summary["mix"]["session"].items():
        if cohort.endswith("/organic"):
            for task, n in mix.items():
                counts[task] = counts.get(task, 0) + n
    total = sum(counts.values())
    if total:
        print(step("What the work was " + S.dim("· organic sessions · content-free classifier")))
        print()
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
        rows = [(task.replace("_", " "), n / total, S.cyan,
                 sep(S.bold(f"{n / total:.0%}"), S.dim(f"{n} sessions")))
                for task, n in top]
        print(_chart(rows))
        print()

    auto = sum(summary["auto_mix"].get("automated", {}).values())
    if auto:
        print(S.dim(f"    {auto} sessions look automated (CI-launched) — "
                    "they answer different questions than human traffic"))
        print()

    repos = summary.get("repos") or {}
    if repos:
        n_commits = sum(d["commits"] for d in repos.values())
        print(step("Did the work hold up "
                   + S.dim(f"· {n_commits} commits across {len(repos)} repos "
                           "· read-only git signals")))
        print()
        measured = sorted((d for d in repos.values() if d["surv30_n"]),
                          key=lambda d: -d["commits"])[:3]
        if measured:
            rows = [(d["path"], d["surv30_median"], S.green,
                     sep(S.bold(f"{d['surv30_median']:.0%} survives 30 days"),
                         S.dim(f"median of {d['surv30_n']} commits")))
                    for d in measured]
            print(_chart(rows))
            print()
        rw_m = sum(d["rework_m"] for d in repos.values())
        rw_y = sum(d["rework_y"] for d in repos.values())
        if rw_m:
            print(S.dim(f"    rework: {rw_y} of {rw_m} measured commits "
                        f"({rw_y / rw_m:.0%}) were edited again within 30 days"))
            print()
        n_unmeasured = sum(1 for d in repos.values() if not d["surv30_n"])
        if n_unmeasured:
            print(S.dim(f"    {n_unmeasured} repos too young to measure "
                        "survival — not recorded, never assumed"))
            print()
    else:
        print(S.dim("    impact metrics need git outcome signals — unlock with ")
              + S.accent("caliper setup --full") + S.dim(" or ")
              + S.accent("caliper signals"))
        print()
    preview = S.yellow("(preview — dashboard not live yet)")
    print(S.dim(f"→ deeper cuts — per-repo spend, rework rates, the full mix: "
                f"{DASHBOARD_URL} ") + preview)
    print(S.dim("    your first look above is that dashboard's first card"))
    print()


def _collection_step(repo_root: Path) -> None:
    """Continuous collection (ADR-0011): the retention question, then the
    FDA choice inside `schedule.install`, then the sidecar opt-in. Never
    installs a daemon without an explicit yes — the non-TTY default is No."""
    import sys as _sys

    from .collection import load_state, save_state
    from .interactive import choose
    from .paths import state_dir

    if _sys.platform != "darwin":
        print(S.dim("    background collection: macOS only for now — Linux "
                    "needs a systemd user timer (ADR-0011)"))
        print()
        return
    sdir = state_dir()
    if load_state(sdir).get("schedule"):
        print(step(sep("Collection already scheduled",
                       S.dim("details:") + " " + S.accent("caliper schedule"))))
        print()
        return

    question = ("Claude Code rotates session logs after ~30 days "
                "(your cleanupPeriodDays; other tools keep theirs longer) — "
                "anything not collected before rotation is gone. Keep "
                "collection continuous?")
    options = ["Install hourly background collection — runs only when "
               "there's new activity",
               "Not now"]
    picked = choose("Question", question, options, default=1)
    noninteractive = picked is None
    if noninteractive:  # no TTY: never silently install a daemon
        picked = 1
    print()
    if picked != 0:
        print(step(sep("Not installed"
                       + (" — non-interactive default" if noninteractive
                          else ""),
                       S.dim("install anytime with") + " "
                       + S.accent("caliper schedule install"))))
        print()
        return

    from .schedule import install
    if install() != 0:
        return

    # sidecar opt-in: off by default, forward-only (ADR-0011 decision 5)
    q2 = ("Also store prompt text locally? Writes the text of your prompts "
          "to content sidecars under ~/.caliper — local only, never in "
          "session records. This is the corpus future classifier training "
          "needs, and it only accumulates from now on.")
    opts2 = ["Yes — build the local corpus",
             "No — metadata only (recommended)"]
    picked2 = choose("Question", q2, opts2, default=1)
    noninteractive2 = picked2 is None
    if noninteractive2:
        picked2 = 1  # non-TTY: content collection is never a silent default
    print()
    state = load_state(sdir)
    state["include_content"] = picked2 == 0
    save_state(sdir, state)
    if picked2 == 0:
        print(step(sep("Content sidecars ON",
                       S.dim("prompt text stays local under ~/.caliper — "
                             "switch off by editing include_content in "
                             ".collection.json"))))
    else:
        print(step(sep("Metadata only"
                       + (" — non-interactive default" if noninteractive2
                          else ""),
                       S.dim("session records stay content-free; opt in by "
                             "setting include_content in "
                             "~/.caliper/state/.collection.json"))))
    print()


def _policy_step(repo_root: Path) -> int:
    """The pivot from observation to action: ask, then present. Gated on
    eval evidence from the user's own traffic (ADR-0014) — a skipped stage
    says why in one line rather than disappearing (DESIGN.md)."""
    from .paths import has_own_eval_evidence
    if not has_own_eval_evidence():
        print(step(sep("Policy step skipped",
                       S.dim("a routing policy needs eval evidence from "
                             "your own traffic, which Caliper cannot "
                             "generate yet"))))
        print()
        return 0
    from .policy import analyze
    from .policy_flow import present_policy
    from .policy_nudge import policy_nudge

    question = "Caliper has quality-per-tier evidence covering part of this traffic. Draft a routing policy?"
    options = ["Draft it — see the numbers before deciding anything",
               "Not now"]
    from .interactive import choose
    picked = choose("Question", question, options)
    if picked is None:  # no TTY — typed fallback so scripted runs still flow
        print(box(S.dim("Question"), "", S.bold(question), "",
                  f"  {S.accent('[x]')} {options[0]}",
                  f"  {S.dim('[ ] ' + options[1])}"))
        print()
        try:
            import sys as _sys
            if not _sys.stdin.isatty():
                raise EOFError  # piped stdin: take the conservative default
            raw = input(f"  draft it? {S.dim('[Y/n]')} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = "n"
        picked = 1 if raw in ("n", "no") else 0
    print()
    if picked != 0:
        print(step(sep("Skipped for now",
                       S.dim("draft it anytime with") + " " + S.accent("caliper policy"))))
        print()
        policy_nudge(repo_root)
        return 0

    a = analyze(repo_root)
    if a is None:
        print(S.dim("    no eval evidence on disk yet — run the eval pipeline first"))
        return 1
    p = a["policy"]
    print(step(sep("Policy drafted", S.accent(p["policy_id"]),
                   S.dim(p["scope"]["task_type"].replace("_", " ")))))
    print(S.dim("    UX prototype: drafted from committed eval evidence — in "
                "production this stage runs the eval pipeline and takes longer"))
    print()
    return present_policy(repo_root, a)
