"""Agreement of the content-free classifier vs the ADR-0002 human labels.

The human labels were assigned WITH prompt text; the classifier reproduces
them WITHOUT it. The gap is the experiment (ADR-0009). Poor agreement on a
class is a finding about metadata separability, not a bug to tune away."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

CAL_DIR_NAME = "unit-comparison-2026-08-07"


def _kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    labels = set(ca) | set(cb)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def _prf(pairs: list[tuple[str, str]]) -> dict:
    """per-class precision/recall/F1 (human = truth, ours = prediction)."""
    classes = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    out = {}
    for c in classes:
        tp = sum(1 for h, p in pairs if h == c and p == c)
        fp = sum(1 for h, p in pairs if h != c and p == c)
        fn = sum(1 for h, p in pairs if h == c and p != c)
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        f1 = (2 * prec * rec / (prec + rec)) if prec and rec else (0.0 if (tp + fp or tp + fn) else None)
        out[c] = {"support": tp + fn, "precision": prec, "recall": rec, "f1": f1}
    return out


def validate(task_classes_path: Path, calibration_dir: Path) -> dict:
    ours = [json.loads(l) for l in task_classes_path.read_text().splitlines()]
    by_key = {}
    for r in ours:
        u = r["unit_ref"]
        if r["unit"] == "prompt":
            key = ("prompt", u["session_id"][:8], u["turn_range"]["start_turn"])
        elif r["unit"] == "segment":
            key = ("segment", u["session_id"][:8], u["segment_id"].split("-", 1)[1])
        else:
            continue
        by_key[key] = r

    report = {}
    for unit, fname in (("prompt", "prompt_units.jsonl"),
                        ("segment", "segment_units.jsonl")):
        cal = [json.loads(l) for l in
               (calibration_dir / fname).read_text().splitlines()]
        pairs, unmatched, per_pair = [], 0, []
        for c in cal:
            u = c["unit_ref"]
            if unit == "prompt":
                key = ("prompt", u["session_id"], u["turn_range"]["start_turn"])
            else:
                key = ("segment", u["session_id"], u["segment_id"].split("-", 1)[1])
            mine = by_key.get(key)
            if mine is None:
                unmatched += 1
                continue
            h = c["task_type"] or "unclassified"
            p = mine["task_type"] or "unclassified"
            pairs.append((h, p))
            per_pair.append({"key": list(key), "human": h, "ours": p,
                             "rule": mine["method"]["rule_ids"][0],
                             "match": h == p})
        acc = sum(1 for a, b in pairs if a == b) / len(pairs) if pairs else None
        report[unit] = {
            "n_labels": len(cal), "n_matched": len(pairs),
            "n_unmatched_rotated": unmatched,
            "accuracy": acc, "cohens_kappa": _kappa(pairs),
            "per_class": _prf(pairs),
            "confusion": Counter(f"{a} -> {b}" for a, b in pairs if a != b),
            "pairs": per_pair,
        }
    return report


def print_report(report: dict) -> None:
    for unit, r in report.items():
        print(f"\n=== {unit.upper()} (n={r['n_matched']} matched, "
              f"{r['n_unmatched_rotated']} unvalidatable/rotated) ===")
        acc = f"{r['accuracy']:.1%}" if r["accuracy"] is not None else "n/a"
        print(f"accuracy {acc}   Cohen's kappa {r['cohens_kappa']:.3f}")
        print(f"{'class':24s} {'n':>3} {'prec':>6} {'rec':>6} {'f1':>6}")
        for c, m in sorted(r["per_class"].items(), key=lambda x: -x[1]["support"]):
            fmt = lambda v: f"{v:.2f}" if v is not None else "   —"
            print(f"{c:24s} {m['support']:3d} {fmt(m['precision']):>6} "
                  f"{fmt(m['recall']):>6} {fmt(m['f1']):>6}")
        print("top confusions (human -> ours):")
        for k, n in r["confusion"].most_common(8):
            print(f"  {n}x {k}")
