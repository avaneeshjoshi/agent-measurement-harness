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
                                            "a test enforces the classifier can't see them")))
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
    from .policy_nudge import policy_nudge

    data_dir = repo_root / "data" / "extracted"
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
            picked = 1  # non-interactive default: quick
        if picked == 2:
            print(step(sep("Setup paused", S.dim("run `caliper setup` anytime"))))
            return 0
        mode = "full" if picked == 0 else "quick"
    print()

    # ---- staged pipeline ------------------------------------------------
    from connectors import PLUGINS
    schema = repo_root / "schemas" / "session.schema.json"
    total_sessions = 0
    for name in PLUGINS:
        m = _stage(f"Backfilling {name}",
                   lambda n=name: run_extract([n], data_dir, schema, False))
        src = m["sources"][name]
        r = src["records"]
        total_sessions += src.get("sessions_on_disk", 0)
        rng = src["date_range"]
        span = (f"{rng['earliest_started_at'][:10]} → "
                f"{(rng['latest_ended_at'] or '')[:10]}"
                if rng["earliest_started_at"] else "no sessions found")
        print(step(sep(f"Backfilled {S.bold(name)}",
                       f"{r['emitted']} sessions", S.dim(span))))
        print()

    def do_classify():
        from jsonschema import Draft202012Validator
        from harness.classifier.classify import classify_all
        records = classify_all(data_dir)
        v = Draft202012Validator(json.loads(
            (repo_root / "schemas" / "task_class.schema.json").read_text()))
        for rec in records:
            v.validate(rec)
        out = repo_root / "data" / "derived" / "classes" / "task_classes.jsonl"
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
                                       repo_root / "schemas" / "production_signal.schema.json"))
        n_commits = sum(r["commits_analyzed"] for r in m["repos"].values())
        print(step(sep("Mined outcome signals",
                       f"{n_commits} commits across {len(m['repos'])} repos",
                       S.dim("survival · rework · reverts · attribution"))))
        print()

    def do_report():
        from harness.report.generate import collect
        from harness.report.render import render
        summary = collect(repo_root)
        html = render(summary)
        out = data_dir / "report" / "first_look.html"
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
    policy_nudge(repo_root)
    return 0
