"""The post-run nudge: surface draft policies awaiting a decision after
extract/setup, instead of leaving them buried in data/derived."""

from __future__ import annotations

import json
from pathlib import Path

from .style import S, sep, step


def policy_nudge(repo_root: Path) -> None:
    policies = repo_root / "data" / "derived" / "routing" / "routing_policies.jsonl"
    if not policies.exists():
        return
    records = [json.loads(l) for l in policies.read_text().splitlines() if l.strip()]
    drafts = [r for r in records if r["status"] in ("draft", "proposed")]
    if not drafts:
        return
    decided: set[str] = set()
    from .paths import extracted_dir
    decisions = extracted_dir() / ".policy_decisions.jsonl"
    if decisions.exists():
        for line in decisions.read_text().splitlines():
            d = json.loads(line)
            if d.get("applied"):
                decided.add(d["policy_id"])
    pending = [r for r in drafts if r["policy_id"] not in decided]
    if not pending:
        return
    word = "policy" if len(pending) == 1 else "policies"
    print(step(sep(S.byellow(f"{len(pending)} draft {word} awaiting your decision"),
                   S.dim("review with") + " " + S.accent("caliper policy"))))
    print()
