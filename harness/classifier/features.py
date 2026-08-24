"""Feature assembly: prompt units / segments / session records -> one flat,
content-free feature dict the rules consume.

Everything here is derived from prompt_unit.schema / session.schema fields
only. The names in FEATURES are what task_class.features_used reports."""

from __future__ import annotations

_READ_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead", "TodoRead",
               "TaskList", "TaskGet", "ListMcpResourcesTool", "ReadMcpResourceTool"}
_WEB_TOOLS = {"WebSearch", "WebFetch", "web_search_call", "tool_search_call",
              "web_search", "web_fetch"}
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
_BROWSER_MARKERS = ("mcp__claude-in-chrome__", "mcp__playwright__", "mcp__puppeteer__",
                    "computer", "browser_")


def _tool_family(name: str) -> str:
    if any(name.startswith(m) or m in name.lower() for m in _BROWSER_MARKERS):
        return "browser"
    if name in _WEB_TOOLS:
        return "web"
    if name in _READ_TOOLS:
        return "read"
    if name in _EDIT_TOOLS:
        return "edit"
    if name in ("Bash", "exec", "exec_command", "run", "js", "write_stdin", "shell"):
        return "shell"
    return "other"


# ADR-0013 (pre-registered): flow context reaches at most this many prompt
# turns in either direction, and never across a segment boundary — segments
# are the flow unit (segmenter 0.1.0), so "neighborhood" inherits their
# 30-minute-gap/branch/file-set semantics instead of inventing new ones.
NEIGHBORHOOD_RADIUS = 3


def neighborhood_features(us: list[dict], idx: int,
                          segment_indices: set[int]) -> dict:
    """Browser/edit activity in the OTHER windows of this unit's segment
    within NEIGHBORHOOD_RADIUS turns (ADR-0013). This is what makes a
    browser check three prompts after an edit visible to the edit's window —
    the flow-context blindness ADR-0009 named as rules-0.1.x's honest miss."""
    me = us[idx]["turn_index"]
    nbr_browser = nbr_edits = 0
    for u in us:
        t = u["turn_index"]
        if t == me or t not in segment_indices \
                or abs(t - me) > NEIGHBORHOOD_RADIUS:
            continue
        w = u.get("window") or {}
        for name, c in (w.get("tool_counts") or {}).items():
            if _tool_family(name) == "browser":
                nbr_browser += c
        nbr_edits += len(w.get("files_edited") or [])
    return {"nbr_browser": nbr_browser, "nbr_edits": nbr_edits}


def features_from_units(units: list[dict],
                        neighborhood: dict | None = None) -> dict:
    """Aggregate one or more prompt units (one for unit=prompt, a segment's
    members for unit=segment) into the rule-facing feature dict.
    `neighborhood` is prompt-grain only (segment/session grains already
    aggregate whole flows); absent -> zeros, so the flow rules can't fire."""
    tool_counts: dict[str, int] = {}
    files: dict[str, dict] = {}
    la = lr = 0
    la_known = False
    interrupted = False
    for u in units:
        w = u["window"]
        for t, c in (w.get("tool_counts") or {}).items():
            tool_counts[t] = tool_counts.get(t, 0) + c
        for f in w.get("files_edited") or []:
            files[f["file_ref"]] = f
        if w.get("lines_added") is not None:
            la_known = True
            la += w["lines_added"]
            lr += w.get("lines_removed") or 0
        if w.get("interrupted"):
            interrupted = True

    fam: dict[str, int] = {}
    for t, c in tool_counts.items():
        k = _tool_family(t)
        fam[k] = fam.get(k, 0) + c

    fl = list(files.values())
    n_files = len(fl)
    def frac(key):
        return (sum(1 for f in fl if f.get(key)) / n_files) if n_files else 0.0

    return {
        "n_units": len(units),
        "tool_calls": sum(tool_counts.values()),
        "tool_counts": tool_counts,
        "fam": fam,  # browser/web/read/edit/shell/other call counts
        "files_edited": n_files,
        "new_files": sum(1 for f in fl if f.get("is_new_file")),
        "top_dirs": len({f["top_dir_ref"] for f in fl}),
        "frac_test": frac("is_test_path"),
        "frac_docs": frac("is_docs_path"),
        "frac_config": frac("is_config_path"),
        "frac_agent": frac("is_agent_config_path"),
        "lines_added": la if la_known else None,
        "lines_removed": lr if la_known else None,
        "interrupted": interrupted,
        "nbr_browser": (neighborhood or {}).get("nbr_browser", 0),
        "nbr_edits": (neighborhood or {}).get("nbr_edits", 0),
    }


def features_from_session(rec: dict) -> dict:
    """Session-record fallback (cursor, or any session without prompt units).
    Maps session.schema aggregates onto the same feature names."""
    tool_counts = {t["tool_name"]: t["count"]
                   for t in rec.get("tool_call_pattern") or []}
    fam: dict[str, int] = {}
    for t, c in tool_counts.items():
        k = _tool_family(t)
        fam[k] = fam.get(k, 0) + c
    d = rec.get("diff_stats") or {}
    langs = rec.get("languages") or []
    n_files = d.get("files_touched", 0)
    docsish = {"markdown", "text"}
    configish = {"json", "yaml", "toml", "xml"}
    lang_set = set(langs)
    return {
        "n_units": None,
        "tool_calls": sum(tool_counts.values()),
        "tool_counts": tool_counts,
        "fam": fam,
        "files_edited": n_files,
        "new_files": 0,
        "top_dirs": 0,  # unknown at session grain
        # session records carry languages, not per-file flags: coarse proxies
        "frac_test": 0.0,
        "frac_docs": 1.0 if (n_files and lang_set and lang_set <= docsish) else 0.0,
        "frac_config": 1.0 if (n_files and lang_set and lang_set <= configish) else 0.0,
        "frac_agent": 0.0,
        "lines_added": d.get("lines_added"),
        "lines_removed": d.get("lines_removed"),
        "interrupted": bool((rec.get("turns") or {}).get("interrupted_tool_calls")),
        "nbr_browser": 0,  # no unit ordering exists at session grain
        "nbr_edits": 0,
    }

FEATURE_NAMES = ["window.tool_counts", "window.files_edited(flags)",
                 "window.lines_added", "window.lines_removed",
                 "window.interrupted", "files_edited.top_dir_ref",
                 "neighborhood.nbr_browser", "neighborhood.nbr_edits"]
