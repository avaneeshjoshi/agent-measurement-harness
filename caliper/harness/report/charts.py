"""Server-side SVG charts for serve (ADR-0017).

Pure functions: aggregated data in, an SVG string out. No library, no
external assets — serve stays offline. The DESIGN.md chart rules are
encoded here, not left to callers:

- every chart's n is part of the fragment (a chart cannot render without it
  — callers pass n_note and it lands in the caption);
- absence is a gap (time axis) or a labeled band (scatter), never a
  zero-height bar and never a point at the origin;
- the figure rides the mark (row bars, tracks) or the paired table
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
    W, PH = 1400, 340
    LEFT, BOT, TOP = 64, 26, 12
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


def _nice_max(v: float) -> float:
    """Round an axis maximum up to a tidy value (reference niceMax)."""
    if v <= 0:
        return 1.0
    import math
    p = 10 ** math.floor(math.log10(v))
    for s in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        if v <= s * p:
            return s * p
    return 10 * p


def cumulative(day_costs: dict[str, float], title: str, meta: str) -> str:
    """Running-total area line over the full date domain (reference
    CUMULATIVE SPEND). Quiet days are flat segments — a day with no priced
    sessions adds $0, which is a true zero, not an absence. Fewer than two
    days cannot make a curve; the caller renders the empty-state sentence
    instead. Hover: a full-height hit slot per day carries running total
    and that day's spend."""
    if len(day_costs) < 2:
        return ""
    days = _days_between(min(day_costs), max(day_costs))
    # column-sized viewBox: this chart lives in a half-width .cols cell,
    # and a 1400-wide box scaled to ~660px renders 5px axis text
    W, PH = 700, 320
    LEFT, BOT, TOP, RIGHT = 56, 24, 14, 14
    plot_w, plot_h = W - LEFT - RIGHT, PH - BOT - TOP

    running, acc = [], 0.0
    for d in days:
        acc += day_costs.get(d, 0.0)
        running.append(acc)
    total = acc
    mx = _nice_max(total)

    def x(i):
        return LEFT + (i / (len(days) - 1)) * plot_w

    def y(v):
        return TOP + plot_h * (1 - v / mx)

    parts = []
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        yy = y(mx * frac)
        parts.append(f'<line x1="{LEFT}" y1="{yy:.1f}" x2="{W - RIGHT}" '
                     f'y2="{yy:.1f}" stroke="var(--edge)"/>')
        parts.append(f'<text x="{LEFT - 8}" y="{yy + 4:.1f}" '
                     f'text-anchor="end" class="ax">${mx * frac:,.0f}</text>')
    ticks = min(4, len(days))
    for i in range(ticks):
        idx = round(i * (len(days) - 1) / max(ticks - 1, 1))
        anchor = "start" if i == 0 else ("end" if i == ticks - 1 else "middle")
        parts.append(f'<text x="{x(idx):.1f}" y="{PH - 8}" '
                     f'text-anchor="{anchor}" class="ax">'
                     f"{days[idx][5:]}</text>")

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(running))
    parts.append(f'<path d="M{x(0):.1f},{y(0):.1f} '
                 + " ".join(f"L{x(i):.1f},{y(v):.1f}"
                            for i, v in enumerate(running))
                 + f' L{x(len(days) - 1):.1f},{y(0):.1f} Z" '
                 'fill="var(--cat-1)" opacity="0.13"/>')
    parts.append(f'<path d="M{pts.replace(" ", " L")}" fill="none" '
                 'stroke="var(--cat-1)" stroke-width="2" '
                 'stroke-linejoin="round"/>')
    end_y = max(y(total) - 9, TOP + 10)
    parts.append(f'<text x="{W - RIGHT}" y="{end_y:.1f}" text-anchor="end" '
                 f'class="pt" font-weight="700">${total:,.0f}</text>')

    slot = plot_w / len(days)
    for i, d in enumerate(days):
        tip = tip_html(d, [
            (None, "running total", f"${running[i]:,.2f}"),
            (None, "that day", f"${day_costs.get(d, 0.0):,.2f}"),
        ])
        parts.append(f'<g data-tip="{tip}"><rect class="hit" '
                     f'x="{LEFT + i * slot:.2f}" y="{TOP}" '
                     f'width="{slot:.2f}" height="{plot_h}" '
                     'fill="transparent"/></g>')

    svg = (f'<svg viewBox="0 0 {W} {PH}" role="img" '
           f'preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>')
    return figure(title, meta, svg)


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
