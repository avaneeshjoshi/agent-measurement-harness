"""Replay runner: identical-conditions agent runs per (task x model tier).

Isolation guarantees (the agent never sees the answer):
- The workspace is a HISTORY-FREE snapshot of the repo at pre_sha
  (`git archive`, no .git directory) — no future commits to dig up.
- WebSearch/WebFetch are disabled — no JIRA/GitHub lookups of the real fix.
- The hidden tests are overlaid AFTER the agent finishes, from ground truth;
  any agent edit to those files is overwritten before scoring.
- Identical prompt template, workspace, and tool surface per tier; the only
  variable is --model.

Scoring: compile floor (`mvn test-compile` on the agent's tree, hidden tests
overlaid — compile failure floors the run), then hidden-test pass rate over
the fix commit's test classes.

Cost: token buckets from the CLI's result JSON, priced with the versioned
sheet in pricing.json (cache buckets included — ADR-0005 showed cache traffic
dominates; input/output alone misprice agent work). The CLI's own
total_cost_usd is recorded alongside as a cross-check.
"""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import HARNESS_VERSION
from .mining import _git, run_hidden_tests

PROMPT_TEMPLATE_VERSION = "replay-prompt-0.1.0"

PROMPT = """You are working in a checkout of Apache Commons Lang ({repo_url}).
A bug was reported against this state of the code:

--- BUG REPORT ---
{problem_statement}
--- END BUG REPORT ---

Fix this bug in the main source code (src/main/java/...).

Rules:
- Modify ONLY main source files under src/main/java. Do not modify or add tests.
- Keep the change minimal and targeted at the described bug.
- The project must still compile: verify with `mvn -q test-compile -Dcheckstyle.skip=true -Drat.skip=true -Dspotbugs.skip=true -Dpmd.skip=true -Danimal.sniffer.skip=true`.
- Do not use the internet or any git history; work only from the code present.
When the fix is complete and the project compiles, you are done."""

EVAL_SCHEMA_VERSION = "0.2.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def load_pricing() -> dict:
    return json.loads((Path(__file__).parent / "pricing.json").read_text())


def price_usage(usage: dict, model_id: str, pricing: dict) -> float | None:
    """Price CLI-reported usage with the versioned sheet. Cache-write TTL
    split is used when the CLI reports it; else 1h TTL is assumed (documented
    in the sheet)."""
    p = pricing["models"].get(model_id)
    if not p or not usage:
        return None
    m = 1_000_000
    cost = (usage.get("input_tokens", 0) / m) * p["input"] \
         + (usage.get("output_tokens", 0) / m) * p["output"] \
         + (usage.get("cache_read_input_tokens", 0) / m) * p["cache_read"]
    cc = usage.get("cache_creation") or {}
    if cc:
        cost += (cc.get("ephemeral_5m_input_tokens", 0) / m) * p["cache_write_5m"]
        cost += (cc.get("ephemeral_1h_input_tokens", 0) / m) * p["cache_write_1h"]
    else:
        cost += (usage.get("cache_creation_input_tokens", 0) / m) * p["cache_write_1h"]
    return round(cost, 6)


def make_snapshot(repo: Path, pre_sha: str, dest: Path) -> None:
    """History-free workspace: git archive | untar. No .git, no future."""
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar") as tf:
        subprocess.run(["git", "-C", str(repo), "archive", "-o", tf.name, pre_sha],
                       check=True)
        with tarfile.open(tf.name) as tar:
            tar.extractall(dest)


def run_agent(workdir: Path, prompt: str, model_id: str,
              max_turns: int = 60, timeout_s: int = 1800) -> dict:
    """One headless Claude Code run. Returns the CLI's result JSON (plus
    our_error on crash/timeout)."""
    cmd = ["claude", "-p", prompt,
           "--model", model_id,
           "--output-format", "json",
           "--dangerously-skip-permissions",
           "--disallowedTools", "WebSearch", "WebFetch",
           "--max-turns", str(max_turns)]
    # identical, clean environment per run: drop the invoking Claude Code
    # session's own vars so the child run is not marked as nested
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC_LOG"))}
    try:
        res = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                             timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return {"our_error": "timeout", "subtype": "timeout"}
    if res.returncode != 0 and not res.stdout.strip():
        return {"our_error": f"exit {res.returncode}: {res.stderr[:500]}"}
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {"our_error": f"unparseable output: {res.stdout[:300]}"}


def score(workdir: Path, repo: Path, task: dict) -> dict:
    """Overlay ground-truth hidden tests, compile floor, run hidden tests."""
    # restore every test file the fix commit touched to its pre state, so the
    # overlay diff applies regardless of what the agent did to src/test
    test_diff = _git(repo, "diff", f"{task['pre_sha']}..{task['fix_sha']}", "--", "src/test")
    changed = _git(repo, "diff", "--name-only",
                   f"{task['pre_sha']}..{task['fix_sha']}", "--", "src/test").split()
    for rel in changed:
        target = workdir / rel
        show = subprocess.run(["git", "-C", str(repo), "show",
                               f"{task['pre_sha']}:{rel}"],
                              capture_output=True, text=True)
        if show.returncode == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(show.stdout)
        elif target.exists():
            target.unlink()  # file is new in the fix commit
    apply = subprocess.run(["git", "apply", "-"], input=test_diff, text=True,
                           cwd=workdir, capture_output=True)
    if apply.returncode != 0:
        return {"build": "fail", "tests_passed": None, "tests_total": None,
                "note": f"test overlay failed: {apply.stderr[:200]}"}

    result = run_hidden_tests(workdir, task["hidden_test_classes"])
    if result is None:
        return {"build": "fail", "tests_passed": None, "tests_total": None,
                "note": "compile failure or no test reports"}
    passed, total = result
    return {"build": "pass", "tests_passed": passed, "tests_total": total,
            "note": None}


def run_cell(task: dict, model_id: str, tier: str, repo: Path,
             work_root: Path, run_id: str, pricing: dict, log=print) -> dict:
    """One (task x model) cell -> a schema-shaped eval_result record."""
    workdir = work_root / run_id / task["task_id"] / model_id
    log(f"  snapshot -> {workdir}")
    make_snapshot(repo, task["pre_sha"], workdir)
    prompt = PROMPT.format(repo_url=task["repo_url"],
                           problem_statement=task["problem_statement"])
    log(f"  running {model_id} ...")
    started = datetime.now(timezone.utc)
    agent = run_agent(workdir, prompt, model_id)
    wall_s = (datetime.now(timezone.utc) - started).total_seconds()
    completed = "our_error" not in agent and agent.get("subtype") == "success"
    log(f"  agent done in {wall_s:.0f}s (completed={completed}, "
        f"turns={agent.get('num_turns')}); scoring ...")

    gates = score(workdir, repo, task)
    (workdir / "caliper-agent-result.json").write_text(json.dumps(agent, indent=2))

    usage = agent.get("usage") or {}
    our_cost = price_usage(usage, model_id, pricing)
    pass_rate = None
    if gates["tests_total"]:
        pass_rate = gates["tests_passed"] / gates["tests_total"]

    record = {
        "schema_version": EVAL_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": _now_iso(),
        "task_ref": {"task_id": task["task_id"], "source_session_id": None,
                     "task_class": {"task_type": "single_file_bug_fix"
                                    if len(task["main_files_changed"]) == 1
                                    else "multi_file_bug_fix",
                                    "taxonomy_version": "0.1.0-provisional",
                                    "classification_confidence": None}},
        "cell": {"model_id": model_id, "model_tier": tier,
                 "skill_attached": False, "skill_id": None, "effort": None},
        "replay_config": {"harness_version": HARNESS_VERSION, "n_runs": 1,
                          "seed": None, "sandbox": "local-macos-mvn",
                          "prompt_template_version": PROMPT_TEMPLATE_VERSION},
        "tracks": {"objective": {"runs": [{
            "run_index": 0,
            "tests_passed": gates["tests_passed"],
            "tests_total": gates["tests_total"],
            "lint": "not_applicable",
            "type_check": "not_applicable",
            "build": gates["build"],
            "completed": completed,
        }], "aggregate": {"metric": "hidden_test_pass_rate",
                          "value": pass_rate if pass_rate is not None else 0.0,
                          "n": 1, "ci": None}}},
        "cost": {
            "tokens_input": usage.get("input_tokens"),
            "tokens_output": usage.get("output_tokens"),
            "tokens_cache_read": usage.get("cache_read_input_tokens"),
            "tokens_cache_creation": usage.get("cache_creation_input_tokens"),
            "cost_usd_estimate": our_cost,
            "cli_reported_cost_usd": agent.get("total_cost_usd"),
            "pricing_source": pricing["pricing_source"],
            "pricing_as_of": pricing["pricing_version"],
        },
    }
    # side-channel details for the report (not part of the schema record)
    meta = {"wall_s": round(wall_s, 1), "num_turns": agent.get("num_turns"),
            "agent_error": agent.get("our_error"), "note": gates.get("note"),
            "session_id": agent.get("session_id")}
    return {"record": record, "meta": meta}


def run_matrix(tasks: list[dict], models: list[tuple[str, str]], repo: Path,
               work_root: Path, out_path: Path, log=print) -> list[dict]:
    pricing = load_pricing()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    results = []
    for task in tasks:
        log(f"TASK {task['task_id']}: {task['subject'][:70]}")
        for model_id, tier in models:
            cell = run_cell(task, model_id, tier, repo, work_root, run_id, pricing, log)
            results.append(cell)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "a") as fh:
                fh.write(json.dumps(cell["record"]) + "\n")
            r = cell["record"]["tracks"]["objective"]["runs"][0]
            log(f"  => build={r['build']} tests={r['tests_passed']}/{r['tests_total']}"
                f" cost=${cell['record']['cost']['cost_usd_estimate']}"
                f" (cli ${cell['record']['cost']['cli_reported_cost_usd']})")
    return results
