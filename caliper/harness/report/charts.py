"""Server-side SVG charts for serve (ADR-0017).

Pure functions: aggregated data in, an SVG string out. No library, no
external assets — serve stays offline. The DESIGN.md chart rules are
encoded here, not left to callers:

- every chart's n is part of the fragment (a chart cannot render without it
  — callers pass n_note and it lands in the caption);
- absence is a gap (time axis) or a labeled band (scatter), never a
  zero-height bar and never a point at the origin;
- the figure rides the mark (row bars, scatter labels) or the paired table
  beneath (dense time series), and hover carries the exact breakdown via
  native <title> — no tooltip script;
- nothing animates: static markup, no transitions, no entrance states.

Colors come only from CSS custom properties (the chart-category tokens
ADR-0017 added to DESIGN.md, and the bucket aliases from the report).
`unclassified` deliberately renders in the absent gray — it is the
instrument's own absence and must look like it. Color never carries a
category alone: legends and the paired tables carry the words.
"""

from __future__ import annotations

import html as H
from datetime import date, timedelta
from math import sqrt

# Fixed task-type -> category-token assignment (taxonomy order, ADR-0017).
TASK_ORDER = ("exploratory_qa", "feature_implementation",
              "ui_verification_loop", "single_file_bug_fix",
              "boilerplate_scaffolding", "multi_file_refactor",
              "test_authoring", "documentation", "config_infra",
              "agent_meta_work")

BUCKET_TOKENS = (("input", "--in"), ("output", "--out"),
                 ("cache_read", "--cr"), ("cache_creation", "--cw"))


def cat_token(label: str) -> str:
    if label == "unclassified":
        return "--absent"
    if label == "other":
        return "--text-3"
    if label in TASK_ORDER:
        return f"--cat-{TASK_ORDER.index(label) + 1}"
    return f"--cat-{hash(label) % 10 + 1}"  # unknown future classes cycle


def _days_between(d0: str, d1: str) -> list[str]:
    a, b = date.fromisoformat(d0), date.fromisoformat(d1)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def swatch_legend(items: list[tuple[str, str]]) -> str:
    """(label, token) pairs -> the words-first legend line."""
    return ('<p class="legend">' + "".join(
        f'<i class="sw" style="background:var({tok})"></i>{H.escape(lab)}'
        for lab, tok in items) + "</p>")


def spend_columns(per_day: dict[str, dict[str, float]], groups: list[str],
                  tokens: dict[str, str], ui: dict, caption: str) -> str:
    """Daily stacked columns. per_day: day -> {group: $}. Days absent from
    per_day render as gaps — ground, never a zero-height bar. Each column
    links to that day's filtered overview (the other URL state preserved);
    <title> carries the breakdown."""
    from urllib.parse import urlencode
    base_ui = {k: v for k, v in ui.items()
               if k not in ("from", "to", "range")}
    if not per_day:
        return ""
    days = _days_between(min(per_day), max(per_day))
    W, PH = 960, 200
    LEFT, BOT, TOP = 52, 22, 8
    plot_w, plot_h = W - LEFT - 8, PH - BOT - TOP
    cw = plot_w / len(days)
    bw = max(1.0, cw * 0.72)
    peak = max(sum(g.values()) for g in per_day.values()) or 1.0

    parts = []
    # gridlines + $ labels (0 / half / peak)
    for frac in (0.0, 0.5, 1.0):
        y = TOP + plot_h * (1 - frac)
        parts.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{W - 8}" '
                     f'y2="{y:.1f}" stroke="var(--edge)"/>')
        parts.append(f'<text x="{LEFT - 6}" y="{y + 4:.1f}" text-anchor="end" '
                     f'class="ax">${peak * frac:,.0f}</text>')
    # x tick labels, ~6 across
    step = max(1, len(days) // 6)
    for i in range(0, len(days), step):
        x = LEFT + i * cw + cw / 2
        parts.append(f'<text x="{x:.1f}" y="{PH - 6}" text-anchor="middle" '
                     f'class="ax">{days[i][5:]}</text>')

    for i, day in enumerate(days):
        g = per_day.get(day)
        if not g:
            continue  # a quiet day is a gap, never a zero bar
        total = sum(g.values())
        x = LEFT + i * cw + (cw - bw) / 2
        y = TOP + plot_h
        title = [f"{day} · ${total:,.2f}"]
        rects = []
        for grp in groups:
            v = g.get(grp, 0.0)
            if not v:
                continue
            h = plot_h * v / peak
            y -= h
            rects.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw:.2f}" '
                         f'height="{max(h, 0.5):.2f}" '
                         f'fill="var({tokens[grp]})"/>')
            title.append(f"{grp} ${v:,.2f}")
        href = "/?" + H.escape(urlencode({**base_ui, "from": day, "to": day}))
        parts.append(f'<a href="{href}"><title>{H.escape(chr(10).join(title))}'
                     f"</title>{''.join(rects)}</a>")

    legend = swatch_legend([(g, tokens[g]) for g in groups])
    return (f'<figure class="chart"><figcaption>{caption}</figcaption>'
            f'<svg viewBox="0 0 {W} {PH}" role="img" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>'
            f"{legend}</figure>")


def proportion_bar(segments: list[tuple[str, int]], n_label: str) -> str:
    """One stacked 100% bar: (label, count) segments in the given order.
    The figure (n) rides the row's end; <title> per segment carries
    label · count · share. Returns one flex row (label outside)."""
    total = sum(c for _, c in segments) or 1
    W, BH = 720, 16
    x = 0.0
    rects = []
    for label, cnt in segments:
        if not cnt:
            continue
        w = W * cnt / total
        rects.append(
            f'<rect x="{x:.2f}" y="0" width="{max(w, 1):.2f}" height="{BH}" '
            f'fill="var({cat_token(label)})"><title>'
            f"{H.escape(f'{label} · {cnt} · {cnt / total:.0%}')}"
            "</title></rect>")
        x += w
    return (f'<svg class="pbar" viewBox="0 0 {W} {BH}" '
            f'preserveAspectRatio="none">{"".join(rects)}</svg>'
            f'<span class="n-of">({H.escape(n_label)})</span>')


def scatter(points: list[dict], qs: str) -> str:
    """Cost × survival, one circle per repo, sized by √commits, the repo
    name and its pair as text beside every mark. Points only — repos that
    cannot be plotted go in the caller's labeled band, never here at an
    origin. x is a √ scale (stated by the caller's caption)."""
    if not points:
        return ""
    W, PH = 960, 300
    LEFT, BOT, TOP, RIGHT = 52, 26, 10, 150
    plot_w, plot_h = W - LEFT - RIGHT, PH - BOT - TOP
    max_cost = max(p["cost"] for p in points) or 1.0

    def sx(c):
        return LEFT + plot_w * sqrt(c / max_cost)

    def sy(s):
        return TOP + plot_h * (1 - s)

    parts = []
    for frac in (0.0, 0.5, 1.0):
        y = sy(frac)
        parts.append(f'<line x1="{LEFT}" y1="{y:.1f}" x2="{W - RIGHT}" '
                     f'y2="{y:.1f}" stroke="var(--edge)"/>')
        parts.append(f'<text x="{LEFT - 6}" y="{y + 4:.1f}" text-anchor="end" '
                     f'class="ax">{frac:.0%}</text>')
    for frac in (0.0, 0.25, 1.0):
        c = max_cost * frac
        x = sx(c)
        parts.append(f'<text x="{x:.1f}" y="{PH - 8}" text-anchor="middle" '
                     f'class="ax">${c:,.0f}</text>')

    for p in sorted(points, key=lambda q: -q["commits"]):
        x, y = sx(p["cost"]), sy(p["surv"])
        r = 4 + 2.2 * sqrt(p["commits"])
        label = (f"{p['name']} {p['surv']:.0%} "
                 f"(n={p['commits']}) · ${p['cost']:,.2f}")
        parts.append(
            f'<a href="/repo/{p["ref"]}{qs}"><title>{H.escape(label)}</title>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            'fill="var(--accent)" fill-opacity="0.25" '
            'stroke="var(--accent)"/>'
            f'<text x="{x + r + 4:.1f}" y="{y + 4:.1f}" class="pt">'
            f"{H.escape(p['name'])} <tspan class='ax'>"
            f"{p['surv']:.0%} (n={p['commits']})</tspan></text></a>")

    return (f'<svg viewBox="0 0 {W} {PH}" role="img" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>')


def bucket_bar(buckets: dict[str, int], max_total: int) -> str:
    """One horizontal stacked bar, absolute scale (share of the chart's
    max). The caller renders the model name before it and the figures
    after — the bar is never the sole carrier."""
    total = sum(buckets.get(b, 0) for b, _ in BUCKET_TOKENS)
    if not total or not max_total:
        return ""
    W, BH = 400, 12
    w_total = max(2.0, W * total / max_total)
    x = 0.0
    rects = []
    for bucket, tok in BUCKET_TOKENS:
        v = buckets.get(bucket, 0)
        if not v:
            continue
        w = w_total * v / total
        rects.append(
            f'<rect x="{x:.2f}" y="0" width="{max(w, 0.8):.2f}" '
            f'height="{BH}" fill="var({tok})"><title>'
            f"{H.escape(f'{bucket} {v:,} ({v / total:.0%})')}</title></rect>")
        x += w
    return (f'<svg class="bbar" viewBox="0 0 {W} {BH}" '
            f'preserveAspectRatio="none">{"".join(rects)}</svg>')
