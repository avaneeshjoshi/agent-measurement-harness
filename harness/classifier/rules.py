"""Ruleset rules-0.2.0 — readable, versioned, each rule with its rationale.
0.2.0 adds the neighborhood flow rules R01c/R01d (ADR-0013, pre-registered
before their one-shot validation; thresholds are NOT to be tuned against the
81 calibration labels — the ADR-0009 freeze rule applies).

Design constraints:
- Content-free features only (features.py); every emitted record lists them.
- First-match wins, ordered most-specific -> default. Confidences are static
  per rule and deliberately modest — they encode rule reliability expectations,
  not per-instance certainty.
- Tuned on the ADR-0001/0002 written descriptions and on stated priors (e.g.
  exploratory_qa produces no edits — an EMPTY files_edited set is a positive
  signal, not missing data). NOT iterated against the calibration labels;
  agreement numbers are findings (ADR-0009).
- 'unclassified' is a legal outcome: shell-only windows with no edits carry
  too little signal to separate exploration from verification from ops.
"""

from __future__ import annotations

MIN_BROWSER_CALLS = 3


def classify_features(f: dict) -> dict:
    """-> {task_type|None, status, confidence, rule_id, rationale, alternatives}"""

    edits = f["files_edited"] > 0
    fam = f["fam"]
    browser = fam.get("browser", 0)
    web = fam.get("web", 0)
    shell = fam.get("shell", 0)
    reads = fam.get("read", 0)
    nbr_browser = f.get("nbr_browser", 0)
    nbr_edits = f.get("nbr_edits", 0)

    # R01 browser_verification: browser/computer-use tools dominate the window.
    # Rationale (ADR-0001 provisional class): iterating on visual behavior;
    # huge tool traffic, modest diffs. Fires above edits because those windows
    # usually also touch files.
    if browser >= MIN_BROWSER_CALLS and browser >= f["tool_calls"] * 0.3:
        return _r("ui_verification_loop", 0.7, "R01-browser-loop",
                  f"{browser} browser-automation calls dominate the window")

    # R01b browser_verification (presence form, rules-0.1.1): the human-label
    # definition is "editing WITH browser checking" — at prompt grain the
    # browser calls are diluted among edits, so ANY browser presence in an
    # edit-bearing window marks the verification loop, at lower confidence.
    # Windows with zero browser calls labeled ui_verification_loop by humans
    # remain honest misses: flow context is invisible to single-window metadata.
    if edits and browser >= 1:
        return _r("ui_verification_loop", 0.55, "R01b-browser-present-edits",
                  f"{browser} browser call(s) alongside edits: edit-and-check loop")

    # R01c neighborhood browser (rules-0.2.0, ADR-0013): the flow context
    # R01b called an honest miss. A browser check often lands a few prompts
    # AFTER the edit it verifies; neighborhood = same segmenter-0.1.0
    # segment, turn distance <= 3. Edit-bearing window, zero in-window
    # browser, any adjacent browser activity -> part of the loop.
    if edits and browser == 0 and nbr_browser >= 1:
        return _r("ui_verification_loop", 0.5, "R01c-neighborhood-browser",
                  f"{nbr_browser} browser call(s) in adjacent windows of "
                  "the same flow")

    # R02 agent_meta: edited files are predominantly agent-tooling config.
    # Rationale (ADR-0001 provisional class): tending the agent itself.
    if edits and f["frac_agent"] >= 0.5:
        return _r("agent_meta_work", 0.7, "R02-agent-config-paths",
                  "majority of edited files are agent-config paths")

    # R03 docs_only: every edited file is documentation.
    if edits and f["frac_docs"] >= 0.99:
        return _r("documentation", 0.75, "R03-docs-paths-only",
                  "all edited files are documentation paths")

    # R04 test_centric: edits are majority test files.
    # Majority (not all): test authoring commonly touches a helper too.
    if edits and f["frac_test"] >= 0.6:
        return _r("test_authoring", 0.65, "R04-test-paths-majority",
                  "majority of edited files are test paths")

    # R05 config_only: every edited file is config.
    if edits and f["frac_config"] >= 0.99:
        return _r("config_infra", 0.7, "R05-config-paths-only",
                  "all edited files are configuration paths")

    # R01d flow sandwich (rules-0.2.0, ADR-0013): a no-edit window inside an
    # edit-and-check flow (shell checks between browser-verified edits).
    # Zero edits demands stronger flow evidence than R01c: >=2 neighborhood
    # browser calls AND neighborhood edits. Sits above R06/R07/R08 so the
    # flow can reclaim what those would swallow.
    if not edits and nbr_browser >= 2 and nbr_edits >= 1:
        return _r("ui_verification_loop", 0.45, "R01d-flow-sandwich",
                  f"no edits here, but {nbr_browser} browser calls and "
                  f"{nbr_edits} edited file(s) in the surrounding flow")

    # R06 no-activity QA: no tools, no edits — a pure answer-from-context turn.
    # Empty files_edited is a POSITIVE exploratory signal (stated prior:
    # ~30% of prompts are exploratory_qa and produce no edits).
    if not edits and f["tool_calls"] == 0:
        return _r("exploratory_qa", 0.7, "R06-no-activity",
                  "no tool calls and no edits: pure Q&A from context")

    # R07 research QA: zero edits with read/search/web activity. Web tools are
    # a strong exploratory marker (stated prior), so confidence rises with them.
    if not edits and (reads + web) > 0 and shell <= (reads + web):
        conf = 0.75 if web > 0 else 0.6
        return _r("exploratory_qa", conf, "R07-read-search-no-edits",
                  "read/search/web activity with zero edits")

    # R08 shell-only, no edits: too ambiguous from metadata (could be
    # exploration, ops, or verification). Declining to guess is the honest
    # output; this share is reported.
    if not edits:
        return {"task_type": None, "status": "unclassified", "confidence": 0.5,
                "rule_id": "R08-shell-only-unclassified",
                "rationale": "shell-dominated window with no edits: "
                             "exploration/ops/verification not separable "
                             "from metadata", "alternatives": []}

    # --- edit-bearing windows below ---
    la, lr = f["lines_added"], f["lines_removed"]

    # R09 scaffolding: mostly NEW files, growth-dominated diff.
    if f["new_files"] >= 3 and (la is None or lr is None or lr <= 0.15 * max(la, 1)):
        return _r("boilerplate_scaffolding", 0.6, "R09-new-file-burst",
                  f"{f['new_files']} new files, additions dominate")

    # R10 single-file small fix: one file, small balanced diff with deletions.
    # Weak by design — bug-fix vs small feature is barely separable from
    # metadata (ADR-0009); emitted as ambiguous with the alternative attached.
    if f["files_edited"] == 1 and la is not None and lr is not None \
            and 0 < la + lr <= 40 and lr > 0:
        return {"task_type": "single_file_bug_fix", "status": "ambiguous",
                "confidence": 0.45, "rule_id": "R10-single-small-balanced",
                "rationale": "one file, small diff with deletions",
                "alternatives": [{"task_type": "feature_implementation",
                                  "confidence": 0.4}]}

    # R11 refactor-shaped: several files, deletion-heavy/balanced, no new files.
    if f["files_edited"] >= 3 and f["new_files"] == 0 and la is not None \
            and lr is not None and lr > 0 and la <= 1.5 * lr:
        return _r("multi_file_refactor", 0.5, "R11-balanced-multifile",
                  "3+ existing files, balanced add/remove")

    # R12 feature default: any remaining edit-bearing window. The bulk class.
    return _r("feature_implementation", 0.55, "R12-edit-default",
              "edit-bearing window not matching a specific shape")


def _r(task_type, conf, rule_id, rationale):
    return {"task_type": task_type, "status": "classified", "confidence": conf,
            "rule_id": rule_id, "rationale": rationale, "alternatives": []}
