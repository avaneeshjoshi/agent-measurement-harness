"""Render the collected summary to one self-contained HTML file. No server,
no external assets, no scripts beyond none at all — a document."""

from __future__ import annotations

import html as H

NR = '<span class="nr">not recorded</span>'

CSS = """
:root { color-scheme: light;
  --page:#f9f9f7; --card:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --line:#e1e0d9; --ring:rgba(11,11,11,.1); --acc:#2a78d6; --acc2:#eb6834;
  --acc3:#1baf7a; --warn:#ec835a; --in:#2a78d6; --out:#eb6834; --cr:#9ec5f4; --cw:#1baf7a; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  color-scheme: dark;
  --page:#0d0d0d; --card:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --ring:rgba(255,255,255,.1); --acc:#3987e5; --acc2:#d95926;
  --acc3:#199e70; --warn:#ec835a; --in:#3987e5; --out:#d95926; --cr:#1c5cab; --cw:#199e70; } }
:root[data-theme="dark"] {
  color-scheme: dark;
  --page:#0d0d0d; --card:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --line:#2c2c2a; --ring:rgba(255,255,255,.1); --acc:#3987e5; --acc2:#d95926;
  --acc3:#199e70; --warn:#ec835a; --in:#3987e5; --out:#d95926; --cr:#1c5cab; --cw:#199e70; }
* { box-sizing: border-box; }
body { margin:0; background:var(--page); color:var(--ink);
  font:14.5px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:1020px; margin:0 auto; padding:36px 24px 64px; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:17px; margin:34px 0 4px; }
.sub { color:var(--ink2); margin:0; max-width:74ch; }
.meta { font:12px ui-monospace,Menlo,monospace; color:var(--muted); margin:6px 0 0; }
.note { font-size:13px; color:var(--ink2); margin:6px 0 10px; max-width:80ch; }
.banner { background:var(--card); border:1px solid var(--ring); border-left:3px solid var(--acc2);
  border-radius:6px; padding:10px 14px; margin:14px 0 0; font-size:13.5px; color:var(--ink2); }
.banner b { color:var(--ink); }
table { border-collapse:collapse; width:100%; background:var(--card);
  border:1px solid var(--ring); border-radius:6px; font-variant-numeric:tabular-nums; margin:8px 0; }
th { font-size:10.5px; letter-spacing:.09em; text-transform:uppercase; color:var(--muted);
  text-align:left; padding:8px 10px 6px; border-bottom:1px solid var(--line); }
td { padding:5px 10px; border-bottom:1px solid var(--line); font-size:13px; }
tr:last-child td { border-bottom:none; }
td.r, th.r { text-align:right; }
.nr { color:var(--muted); font-style:italic; font-size:12px; }
.bar { display:inline-block; height:9px; border-radius:2px; vertical-align:middle; }
.src { font-size:11.5px; color:var(--muted); margin:2px 0 0; }
.wrap { overflow-x:auto; }
.legend { font-size:12px; color:var(--ink2); margin:4px 0; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 4px 0 10px; vertical-align:baseline; }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
@media (max-width:760px){ .grid2 { grid-template-columns:1fr; } }
.cav { background:var(--card); border:1px solid var(--ring); border-left:3px solid var(--warn);
  border-radius:6px; padding:12px 16px; font-size:13px; color:var(--ink2); }
.cav ul { margin:6px 0 0; padding-left:18px; } .cav li { margin:3px 0; }
.mixrow td:first-child { color:var(--ink2); }
"""


def _fmt(n, money=False):
    if n is None:
        return NR
    if money:
        return f"${n:,.2f}"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


def _tok_bar(c: dict, max_total: int) -> str:
    total = sum(c.get(k, 0) for k in ("input", "output", "cache_read", "cache_creation"))
    if not total or not max_total:
        return ""
    w = max(2, int(220 * total / max_total))
    parts = []
    for key, var in (("input", "--in"), ("output", "--out"),
                     ("cache_read", "--cr"), ("cache_creation", "--cw")):
        frac = c.get(key, 0) / total
        pw = max(1, int(w * frac)) if c.get(key) else 0
        if pw:
            parts.append(f'<span class="bar" style="width:{pw}px;background:var({var})"></span>')
    return "".join(parts)


def _spend_table(title: str, data: dict, src: str, top: int = 14,
                 chrono: bool = False) -> str:
    if chrono:
        rows = sorted(data.items())[:top]
    else:
        rows = sorted(data.items(), key=lambda kv: -sum(
            kv[1].get(k, 0) for k in ("input", "output", "cache_read", "cache_creation")))[:top]
    max_total = max((sum(c.get(k, 0) for k in ("input", "output", "cache_read", "cache_creation"))
                     for _, c in rows), default=0)
    out = [f"<h3>{H.escape(title)}</h3>", '<div class="wrap"><table><tr>'
           '<th></th><th class="r">sessions</th><th class="r">input</th>'
           '<th class="r">output</th><th class="r">cache read</th>'
           '<th class="r">cache write</th><th class="r">list-$ *</th><th>buckets</th></tr>']
    for name, c in rows:
        cost = c.get("cost_x1000")
        label = str(name)
        if c.get("eval_sessions"):
            label += f" \u2020({c['eval_sessions']} eval)"
        out.append(
            f"<tr><td>{H.escape(label)}</td>"
            f'<td class="r">{c.get("sessions", 0)}</td>'
            f'<td class="r">{_fmt(c.get("input", 0))}</td>'
            f'<td class="r">{_fmt(c.get("output", 0))}</td>'
            f'<td class="r">{_fmt(c.get("cache_read", 0))}</td>'
            f'<td class="r">{_fmt(c.get("cache_creation", 0))}</td>'
            f'<td class="r">{_fmt(cost / 1000 if cost is not None else None, money=True)}</td>'
            f"<td>{_tok_bar(c, max_total)}</td></tr>")
    out.append(f'</table></div><p class="src">source: {H.escape(src)}</p>')
    return "\n".join(out)


def _mix_table(mix: dict) -> str:
    out = []
    order = ["exploratory_qa", "feature_implementation", "ui_verification_loop",
             "single_file_bug_fix", "boilerplate_scaffolding", "multi_file_refactor",
             "test_authoring", "documentation", "config_infra", "agent_meta_work",
             "other", "unclassified"]
    for unit in ("prompt", "segment", "session"):
        groups = mix.get(unit) or {}
        if not groups:
            continue
        out.append(f"<h3>{unit} grain</h3>")
        out.append('<div class="wrap"><table><tr><th>tool / cohort</th><th class="r">n</th>'
                   + "".join(f"<th class='r'>{t.replace('_', ' ')[:14]}</th>"
                             for t in order if any(t in g for g in groups.values()))
                   + "</tr>")
        cols = [t for t in order if any(t in g for g in groups.values())]
        for key, cnt in sorted(groups.items()):
            n = sum(cnt.values())
            cells = "".join(
                f"<td class='r'>{cnt[t] / n:.0%}</td>" if cnt.get(t) else "<td class='r'>·</td>"
                for t in cols)
            out.append(f"<tr class='mixrow'><td>{H.escape(key)}</td><td class='r'>{n}</td>{cells}</tr>")
        out.append("</table></div>")
    return "\n".join(out)


def render(s: dict) -> str:
    spend = s["spend"]
    cover = s["coverage"]

    # outcomes + cost side by side
    repo_rows = []
    for ref, rp in sorted(s["repos"].items(), key=lambda kv: -kv[1]["commits"]):
        name = rp.get("path") or ref
        cost = s["proj_cost"].get(name)
        surv = rp["surv30_median"]
        rework = (f"{rp['rework_y']}/{rp['rework_m']}"
                  if rp["rework_m"] else None)
        attr = rp.get("attr", {})
        attr_s = f"{attr.get('known', 0)}k/{attr.get('partial', 0)}p/{attr.get('unknown', 0)}u"
        surv_cell = (f"{surv:.0%} <span class='nr'>(n={rp['surv30_n']})</span>"
                     if surv is not None else NR)
        repo_rows.append(
            f"<tr><td>{H.escape(name)}</td>"
            f"<td class='r'>{rp['commits']}</td>"
            f"<td class='r'>{surv_cell}</td>"
            f"<td class='r'>{rework if rework is not None else NR}</td>"
            f"<td class='r'>{attr_s}</td>"
            f"<td class='r'>{_fmt(cost, money=True) if cost is not None else NR}</td></tr>")

    auto_rows = []
    for k in ("human", "unmarked", "automated"):
        cnt = s["auto_mix"].get(k)
        if not cnt:
            continue
        n = sum(cnt.values())
        top3 = ", ".join(f"{t.replace('_', ' ')} {v / n:.0%}" for t, v in
                         sorted(cnt.items(), key=lambda x: -x[1])[:3])
        auto_rows.append(f"<tr><td>{k}</td><td class='r'>{n}</td><td>{top3}</td></tr>")

    cover_rows = []
    for tool, c in cover.items():
        cover_rows.append(
            f"<tr><td>{tool}</td><td class='r'>{c['sessions']}</td>"
            f"<td class='r'>{c['repo_join']} ({c['repo_join'] / c['sessions']:.0%})</td>"
            f"<td class='r'>{c['with_tokens'] if c['with_tokens'] else NR}</td>"
            f"<td class='r'>{c['with_units'] if c['with_units'] else NR}</td>"
            f"<td>{c['range'][0]} → {c['range'][1]}</td></tr>")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Caliper — first look</title><style>{CSS}</style></head><body><main>
<h1>Caliper — first look</h1>
<p class="sub">Everything the logs on this machine can already say: what the agents were used for,
what it would have cost at list prices, and what happened to the code afterward. Generated
read-only from <code>data/extracted/</code> and <code>data/derived/</code> — presentation only,
no new measurement.</p>
<p class="meta">generated {H.escape(s['generated_at'])} · {s['n_sessions']} sessions ·
report {H.escape('first-look-0.1.0')}</p>
<div class="banner"><b>These are list-price equivalents, not charges.</b> Priced from the
versioned snapshot ({H.escape(s['pricing']['as_of'])}) over all four token buckets; on a
subscription this is what the traffic <i>would</i> have cost at API rates, not what was billed.
Rate source: {H.escape(s['pricing']['source'])}.
Sessions mixing models are priced at their dominant model (approximation, labeled).
{spend['unpriced_sessions']} session(s) had tokens but no priceable model;
{spend['no_token_sessions']} recorded no tokens at all (Cursor logs none) — shown as
not recorded, never as zero.</div>

<h2>1 · Spend</h2>
<p class="legend">token buckets: <i style="background:var(--in)"></i>input
<i style="background:var(--out)"></i>output
<i style="background:var(--cr)"></i>cache read
<i style="background:var(--cw)"></i>cache write — cache reads dominate real agent
traffic; a view that hides them misprices everything.</p>
{_spend_table('By model (dominant per session)', spend['by_model'], 'data/extracted/*/sessions.jsonl → tokens, models[]')}
{_spend_table('By tool', spend['by_tool'], 'data/extracted/*/sessions.jsonl → tokens')}
{_spend_table('By project', spend['by_project'], 'sessions.jsonl → project_ref, display-named via local-only mapping (never committed)')}
{_spend_table('By day (chronological)', spend['by_day'], 'sessions.jsonl → started_at date', top=100, chrono=True)}
<p class="note">† marks days containing eval-harness sessions — Caliper's own replay runs
(202 sessions) land almost entirely on two days and dominate their token volume; read
those days as instrument spend, not organic usage.</p>

<h2>2 · Task mix</h2>
<p class="note">Classifier output (rules-0.1.1, ADR-0009). Cohorts are never pooled:
the eval-harness cohort is Caliper's own replay traffic; automated and human sessions
mix very differently. Unclassified is a legal outcome and stays visible.</p>
{_mix_table(s['mix'])}
<h3>Automated vs human (organic sessions)</h3>
<div class="wrap"><table><tr><th>cohort</th><th class="r">n</th><th>top classes</th></tr>
{''.join(auto_rows)}</table></div>
<p class="src">source: data/derived/classes/task_classes.jsonl × sessions.jsonl automated flag —
pooling these would distort the mix (ADR-0009: 86% vs 51% exploratory).</p>

<h2>3 · Outcomes — beside what they cost</h2>
<p class="note">Git-history signals per repo (ADR-0006) next to that project's session
spend: the column nobody else has. Survival = median 30-day line survival of measured
commits; rework = commits reworked within 14 days / measured; attribution =
known/partial/unknown commits (never inferred from code).</p>
<div class="wrap"><table><tr><th>repo</th><th class="r">commits</th>
<th class="r">30d survival</th><th class="r">rework ≤14d</th>
<th class="r">AI attr (k/p/u)</th><th class="r">session list-$ *</th></tr>
{''.join(repo_rows)}</table></div>
<p class="src">source: data/extracted/git_history/production_signals.jsonl ·
spend join via project display name (approximate: project↔repo mapping is by
working directory)</p>

<h2>4 · Coverage &amp; honesty</h2>
<div class="wrap"><table><tr><th>tool</th><th class="r">sessions</th>
<th class="r">joined to a repo</th><th class="r">with tokens</th>
<th class="r">with prompt units</th><th>date range</th></tr>
{''.join(cover_rows)}</table></div>
<div class="cav"><b>Caveats that travel with every number above.</b><ul>
<li><b>Solo data:</b> one developer's machine. Mix percentages validate the instrument,
not anyone else's traffic (ADR-0002, ADR-0009).</li>
<li><b>Classifier agreement is 53% (κ 0.41) at prompt grain</b> vs 81 human labels —
strong on exploratory/browser work, blind to intent distinctions. Mix rows inherit
that uncertainty (ADR-0009).</li>
<li><b>Cursor records no tokens or turns</b> — its spend is not recorded (not zero),
and its mix is session-grain only.</li>
<li><b>Log retention is ~days:</b> sessions before Jul 25 survive only as previously
extracted records; prompt-grain data for them is gone (ADR-0009).</li>
<li><b>Survival/rework</b> exclude generated-file skew per-commit medians; young
commits are "not yet measurable", never zero (ADR-0006).</li>
<li><b>Eval-harness cohort</b> (202 sessions) is Caliper measuring itself; it is
broken out, not mixed into organic rows.</li></ul></div>
<p class="src">Every figure derives from a record on disk; regenerate with
<code>caliper report</code>. Rates come from a dated snapshot generated by
<code>caliper pricing update</code> (LiteLLM community data — not authoritative;
historical records keep the rates that applied when they were priced). This file and the name mapping live in the gitignored
extraction tree because they render local project names.</p>
</main></body></html>"""
