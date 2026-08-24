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


def figure(title: str, meta: str, inner: str) -> str:
    """The chart panel: a one-line header bar — uppercase title left, the n
    and honesty notes faint on the right — ruled off from the chart body.
    The caption never crowds the chart (ADR-0017 postscript 2)."""
    return (f'<figure class="chart"><figcaption><span class="ct">'
            f'{H.escape(title)}</span><span class="cm">{H.escape(meta)}'
            f'</span></figcaption><div class="cbody">{inner}</div></figure>')


def tip_html(header: str, rows: list[tuple[str | None, str, str]],
             total: str | None = None) -> str:
    """data-tip attribute payload for the instant pointer tooltip
    (views.JS): a boxed panel with a header line, swatch·name·value rows,
    and a ruled Total. Server-authored HTML, entity-escaped into the
    attribute; the tooltip sets it back as innerHTML. Native SVG <title>
    is delayed and tiny — measured unusable in the first walkthrough."""
    body = "".join(
        '<span class="tr">'
        + (f'<i class="sw" style="background:var({tok})"></i>' if tok else "")
        + f"{H.escape(lab)}<b>{H.escape(val)}</b></span>"
        for tok, lab, val in rows)
    tot = (f'<span class="tt">Total<b>{H.escape(total)}</b></span>'
           if total else "")
    return H.escape(
        f'<span class="th">{H.escape(header)}</span>{body}{tot}', quote=True)


def spend_columns(per_day: dict[str, dict[str, float]], groups: list[str],
                  tokens: dict[str, str], title: str, meta: str) -> str:
    """Daily stacked columns. per_day: day -> {group: $}. Days absent from
    per_day render as gaps — ground, never a zero-height bar. Each active
    day carries a full-height invisible hit rect so hovering ANYWHERE in
    its slot shows the breakdown instantly. Columns do not navigate:
    filtering the page to a single day re-renders one stretched bar, which
    is not a destination (ADR-0017 postscript 2)."""
    if not per_day:
        return ""
    days = _days_between(min(per_day), max(per_day))
    W, PH = 960, 300
    LEFT, BOT, TOP = 56, 24, 10
    plot_w, plot_h = W - LEFT - 8, PH - BOT - TOP
    cw = plot_w / len(days)
    bw = max(1.5, cw * 0.8)
    peak = max(sum(g.values()) for g in per_day.values()) or 1.0

    parts = []
    # quarter gridlines + $ labels
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
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
        rows = []
        rects = []
        for grp in groups:
            v = g.get(grp, 0.0)
            if not v:
                continue
            h = plot_h * v / peak
            y -= h
            rects.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bw:.2f}" '
                         f'height="{max(h, 0.8):.2f}" '
                         f'fill="var({tokens[grp]})"/>')
            rows.append((tokens[grp], grp, f"${v:,.2f}"))
        tip = tip_html(day, rows, f"${total:,.2f}")
        parts.append(
            f'<g data-tip="{tip}">'
            f'<rect class="hit" x="{LEFT + i * cw:.2f}" y="{TOP}" '
            f'width="{cw:.2f}" height="{plot_h}" fill="transparent"/>'
            f"{''.join(rects)}</g>")

    legend = swatch_legend([(g, tokens[g]) for g in groups])
    svg = (f'<svg viewBox="0 0 {W} {PH}" role="img" '
           f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>')
    return figure(title, meta, svg + legend)


def proportion_bar(segments: list[tuple[str, int]]) -> str:
    """One stacked 100% bar: (label, count) segments in the given order,
    each hoverable for label · count · share. The caller renders the label
    line (name left, n right) above it — the reference row pattern."""
    total = sum(c for _, c in segments) or 1
    W, BH = 720, 18
    x = 0.0
    rects = []
    for label, cnt in segments:
        if not cnt:
            continue
        w = W * cnt / total
        tip = H.escape(f"{label} · {cnt} · {cnt / total:.0%}", quote=True)
        rects.append(
            f'<rect x="{x:.2f}" y="0" width="{max(w, 1):.2f}" height="{BH}" '
            f'fill="var({cat_token(label)})" data-tip="{tip}"/>')
        x += w
    return (f'<svg class="pbar" viewBox="0 0 {W} {BH}" '
            f'preserveAspectRatio="none">{"".join(rects)}</svg>')


def scatter(points: list[dict], qs: str) -> str:
    """Cost × survival, one circle per repo, sized by √commits, the repo
    name and its pair as text beside every mark. Points only — repos that
    cannot be plotted go in the caller's labeled band, never here at an
    origin. x is a √ scale (stated by the caller's caption)."""
    if not points:
        return ""
    W, PH = 960, 360
    LEFT, BOT, TOP, RIGHT = 52, 26, 12, 150
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

    # collision-aware label placement: repos cluster at high survival on
    # real data, so labels stagger downward until they stop overlapping —
    # the figure must ride the mark, and an unreadable label rides nothing
    placed: list[tuple[float, float, float]] = []  # (x0, x1, y)
    for p in sorted(points, key=lambda q: -q["commits"]):
        x, y = sx(p["cost"]), sy(p["surv"])
        r = 4 + 2.2 * sqrt(p["commits"])
        text = f"{p['name']} {p['surv']:.0%} (n={p['commits']})"
        lw = 6.2 * len(text)
        lx, ly = x + r + 4, y + 4
        while any(not (lx + lw < x0 or lx > x1 or abs(ly - yy) >= 13)
                  for x0, x1, yy in placed):
            ly += 14
        placed.append((lx, lx + lw, ly))
        tip = tip_html(p["name"], [
            (None, "30d survival", f"{p['surv']:.0%} (n={p['commits']})"),
            (None, "session list-$", f"${p['cost']:,.2f}"),
            (None, "commits", f"{p['commits']}"),
        ])
        parts.append(
            f'<a href="/repo/{p["ref"]}{qs}" data-tip="{tip}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
            'fill="var(--accent)" fill-opacity="0.25" '
            'stroke="var(--accent)"/>'
            f'<text x="{lx:.1f}" y="{ly:.1f}" class="pt">'
            f"{H.escape(p['name'])} <tspan class='ax'>"
            f"{p['surv']:.0%} (n={p['commits']})</tspan></text></a>")

    return (f'<svg viewBox="0 0 {W} {PH}" role="img" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>')


def bucket_bar(buckets: dict[str, int], max_total: int) -> str:
    """One full-width bar on a faint track: the filled length is this
    model's share of the chart's largest total, split by bucket, each
    segment hoverable. The caller renders the label line (model left,
    figures right) above it — the bar is never the sole carrier."""
    total = sum(buckets.get(b, 0) for b, _ in BUCKET_TOKENS)
    if not total or not max_total:
        return ""
    W, BH = 720, 16
    w_total = max(2.0, W * total / max_total)
    x = 0.0
    rects = [f'<rect x="0" y="0" width="{W}" height="{BH}" '
             'fill="var(--surface-2)"/>']
    for bucket, tok in BUCKET_TOKENS:
        v = buckets.get(bucket, 0)
        if not v:
            continue
        w = w_total * v / total
        tip = H.escape(f"{bucket.replace('_', ' ')} · {v:,} tokens · "
                       f"{v / total:.0%}", quote=True)
        rects.append(
            f'<rect x="{x:.2f}" y="0" width="{max(w, 0.8):.2f}" '
            f'height="{BH}" fill="var({tok})" data-tip="{tip}"/>')
        x += w
    return (f'<svg class="bbar" viewBox="0 0 {W} {BH}" '
            f'preserveAspectRatio="none">{"".join(rects)}</svg>')
