"""Page builders for caliper serve (ADR-0016).

Every fragment here renders from the SAME load_data/summarize bundle the
static report consumes — one data layer, so serve can never disagree with a
report the user already sent someone. Markup follows DESIGN.md: tokens only,
uncertainty pairs on every rate, the six absence words as absence (never
zero, never a dash), an evidence line under every table, the caveat block on
every view carrying measurements, and nothing that animates on load.

Session→commit relationships DO NOT EXIST in this product yet (the trace
layer is stubbed). Where commits appear near a session they are labeled
temporal proximity, in words, by the fragment builder itself — the label
cannot be omitted by a caller.
"""

from __future__ import annotations

import html as H
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from . import charts
from .generate import TOOLS, _cohort, _dominant_models, _price

# The ±24h nearby-commit window is an UNVALIDATED display choice for
# readability, not a measured commit-latency figure (ADR-0016). The honest
# value comes from the trace layer once session→commit latency is measured.
PROXIMITY_HOURS = 24

PROXIMITY_LABEL = "Commits nearby in time — temporal proximity, not attribution"

ABSENT_WORDS = ("not recorded", "not yet measurable", "not priced",
                "unclassified", "unmeasurable", "excluded_generated")

# DESIGN.md tokens, verbatim — light default, dark as a token-for-token
# override. No other color values may appear below this block.
CSS = """
:root { color-scheme: light;
  --bg:#FAF9F6; --surface-1:#FFFFFF; --surface-2:#F2F0EC;
  --edge:rgba(0,0,0,.10); --edge-strong:#C9C5BE;
  --text-1:#26241F; --text-2:#5D594F; --text-3:#8B867D;
  --accent:#1F4A38; --measured:#4F7A4A; --provisional:#A15F28;
  --absent:#8B867D; --danger:#A8443A; --hover:rgba(0,0,0,.04);
  --in:var(--cat-3); --out:var(--cat-2); --cr:var(--cat-1); --cw:var(--cat-4);
  --cat-1:#3D7FD9; --cat-2:#E07A38; --cat-3:#3FA455; --cat-4:#D9A63A;
  --cat-5:#E06C9F; --cat-6:#35AEAE; --cat-7:#D9564A; --cat-8:#8A66D9;
  --cat-9:#A8845A; --cat-10:#7593A6; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark;
  --bg:#0F0F0E; --surface-1:#191917; --surface-2:#232320;
  --edge:rgba(255,255,255,.11); --edge-strong:#4A4843;
  --text-1:#F7F5F2; --text-2:#B6B1A8; --text-3:#8B867D;
  --accent:#8FBFA4; --measured:#8FAE8B; --provisional:#D9A47E;
  --danger:#C97B6F; --hover:rgba(255,255,255,.06);
  --cat-1:#5E9BE6; --cat-2:#EE9459; --cat-3:#57BE6E; --cat-4:#E6BC55;
  --cat-5:#EE8DB7; --cat-6:#4FC6C6; --cat-7:#E67468; --cat-8:#A588E6;
  --cat-9:#C29D6E; --cat-10:#8FAEC2; } }
@media (prefers-reduced-motion: reduce) {
  * { transition-duration:0.01ms !important; animation-duration:0.01ms !important; }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text-1);
  font:13px/1.5 ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums; -webkit-font-smoothing:antialiased; }
main { max-width:1760px; margin:0 auto; padding:32px 22px 70px;
  display:flex; flex-direction:column; gap:20px; }
@media (min-width:1700px){ body { font-size:14px; }
  main { padding:44px 40px 90px; gap:26px; } }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
a:focus-visible, button:focus-visible, input:focus-visible,
select:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
code, .mono, .fig { font-family:inherit; }
p { margin:0; }
.mast { display:flex; align-items:baseline; justify-content:space-between;
  flex-wrap:wrap; gap:10px 20px; }
.mast h1 { margin:0; font-size:clamp(26px,4.5vw,40px); letter-spacing:-.02em;
  text-transform:uppercase; font-weight:700; }
.stamp { font-size:12px; color:var(--text-3); max-width:60ch;
  text-align:right; }
.ctl { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.ctl .lbl { font-size:11px; letter-spacing:.12em; text-transform:uppercase;
  color:var(--text-3); margin-right:3px; }
.ctl .gap { flex:1; min-width:8px; }
.btn, form.flt button { font:inherit; font-size:12px; letter-spacing:.06em;
  text-transform:uppercase; background:transparent; color:var(--text-2);
  border:2px solid var(--edge-strong); border-radius:0; padding:5px 12px;
  cursor:pointer; display:inline-block; }
.btn:hover, form.flt button:hover { border-color:var(--text-1);
  color:var(--text-1); text-decoration:none; }
.btn[aria-pressed="true"] { background:var(--text-1);
  border-color:var(--text-1); color:var(--bg); }
form.flt { display:inline-flex; gap:8px; align-items:center; flex-wrap:wrap;
  font-size:12px; color:var(--text-2); }
form.flt input, form.flt select { font:inherit; font-size:12px;
  color:var(--text-1); background:var(--surface-1);
  border:2px solid var(--edge-strong); border-radius:0; padding:4px 8px; }
.fstate { font-size:12px; color:var(--provisional); }
.stats { display:grid; grid-template-columns:repeat(4,1fr);
  border:2px solid var(--text-1); }
@media (max-width:780px){ .stats { grid-template-columns:repeat(2,1fr); } }
.stat { padding:15px 14px; border-right:2px solid var(--text-1);
  background:var(--surface-1); min-width:0; }
.stat:last-child { border-right:0; }
@media (max-width:780px){ .stat:nth-child(2n){ border-right:0; }
  .stat:nth-child(-n+2){ border-bottom:2px solid var(--text-1); } }
.stat .k { font-size:11px; letter-spacing:.12em; text-transform:uppercase;
  color:var(--text-3); }
.stat .v { font-size:clamp(22px,3vw,32px); font-weight:700;
  letter-spacing:-.02em; margin-top:3px; white-space:nowrap; }
.stat .n { font-size:11px; color:var(--text-2); margin-top:1px; }
.stat.lead { background:var(--text-1); color:var(--bg); }
.stat.lead .k, .stat.lead .n { color:var(--bg); opacity:.72; }
.note-line { font-size:12px; color:var(--text-2); max-width:none; }
.wrap, figure.chart, .panelbox { border:2px solid var(--edge-strong);
  background:var(--surface-1); margin:0; }
.wrap { overflow-x:auto; }
figure.chart figcaption, .phead { display:flex; justify-content:space-between;
  align-items:baseline; gap:12px; padding:9px 14px;
  border-bottom:2px solid var(--edge-strong); }
.ct, .phead .ct { font-size:11px; letter-spacing:.16em;
  text-transform:uppercase; font-weight:700; color:var(--text-2);
  white-space:nowrap; }
.cm { font-size:11px; color:var(--text-3); text-align:right; }
.cbody, .pbody { padding:16px 14px; }
figure.chart svg { width:100%; height:auto; display:block; }
figure.chart g[data-tip]:hover .hit { fill:var(--hover); }
svg .ax { font-family:inherit; font-size:11px; fill:var(--text-3); }
svg .pt { font-family:inherit; font-size:12px; fill:var(--text-1); }
svg .pt .ax { fill:var(--text-2); }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:20px;
  align-items:stretch; }
.cols .col { display:flex; flex-direction:column; gap:20px; min-width:0; }
.cols .col > *:last-child { flex:1 1 auto; }
@media (max-width:880px){ .cols { grid-template-columns:1fr; }
  .cols .col > *:last-child { flex:0 0 auto; } }
.grid2 { display:grid; grid-template-columns:1fr 1fr; gap:0 20px;
  align-items:start; }
.grid2 > div { min-width:0; }
.grid2 > div > h2:first-child { margin-top:8px; }
@media (max-width:1100px){ .grid2 { grid-template-columns:1fr; } }
h2 { font-size:13px; letter-spacing:.1em; text-transform:uppercase;
  font-weight:700; margin:14px 0 4px; }
.meta, .n-of { font-size:12px; color:var(--text-2); }
.faint { font-size:12px; color:var(--text-3); }
.note { font-size:12px; color:var(--text-2); max-width:760px; margin:4px 0 8px; }
.legend { display:flex; flex-wrap:wrap; gap:5px 16px; padding:8px 0 0;
  font-size:12px; color:var(--text-2); margin:0; }
.sw { display:inline-block; width:11px; height:11px; flex:none;
  margin:0 6px 0 0; vertical-align:-1px; }
.rows { display:flex; flex-direction:column; }
.row2 { display:grid; grid-template-columns:1fr auto; gap:4px 14px;
  padding:11px 0; border-top:1px solid var(--edge-strong); }
.row2:first-child { border-top:0; padding-top:2px; }
.row2 .nm { display:flex; align-items:center; gap:8px; min-width:0; }
.row2 .nm i { width:10px; height:10px; flex:none; font-style:normal; }
.row2 .nm b { font-weight:400; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }
.row2 .amt { white-space:nowrap; }
.row2 .amt span { color:var(--text-3); margin-left:8px; }
.row2 .track { grid-column:1 / -1; height:8px; background:var(--surface-2); }
.row2 .fill { height:100%; }
.row2 .sub { grid-column:1 / -1; font-size:11px; color:var(--text-3);
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tokgrid { display:grid; grid-template-columns:1fr 1fr; }
@media (max-width:520px){ .tokgrid { grid-template-columns:1fr; } }
.tok { padding:14px; border-top:1px solid var(--edge-strong);
  border-right:1px solid var(--edge-strong); }
.tok:nth-child(-n+2){ border-top:0; }
.tok:nth-child(2n){ border-right:0; }
.tok .k { font-size:11px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--text-3); display:flex; align-items:center; gap:7px; }
.tok .v { font-size:24px; font-weight:700; letter-spacing:-.02em;
  margin:3px 0 5px; }
.tok .v small { font-size:12px; font-weight:400; color:var(--text-3);
  margin-left:6px; }
.tok .exact { font-size:11px; color:var(--text-3); }
.tok .track { height:6px; background:var(--surface-2); margin-bottom:6px; }
.tok .fill { height:100%; }
.brow { margin:12px 0 0; }
.brow:first-child { margin-top:0; }
.brow .bl { display:flex; justify-content:space-between;
  align-items:baseline; gap:12px; font-size:13px; }
.brow .br { color:var(--text-2); font-size:12px; text-align:right; }
.pbar { display:block; width:100%; height:18px; margin-top:4px; }
.bbar { display:block; width:100%; height:16px; margin-top:4px; }
table { border-collapse:collapse; width:100%; font-size:12px; }
thead th { font-size:10px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--text-3); text-align:right; padding:7px 9px;
  border-bottom:2px solid var(--edge-strong); background:var(--surface-1);
  position:sticky; top:0; cursor:pointer; user-select:none;
  white-space:nowrap; }
thead th:first-child { text-align:left; }
thead th .si { color:var(--accent); margin-left:4px; }
td { padding:6px 9px; text-align:right; border-bottom:1px solid
  var(--edge-strong); white-space:nowrap; color:var(--text-2); }
td:first-child { text-align:left; }
td.n { text-align:right; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:var(--bg); }
.zero { color:var(--edge-strong); }
.scroll { max-height:460px; overflow:auto; }
.kv td:first-child { color:var(--text-2); width:220px; }
.ab { color:var(--absent); font-style:italic;
  font-variant-caps:all-small-caps; font-size:12px; letter-spacing:.02em;
  background:color-mix(in srgb, var(--surface-2) 40%, transparent);
  padding:0 4px; }
.why { color:var(--text-3); font-size:11px; font-style:normal; }
.src { font-size:11px; color:var(--text-3); margin:4px 0 0; }
.panelbox > .src { padding:8px 14px 10px; margin:0; }
.src b { letter-spacing:.08em; text-transform:uppercase; font-weight:700; }
.cav { border:2px solid var(--edge-strong); border-left:4px solid
  var(--provisional); background:var(--surface-1); padding:12px 14px;
  font-size:12px; color:var(--text-1); }
.cav .hd { font-size:11px; letter-spacing:.16em; text-transform:uppercase;
  font-weight:700; color:var(--text-2); }
.cav p { margin:6px 0 0; max-width:none; }
.prox { border:2px solid var(--edge-strong); background:var(--surface-1);
  padding:12px 14px; }
.prox .hd { font-weight:700; font-size:12px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--text-2); }
.prox .wrap { border:none; background:none; }
.band { font-size:12px; color:var(--text-2); border-top:1px solid
  var(--edge-strong); margin-top:12px; padding-top:8px; }
.tip { position:fixed; z-index:50; pointer-events:none; max-width:300px;
  background:var(--surface-1); color:var(--text-1);
  border:2px solid var(--text-1); padding:8px 10px; font-size:12px;
  opacity:0; transition:opacity .08s linear; }
.tip.on { opacity:1; }
.tip .th { display:block; font-weight:700; letter-spacing:.05em;
  text-transform:uppercase; margin-bottom:5px; }
.tip .tr, .tip .tt { display:flex; justify-content:space-between;
  align-items:center; gap:14px; }
.tip .tr b, .tip .tt b { font-weight:400; }
.tip .tt { border-top:1px solid var(--edge-strong); margin-top:5px;
  padding-top:4px; font-weight:700; }
.tip .tt b { font-weight:700; }
footer { font-size:11px; color:var(--text-3); }
.empty { font-size:13px; margin:10px 0; }
.big { font-size:32px; font-weight:700; letter-spacing:-.02em; }
"""

# Column sort on header click. Runs only on user action — nothing animates
# or reorders on load (DESIGN.md prohibited pattern 15).
JS = """
document.addEventListener('click', function (e) {
  var th = e.target.closest('th[data-col]');
  if (!th) return;
  var table = th.closest('table');
  var idx = +th.dataset.col;
  var dir = th.dataset.dir === 'a' ? 'd' : 'a';
  table.querySelectorAll('th').forEach(function (h) {
    h.dataset.dir = '';
    var m = h.querySelector('.si'); if (m) m.remove();
  });
  th.dataset.dir = dir;
  var mark = document.createElement('span');
  mark.className = 'si'; mark.textContent = dir === 'a' ? '\\u25b4' : '\\u25be';
  th.appendChild(mark);
  var tb = table.tBodies[0];
  var rows = Array.prototype.slice.call(tb.rows);
  var num = th.dataset.num === '1';
  rows.sort(function (r1, r2) {
    var a = r1.cells[idx].dataset.s, b = r2.cells[idx].dataset.s;
    if (a === undefined) a = r1.cells[idx].textContent.trim();
    if (b === undefined) b = r2.cells[idx].textContent.trim();
    if (num) {
      a = parseFloat(a); b = parseFloat(b);
      if (isNaN(a)) a = -Infinity;
      if (isNaN(b)) b = -Infinity;
    }
    return (a < b ? -1 : a > b ? 1 : 0) * (dir === 'a' ? 1 : -1);
  });
  rows.forEach(function (r) { tb.appendChild(r); });
});

// Instant pointer tooltip for [data-tip] marks. Server-authored payload,
// shown/hidden with no delay and no animation; native SVG <title> was
// measured unusable (ADR-0017 postscript 2).
var tip = document.createElement('div');
tip.className = 'tip';
document.body.appendChild(tip);
document.addEventListener('mousemove', function (e) {
  var t = e.target && e.target.closest ? e.target.closest('[data-tip]') : null;
  if (!t) { tip.classList.remove('on'); return; }
  var payload = t.getAttribute('data-tip');
  if (tip.dataset.for !== payload) {
    tip.innerHTML = payload;
    tip.dataset.for = payload;
  }
  tip.classList.add('on');
  var r = tip.getBoundingClientRect();
  var x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
  tip.style.left = Math.max(8, x) + 'px';
  tip.style.top = Math.max(8, y) + 'px';
});
addEventListener('scroll', function () { tip.classList.remove('on'); },
  { passive: true });
addEventListener('blur', function () { tip.classList.remove('on'); });
"""


# ---------------------------------------------------------------------------
# primitives (DESIGN.md: Absent, FigurePair, EvidenceLine, CaveatBlock, Table)

def absent(word: str, reason: str | None = None) -> str:
    """The Absent primitive — the only way an absence renders (DESIGN.md)."""
    if word not in ABSENT_WORDS:
        raise ValueError(f"not an absence word: {word}")
    why = f' <span class="why">— {H.escape(reason)}</span>' if reason else ""
    return f'<span class="ab">{H.escape(word)}</span>{why}'


def pair(figure: str, n_text: str) -> str:
    """The uncertainty pair: value + its n, same visual unit, never split."""
    return (f'<span class="fig">{figure}</span> '
            f'<span class="n-of">({H.escape(n_text)})</span>')


def money(x: float | None, word: str = "not priced") -> str:
    if x is None:
        return absent(word)
    return f'<span class="fig">${x:,.2f}</span>'


def count(x) -> str:
    return f'<span class="fig">{x:,}</span>'


def evidence(src: str) -> str:
    return f'<p class="src"><b>source:</b> {H.escape(src)}</p>'


def caveat_block(sentences: list[str]) -> str:
    body = "".join(f"<p>{s}</p>" for s in sentences)
    return (f'<div class="cav"><div class="hd">Caveats that travel with '
            f"these numbers</div>{body}</div>")


def table(cols: list[tuple[str, bool]], rows: list[list[tuple[str, object]]],
          sort_note: str | None = None, cls: str = "") -> str:
    """cols: (label, numeric). rows: cells as (html, sortkey|None).
    Sortable by any column on click; initial order is the caller's and is
    stated when not obvious."""
    head = "".join(
        f'<th data-col="{i}" data-num="{1 if num else 0}"'
        f'{" class=" + chr(34) + "r" + chr(34) if num else ""}>'
        f"{H.escape(lab)}</th>"
        for i, (lab, num) in enumerate(cols))
    body = []
    for r in rows:
        tds = []
        for (cell, key), (_lab, num) in zip(r, cols):
            k = f' data-s="{H.escape(str(key), quote=True)}"' if key is not None else ""
            cls = ' class="n"' if num else ""
            tds.append(f"<td{cls}{k}>{cell}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    note = f'<p class="faint">{H.escape(sort_note)}</p>' if sort_note else ""
    wrap_cls = f"wrap {cls}".strip()
    return (f'<div class="{wrap_cls}"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>{note}')


# ---------------------------------------------------------------------------
# shared bits

def _qs(filters: dict) -> str:
    """Query string for an href attribute (&-escaped for HTML)."""
    return "?" + H.escape(urlencode(filters)) if filters else ""


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _dur(ms) -> str:
    if ms is None:
        return absent("not recorded")
    s = ms // 1000
    if s >= 3600:
        return f'<span class="fig">{s // 3600}h {s % 3600 // 60}m</span>'
    if s >= 60:
        return f'<span class="fig">{s // 60}m {s % 60}s</span>'
    return f'<span class="fig">{s}s</span>'


def _repo_names(raw: dict) -> dict[str, str]:
    """repo_ref -> display name (basename of the measured repo path)."""
    out = {}
    for r in raw["signals"]:
        out[r["change_ref"]["repo_ref"]] = \
            r["provenance"]["repo_path"].rsplit("/", 1)[-1]
    return out


def _session_class(raw: dict, sid: str) -> dict | None:
    for r in raw["classes"]:
        if r["unit"] == "session" and r["unit_ref"]["session_id"] == sid:
            return r
    return None


def _session_cost(raw: dict, rec: dict) -> float | None:
    tok = rec.get("tokens")
    if not tok:
        return None
    return _price(tok, _dominant_models(rec), raw["pricing"])


def _filter_state(ui: dict, resolved: dict) -> str:
    if not ui:
        return ""
    parts = []
    if ui.get("range") and ui["range"] != "all" and not ui.get("from"):
        parts.append(f"last {ui['range']}"
                     + (f" (since {resolved['from']})"
                        if resolved.get("from") else ""))
    if ui.get("from"):
        parts.append(f"from {ui['from']}")
    if ui.get("to"):
        parts.append(f"to {ui['to']}")
    if ui.get("tool"):
        parts.append(f"tool {ui['tool']}")
    if not parts:
        return ""
    return ('<p class="fstate">Filtered: ' + H.escape(" · ".join(parts)) +
            ". Every figure on this page is computed over the filtered "
            "records only.</p>")


def _range_row(ui: dict) -> str:
    """The persistent range selector: URL state like every other filter,
    each link preserving the rest of the state. Picking a range clears an
    explicit date pair (the range IS the date choice)."""
    base = {k: v for k, v in ui.items() if k not in ("from", "to", "range")}
    active = ui.get("range") or \
        ("custom" if ("from" in ui or "to" in ui) else "all")
    links = []
    for key in ("1d", "7d", "30d", "90d", "all"):
        q = dict(base)
        if key != "all":
            q["range"] = key
        pressed = "true" if active == key else "false"
        links.append(f'<a class="btn" aria-pressed="{pressed}" '
                     f'href="?{H.escape(urlencode(q))}">{key}</a>')
    return '<span class="lbl">range</span>' + "".join(links)


def _survival30(rec: dict, now: datetime) -> tuple[str, object]:
    """One commit's 30d survival cell: the pair, or its absence word with
    the reason — never 0%, never blank (DESIGN.md state presentation)."""
    entry = next((s for s in rec.get("survival") or []
                  if s["horizon_days"] == 30), None)
    if entry is None:
        return absent("not recorded"), -1
    st = entry["status"]
    if st == "measured":
        frac = entry["surviving_fraction"]
        return (pair(f"{frac:.0%}", f"of {entry['lines_original']:,} lines"),
                frac)
    if st == "not_yet_measurable":
        age = (now - _parse_iso(rec["change_ref"]["authored_at"])).days
        return (absent("not yet measurable",
                       f"30d horizon, commit is {age}d old"), -1)
    if st == "excluded_generated":
        pv = (rec.get("generated") or {}).get("patterns_version", "")
        return absent("excluded_generated", f"generated only, {pv}"), -1
    return absent("unmeasurable", "no work lines to trace"), -1


def _rework_cell(rec: dict) -> tuple[str, object]:
    rw = rec.get("rework")
    if not rw:
        return absent("not recorded"), -1
    st = rw["status"]
    if st == "measured":
        return (("yes", 1) if rw["occurred"] else ("no", 0))
    if st in ("not_yet_measurable", "unmeasurable", "excluded_generated"):
        return absent(st.replace("_", " ") if st != "excluded_generated"
                      else "excluded_generated"), -1
    return absent("not recorded"), -1


def _commit_rows(sigs: list[dict], now: datetime) -> list[list]:
    rows = []
    for r in sorted(sigs, key=lambda x: x["change_ref"]["authored_at"],
                    reverse=True):
        cr = r["change_ref"]
        sha = cr["commit_sha"][:10]
        authored = cr["authored_at"][:16].replace("T", " ")
        surv, sk = _survival30(r, now)
        rework, rk = _rework_cell(r)
        attr = r["ai_attribution"]["status"]
        gen = (r.get("generated") or {}).get("lines_added_excluded", 0)
        rows.append([
            (f'<span class="mono">{H.escape(sha)}</span>', sha),
            (f'<span class="fig">{H.escape(authored)}</span>', authored),
            (f'<span class="fig">+{cr["lines_added"]:,} '
             f'−{cr["lines_deleted"]:,}</span>', cr["lines_added"]),
            (surv, sk),
            (rework, rk),
            (H.escape(attr), attr),
            (count(gen) if gen else '<span class="fig">0</span>', gen),
        ])
    return rows


_COMMIT_COLS = [("commit", False), ("authored", False), ("work lines", True),
                ("30d survival", True), ("rework ≤14d", True),
                ("AI attribution", False), ("generated lines excluded", True)]


def _nearby_commits(raw: dict, rec: dict, now: datetime) -> str:
    """The ONLY place commits appear beside a session — and the proximity
    label is built here, unconditionally, so no caller can imply the
    session→commit attribution the product does not have."""
    names = raw["names"]
    repo_by_name = {v: k for k, v in _repo_names(raw).items()}
    proj = names.get(rec.get("project_ref"))
    repo_ref = repo_by_name.get(proj) if proj else None
    if repo_ref is None:
        return (f'<div class="prox"><div class="hd">{PROXIMITY_LABEL}</div>'
                '<p class="note">This session\'s project could not be joined '
                "to a measured repo (the display-name join is approximate "
                "and found no match), so no nearby commits are shown.</p></div>")
    start = _parse_iso(rec["started_at"])
    end = _parse_iso(rec.get("ended_at") or rec["started_at"])
    sigs = []
    for r in raw["signals"]:
        if r["change_ref"]["repo_ref"] != repo_ref:
            continue
        t = _parse_iso(r["change_ref"]["authored_at"])
        gap_h = min(abs((t - start).total_seconds()),
                    abs((t - end).total_seconds())) / 3600
        if start <= t <= end:
            gap_h = 0
        if gap_h <= PROXIMITY_HOURS:
            sigs.append(r)
    body = (table(_COMMIT_COLS, _commit_rows(sigs, now))
            + evidence("~/.caliper/extracted/git_history/production_signals.jsonl"
                       " × session started_at/ended_at")
            if sigs else
            '<p class="note">No commits in this repo within the window.</p>')
    return (f'<div class="prox"><div class="hd">{PROXIMITY_LABEL}</div>'
            f'<p class="note">Commits in {H.escape(proj or "")} within '
            f"{PROXIMITY_HOURS} hours of this session. The trace layer that "
            "could join a session to its commits does not exist yet; "
            "nearness in time is the only relationship shown and it is not "
            f"evidence this session produced them. The {PROXIMITY_HOURS}-hour "
            "window is an unvalidated display choice (ADR-0016), not a "
            f"measured figure.</p>{body}</div>")


def page(title: str, body: str, active: str, loaded_at: str,
         filters: dict, resolved: dict | None = None) -> str:
    q = _qs(filters)
    nav = "".join(
        f'<a class="btn" aria-pressed='
        f'"{"true" if active == key else "false"}" href="{href}{q}">'
        f"{label}</a>"
        for key, href, label in (
            ("overview", "/", "Overview"),
            ("coverage", "/coverage", "Coverage &amp; honesty")))
    tool_opts = '<option value="">all tools</option>' + "".join(
        f'<option value="{t}"{" selected" if filters.get("tool") == t else ""}>{t}</option>'
        for t in TOOLS)
    clear = ('<a class="btn" aria-pressed="false" href="?">clear</a>'
             if filters else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{H.escape(title)}</title><style>{CSS}</style></head><body><main>
<header class="mast"><h1>Caliper</h1>
<span class="stamp">data loaded {H.escape(loaded_at)} · re-reads when the
records change · 127.0.0.1 only · reads ~/.caliper read-only, writes
nothing</span></header>
<div class="ctl">{nav}<span class="gap"></span>
<form class="flt" method="get" action="">
<label>from <input type="date" name="from" value="{H.escape(filters.get("from", ""))}"></label>
<label>to <input type="date" name="to" value="{H.escape(filters.get("to", ""))}"></label>
<label>tool <select name="tool">{tool_opts}</select></label>
<button type="submit">Apply</button> {clear}</form>
{_range_row(filters)}</div>
{_filter_state(filters, resolved if resolved is not None else filters)}
{body}
<footer>filters are URL state — every view is linkable and reload-safe ·
serve renders the same figures as caliper report from the same data layer
(mtime-keyed cache, ADR-0016)</footer>
</main><script>{JS}</script></body></html>"""


def _empty(sentence: str, action: str) -> str:
    return (f'<p class="empty">{H.escape(sentence)} '
            f'<span class="mono">{H.escape(action)}</span></p>')


# ---------------------------------------------------------------------------
# views

_LIST_PRICE = ("Every dollar figure is a list-price equivalent from the "
               "versioned sheet, not a charge — on a subscription this is "
               "what the traffic would have cost at API rates.")
_SOLO = ("Solo data: one developer's machine. These figures validate the "
         "instrument, not anyone else's traffic (ADR-0002, ADR-0009).")


def _overview_caveats(s: dict) -> list[str]:
    h = s["headline"]
    return [
        _LIST_PRICE + f" Sheet: {s['pricing']['as_of']}.",
        _SOLO,
        "Classifier agreement is 53.1% (n=81, κ=0.41) at prompt grain — "
        "mix rows inherit that uncertainty (ADR-0009).",
        f"Cursor records no tokens, so its spend is not recorded, never "
        f"zero — {h['cursor_share_all']:.0%} of all sessions "
        f"({h['cursor_share_organic']:.0%} of organic ones), a structural "
        "hole, not a footnote (ADR-0004).",
        "Generated paths (pattern list gen-0.1.0 plus each repo's "
        ".gitattributes) are excluded from line counting; a commit touching "
        "only generated files reads excluded_generated, never 0% "
        "(ADR-0015).",
    ]


def _spend_section(title: str, data: dict, src: str, chrono: bool = False) -> str:
    if not data:
        return ""
    keys = sorted(data) if chrono else sorted(
        data, key=lambda k: -sum(data[k].get(b, 0) for b in
                                 ("input", "output", "cache_read", "cache_creation")))
    trunc_note = ""
    if chrono and len(keys) > 21:
        # DESIGN.md overflow rule: truncate to recent rows with a STATED
        # count of what is not shown — never an unlabeled cutoff
        earlier = keys[:-21]
        n_sess = sum(data[k].get("sessions", 0)
                     + data[k].get("sessions_no_tokens", 0) for k in earlier)
        cost = sum(data[k].get("cost_x1000", 0) for k in earlier) / 1000
        trunc_note = (f'<p class="faint">+ {len(earlier)} earlier days · '
                      f"{n_sess} sessions · ${cost:,.2f} list-equivalent — "
                      "narrow the range to see them</p>")
        keys = keys[-21:]
    if chrono:
        keys = list(reversed(keys))  # newest first (stated in the header)
    rows = []
    for k in keys:
        c = data[k]
        cost = c.get("cost_x1000")
        label = str(k)
        if c.get("eval_sessions"):
            label += f" ({c['eval_sessions']} eval)"
        no_tok = c.get("sessions_no_tokens", 0)
        n_sessions = c.get("sessions", 0) + no_tok
        sess_cell = count(n_sessions)
        if no_tok:
            sess_cell += (f' <span class="n-of">({no_tok} log no '
                          "tokens)</span>")
        if c.get("sessions", 0) == 0 and no_tok:
            # every session here lacks tokens (Cursor): the buckets are a
            # structural absence, never four zeros (ADR-0004, DESIGN.md)
            bucket_cells = [(absent("not recorded"), -1)] * 4
            cost_cell = (absent("not recorded", "no tokens logged"), -1)
        else:
            bucket_cells = [
                ((count(v) if v else '<span class="zero">0</span>'), v)
                for v in (c.get(b, 0) for b in
                          ("input", "output", "cache_read",
                           "cache_creation"))]
            cost_cell = (money(cost / 1000 if cost is not None else None),
                         cost / 1000 if cost is not None else -1)
        rows.append([(H.escape(label), label),
                     (sess_cell, n_sessions), *bucket_cells, cost_cell])
    cols = [(title, False), ("sessions", True), ("input", True),
            ("output", True), ("cache read", True), ("cache write", True),
            ("list-$", True)]
    note = "newest first" if chrono else None
    return (table(cols, rows, sort_note=note,
                  cls="scroll" if chrono else "")
            + trunc_note + evidence(src))


def _day_group_costs(raw: dict, split: str):
    """day -> {group: $} for the spend-over-time chart, priced sessions
    only — an unpriced session cannot stack in dollars, so it is excluded
    HERE and the exclusion is stated in the chart's n (the tables beneath
    keep every session)."""
    from collections import Counter
    per_day: dict[str, dict[str, float]] = {}
    totals: Counter = Counter()
    n_priced = n_unpriced = n_no_tokens = 0
    for rec in raw["sessions"].values():
        if rec.get("fork_of"):
            continue
        if not rec.get("tokens"):
            n_no_tokens += 1
            continue
        cost = _price(rec["tokens"], _dominant_models(rec), raw["pricing"])
        if cost is None:
            n_unpriced += 1
            continue
        n_priced += 1
        day = rec["started_at"][:10]
        grp = rec["source_tool"] if split == "tool" else \
            next(iter(_dominant_models(rec)), "unknown")
        per_day.setdefault(day, {})
        per_day[day][grp] = per_day[day].get(grp, 0.0) + cost
        totals[grp] += cost
    groups = [g for g, _ in totals.most_common()]
    return per_day, groups, n_priced, n_unpriced, n_no_tokens


def _spend_chart(raw: dict, filters: dict) -> str:
    split = filters.get("split") if filters.get("split") in ("tool", "model") \
        else "tool"
    per_day, groups, n_priced, n_unpriced, n_no_tok = \
        _day_group_costs(raw, split)
    if not per_day:
        return ""
    tokens = {g: f"--cat-{i % 10 + 1}" for i, g in enumerate(groups)}
    excluded = []
    if n_unpriced:
        excluded.append(f"{n_unpriced} unpriced")
    if n_no_tok:
        excluded.append(f"{n_no_tok} token-less")
    meta = (f"n = {len(per_day)} active days · {n_priced} priced sessions"
            + (f" · {' + '.join(excluded)} excluded — the tables keep them"
               if excluded else "")
            + " · quiet days are gaps, not zeros")
    other = "model" if split == "tool" else "tool"
    toggle_qs = _qs({**{k: v for k, v in filters.items() if k != "split"},
                     "split": other})
    toggle = (f'<p class="meta">split by {split} · '
              f'<a href="/{toggle_qs or "?"}">split by {other}</a> · '
              "hover a day for its breakdown</p>")
    return toggle + charts.spend_columns(
        per_day, groups, tokens, f"Spend per day · by {split}", meta)


def _mix_bars(unit: str, groups: dict, order: list[str]) -> str:
    """One stacked proportion bar per cohort — cohorts stay unpooled,
    unclassified always a visible segment (absent gray). Reference row
    pattern: cohort + n on the label line, the bar full-width beneath."""
    rows = []
    for key, cnt in sorted(groups.items()):
        n = sum(cnt.values())
        segments = [(t, cnt.get(t, 0)) for t in order]
        rows.append(
            f'<div class="brow"><div class="bl"><span>{H.escape(key)}</span>'
            f'<span class="br">n={n}</span></div>'
            f"{charts.proportion_bar(segments)}</div>")
    legend = charts.swatch_legend(
        [(t.replace("_", " "), charts.cat_token(t)) for t in order])
    return charts.figure(
        f"Task mix · {unit} grain",
        "share of classified units per cohort · hover a segment",
        "".join(rows) + legend)


def _outcome_scatter(raw: dict, s: dict, filters: dict) -> str:
    pts, banded = [], []
    for ref, rp in s["repos"].items():
        name = rp.get("path") or ref
        cost = s["proj_cost"].get(name)
        surv = rp["surv30_median"]
        if surv is not None and cost is not None:
            pts.append({"name": name, "ref": quote(ref), "cost": cost,
                        "surv": surv, "commits": rp["commits"]})
        else:
            reasons = []
            if surv is None:
                reasons.append(absent("not yet measurable",
                                      "no measured 30d survival"))
            if cost is None:
                reasons.append(absent("not recorded", "no priced sessions "
                                      "joined to this repo"))
            banded.append(
                f'<a href="/repo/{quote(ref)}{_qs(filters)}">'
                f"{H.escape(name)}</a> ({' · '.join(reasons)})")
    if not pts and not banded:
        return ""
    meta = (f"n = {len(pts)} repos plotted"
            + (f" · {len(banded)} not plottable, listed below" if banded
               else "")
            + " · x session list-$ (√ scale) · point size = commits · "
            "click a point for the repo")
    band = (f'<p class="band">Not plottable — never omitted, never at the '
            f'origin: {", ".join(banded)}</p>' if banded else "")
    svg = charts.scatter(pts, _qs(filters)) if pts else ""
    return charts.figure("Cost × 30d survival per repo", meta, svg + band)


def _bucket_chart(by_model: dict) -> str:
    keys = sorted(by_model, key=lambda k: -sum(
        by_model[k].get(b, 0) for b, _ in charts.BUCKET_TOKENS))
    max_total = max((sum(c.get(b, 0) for b, _ in charts.BUCKET_TOKENS)
                     for c in by_model.values()), default=0)
    if not max_total:
        return ""
    rows = []
    for k in keys:
        c = by_model[k]
        total = sum(c.get(b, 0) for b, _ in charts.BUCKET_TOKENS)
        if not total:
            continue
        cost = c.get("cost_x1000")
        fig = (f'<span class="fig">{total:,}</span> '
               f'<span class="n-of">tokens</span> · '
               + money(cost / 1000 if cost is not None else None)
               + f' <span class="n-of">(n={c.get("sessions", 0)} '
               "sessions)</span>")
        rows.append(
            f'<div class="brow"><div class="bl"><span class="mono">'
            f'{H.escape(str(k))}</span><span class="br">{fig}</span></div>'
            f"{charts.bucket_bar(c, max_total)}</div>")
    legend = charts.swatch_legend(
        [(b.replace("_", " "), tok) for b, tok in charts.BUCKET_TOKENS])
    return charts.figure(
        "Token buckets per model",
        "bar length = share of the largest model's total · cache reads "
        "dominate real traffic · hover a segment",
        "".join(rows) + legend)


def _compact(n: int) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f}B" if n < 1e10 else f"{n / 1e9:.0f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M" if n < 1e7 else f"{n / 1e6:.0f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K" if n < 1e4 else f"{n / 1e3:.0f}K"
    return f"{n:,}"


def tiles(items: list[tuple[str, str, str, bool]]) -> str:
    """The stats strip (ADR-0018): every tile carries its basis line — a
    tile without one does not render — and at most the first is the lead."""
    cells = []
    for k, v, n, lead in items:
        if not n:
            raise ValueError(f"a stat tile needs its basis line: {k}")
        cells.append(f'<div class="stat{" lead" if lead else ""}">'
                     f'<div class="k">{H.escape(k)}</div>'
                     f'<div class="v">{v}</div>'
                     f'<div class="n">{H.escape(n)}</div></div>')
    return '<div class="stats">' + "".join(cells) + "</div>"


def panel(title: str, note: str, body: str, pad: bool = True) -> str:
    return (f'<section class="panelbox"><div class="phead">'
            f'<span class="ct">{H.escape(title)}</span>'
            f'<span class="cm">{H.escape(note)}</span></div>'
            + (f'<div class="pbody">{body}</div>' if pad else body)
            + "</section>")


def rank_rows(rows: list[dict]) -> str:
    """Reference rank rows: swatch+name left, amount+share right, a
    full-width track beneath, an optional faint sub-line. An absent value
    renders its absence words and NO track — an absence never becomes a
    bar of any length."""
    out = []
    for r in rows:
        sw = (f'<i style="background:var({r["token"]})"></i>'
              if r.get("token") else "")
        share = (f'<span>{r["share"]:.0%}</span>'
                 if r.get("share") is not None else "")
        track = ""
        if r.get("fill") is not None:
            track = (f'<div class="track"><div class="fill" '
                     f'style="width:{max(r["fill"] * 100, 1):.1f}%;'
                     f'background:var({r.get("token") or "--cat-1"})">'
                     "</div></div>")
        sub = (f'<div class="sub">{r["sub"]}</div>' if r.get("sub") else "")
        out.append(f'<div class="row2"><div class="nm">{sw}'
                   f'<b>{r["name"]}</b></div>'
                   f'<div class="amt">{r["amt"]}{share}</div>{track}{sub}'
                   "</div>")
    return '<div class="rows">' + "".join(out) + "</div>"


def tok_tiles(sums: dict[str, int]) -> str:
    """Tokens-by-type tiles: compact figure + share + track + exact count."""
    grand = sum(sums.values()) or 1
    mx = max(sums.values()) if any(sums.values()) else 1
    cells = []
    for bucket, tok in charts.BUCKET_TOKENS:
        v = sums.get(bucket, 0)
        cells.append(
            f'<div class="tok"><div class="k">'
            f'<i class="sw" style="background:var({tok})"></i>'
            f'{H.escape(bucket.replace("_", " "))}</div>'
            f'<div class="v">{_compact(v)}<small>{v / grand:.1%}</small></div>'
            f'<div class="track"><div class="fill" style="width:'
            f'{(v / mx) * 100 if v else 0:.1f}%;background:var({tok})">'
            f"</div></div>"
            f'<div class="exact">{v:,} tokens</div></div>')
    return '<div class="tokgrid">' + "".join(cells) + "</div>"


def overview(raw: dict, s: dict, filters: dict, loaded_at: str) -> str:
    if not s["n_sessions"]:
        if filters:
            body = _empty("No sessions match this filter.",
                          "") + '<p class="empty"><a href="?">Clear the filter</a>.</p>'
        else:
            body = _empty("No sessions extracted yet. Run",
                          "caliper extract") + \
                   '<p class="note">Or start from <span class="mono">caliper' \
                   ' setup</span> for the guided first run.</p>'
        return page("Caliper — overview", body, "overview", loaded_at,
                filters, s["filters"])

    h = s["headline"]
    netted = (f" ({h['fork_children_netted']} fork "
              f"{'child' if h['fork_children_netted'] == 1 else 'children'}"
              " netted from spend)" if h.get("fork_children_netted") else "")
    ranges = [c["range"] for c in s["coverage"].values()]
    span = (f"{min(r[0] for r in ranges)} → {max(r[1] for r in ranges)}"
            if ranges else "")

    spend = s["spend"]
    day_costs = {d: c.get("cost_x1000", 0) / 1000
                 for d, c in spend["by_day"].items() if c.get("cost_x1000")}
    active_days = len(day_costs)
    peak_day = max(day_costs, key=day_costs.get) if day_costs else None
    tok_sums = {b: sum(c.get(b, 0) for c in spend["by_tool"].values())
                for b, _ in charts.BUCKET_TOKENS}
    grand_tokens = sum(tok_sums.values())
    head = (tiles([
        ("Total spend", f'${h["total_cost"]:,.2f}',
         f"{span} · at API list rates", True),
        ("Per active day",
         f'${h["total_cost"] / active_days if active_days else 0:,.2f}',
         f"{active_days} days with priced usage", False),
        ("Tokens", _compact(grand_tokens),
         f"{grand_tokens:,} total, all four buckets", False),
        ("Heaviest day",
         f"${day_costs[peak_day]:,.2f}" if peak_day else "$0.00",
         peak_day or "no priced days", False),
    ])
        + '<p class="note-line">The total price of everything you ran, at '
        "pay-as-you-go API rates — if a subscription covered it, that "
        "is what you saved. "
        f'{h["priced_sessions"]} priced of {s["n_sessions"]} sessions'
        f"{H.escape(netted)} · "
        f'{h["unpriced_sessions"]} with tokens but no publishable rate, '
        f'{h["no_token_sessions"]} with no tokens logged — the total is '
        "a floor, not a sum.</p>")
    # the trend runs full width; the .cols pack independently (ADR-0018)
    model_rows = []
    mcosts = {k: c.get("cost_x1000") for k, c in spend["by_model"].items()}
    grand_cost = sum(v for v in mcosts.values() if v) or 1
    max_cost = max((v for v in mcosts.values() if v), default=1)
    for i, (k, c) in enumerate(sorted(
            spend["by_model"].items(),
            key=lambda kv: -(kv[1].get("cost_x1000") or 0))):
        tokn = f"--cat-{i % 10 + 1}"
        x = c.get("cost_x1000")
        if x is None:
            model_rows.append({
                "token": tokn, "name": H.escape(str(k)),
                "amt": absent("not priced", "no publishable rate"),
                "sub": f'{c.get("sessions", 0)} sessions'})
        else:
            model_rows.append({
                "token": tokn, "name": H.escape(str(k)),
                "amt": f"${x / 1000:,.2f}", "share": x / grand_cost,
                "fill": x / max_cost,
                "sub": f'n={c.get("sessions", 0)} sessions'})

    tool_rows = []
    tcosts = {k: c.get("cost_x1000") or 0 for k, c in spend["by_tool"].items()}
    tgrand = sum(tcosts.values()) or 1
    tmax = max(tcosts.values()) if any(tcosts.values()) else 1
    for i, (k, c) in enumerate(sorted(spend["by_tool"].items(),
                                      key=lambda kv: -tcosts[kv[0]])):
        no_tok = c.get("sessions_no_tokens", 0)
        n_sess = c.get("sessions", 0) + no_tok
        if c.get("sessions", 0) == 0 and no_tok:
            tool_rows.append({
                "name": H.escape(str(k)),
                "amt": absent("not recorded", "source logs no tokens"),
                "sub": f"{n_sess} sessions, none with tokens (ADR-0004)"})
        else:
            x = tcosts[k]
            tool_rows.append({
                "token": f"--cat-{i % 10 + 1}", "name": H.escape(str(k)),
                "amt": f"${x / 1000:,.2f}", "share": x / tgrand,
                "fill": x / tmax,
                "sub": f"n={n_sess} sessions"
                       + (f" ({no_tok} log no tokens)" if no_tok else "")})

    proj_rows = []
    pcosts = {k: c.get("cost_x1000") or 0
              for k, c in spend["by_project"].items()}
    pgrand = sum(pcosts.values()) or 1
    pmax = max(pcosts.values()) if any(pcosts.values()) else 1
    for k, c in sorted(spend["by_project"].items(),
                       key=lambda kv: -pcosts[kv[0]]):
        x = pcosts[k]
        proj_rows.append({
            "token": "--cat-1", "name": H.escape(str(k)),
            "amt": f"${x / 1000:,.2f}", "share": x / pgrand,
            "fill": x / pmax, "sub": f'n={c.get("sessions", 0)} sessions'})

    spend_html = (
        _spend_chart(raw, filters)
        + '<div class="cols"><div class="col">'
        + panel("Total by model", f"{len(model_rows)} models · list-$",
                rank_rows(model_rows)
                + evidence("extracted/*/sessions.jsonl → tokens, models[] · "
                           "dominant-model pricing (approximation)"))
        + panel("Tokens by type",
                f"{_compact(grand_tokens)} total · " + (
                    "filtered range" if s["filters"] else "all time"),
                tok_tiles(tok_sums)
                + evidence("sessions.jsonl → tokens, four buckets never "
                           "pooled (ADR-0005)"), pad=False)
        + '</div><div class="col">'
        + _bucket_chart(spend["by_model"])
        + panel("Spend by tool", f"{len(tool_rows)} tools",
                rank_rows(tool_rows)
                + evidence("extracted/*/sessions.jsonl → tokens"))
        + panel("Spend by project", f"{len(proj_rows)} projects",
                rank_rows(proj_rows)
                + evidence("sessions.jsonl → project_ref, display-named via "
                           "local-only mapping (never committed)"))
        + "</div></div>"
        + _spend_section("day", spend["by_day"],
                         "sessions.jsonl → started_at date", chrono=True))

    # task mix by cohort — never pooled, unclassified always visible
    mix_html = "<h2>Task mix</h2>"
    if not raw["classes"]:
        mix_html += _empty("No classifications yet. Run", "caliper classify")
    else:
        order = ["exploratory_qa", "feature_implementation",
                 "ui_verification_loop", "single_file_bug_fix",
                 "boilerplate_scaffolding", "multi_file_refactor",
                 "test_authoring", "documentation", "config_infra",
                 "agent_meta_work", "other", "unclassified"]
        for unit in ("prompt", "segment", "session"):
            groups = s["mix"].get(unit) or {}
            if not groups:
                continue
            cols_present = [t for t in order
                            if any(t in g for g in groups.values())]
            if "unclassified" not in cols_present:
                cols_present.append("unclassified")
            cols = [(f"{unit} grain — tool / cohort", False), ("n", True)] + \
                   [(t.replace("_", " "), True) for t in cols_present]
            rows = []
            for key, cnt in sorted(groups.items()):
                n = sum(cnt.values())
                cells = [(H.escape(key), key), (count(n), n)]
                for t in cols_present:
                    v = cnt.get(t, 0)
                    cells.append((pair(f"{v / n:.0%}", f"{v}"), v / n)
                                 if v else ('<span class="fig">0</span>', 0))
                rows.append(cells)
            mix_html += ('<div class="grid2"><div>'
                         + _mix_bars(unit, groups, cols_present)
                         + "</div><div>" + table(cols, rows)
                         + "</div></div>")
        mix_html += evidence("~/.caliper/derived/classes/task_classes.jsonl "
                             "× sessions.jsonl cohort — cohorts never pooled "
                             "(ADR-0009)")

    # outcomes beside cost
    out_html = "<h2>Outcomes — beside what they cost</h2>"
    if not raw["signals"]:
        out_html += _empty("No signals yet. Run", "caliper signals")
    else:
        rows = []
        for ref, rp in sorted(s["repos"].items(),
                              key=lambda kv: -kv[1]["commits"]):
            name = rp.get("path") or ref
            cost = s["proj_cost"].get(name)
            surv = rp["surv30_median"]
            attr = rp.get("attr", {})
            attr_s = (f"{attr.get('known', 0)}k / {attr.get('partial', 0)}p "
                      f"/ {attr.get('unknown', 0)}u")
            gen = rp.get("gen_lines_excluded", 0)
            rows.append([
                (f'<a href="/repo/{quote(ref)}{_qs(filters)}">'
                 f"{H.escape(name)}</a>", name),
                (count(rp["commits"]), rp["commits"]),
                (pair(f"{surv:.0%}", f"n={rp['surv30_n']} commits")
                 if surv is not None else
                 absent("not yet measurable", "no commit has cleared the "
                        "30d horizon"), surv if surv is not None else -1),
                ((pair(f"{rp['rework_y']}/{rp['rework_m']}",
                       f"n={rp['rework_m']}") if rp["rework_m"]
                  else absent("not yet measurable")),
                 rp["rework_y"] if rp["rework_m"] else -1),
                (f'<span class="fig">{H.escape(attr_s)}</span>', attr_s),
                (count(gen) if gen else '<span class="fig">0</span>', gen),
                (money(cost, word="not recorded"),
                 cost if cost is not None else -1),
            ])
        cols = [("repo", False), ("commits", True),
                ("30d survival (median)", True), ("rework ≤14d", True),
                ("AI attr (k/p/u)", False), ("gen lines excluded", True),
                ("session list-$", True)]
        out_html += (
            _outcome_scatter(raw, s, filters)
            + '<p class="note">One row per measured repo: click through for '
            "its commits and sessions. Survival is the per-commit median; "
            "attribution is known/partial/unknown commits, never inferred "
            "from code.</p>"
            + table(cols, rows, sort_note="sorted by commit count")
            + evidence("~/.caliper/extracted/git_history/"
                       "production_signals.jsonl · spend join via project "
                       "display name (approximate: working-directory "
                       "mapping)"))

    cov_html = ("<h2>Coverage</h2>" + _coverage_table(s)
                + '<p class="note"><a href="/coverage'
                + _qs(filters) + '">Full coverage &amp; honesty view →</a></p>')

    body = (head + spend_html + mix_html + out_html + cov_html
            + caveat_block(_overview_caveats(s)))
    return page("Caliper — overview", body, "overview", loaded_at,
                filters, s["filters"])


def _coverage_table(s: dict) -> str:
    rows = []
    for tool in TOOLS:
        c = s["coverage"].get(tool)
        if not c:
            rows.append([
                (H.escape(tool), tool), ('<span class="fig">0</span>', 0),
                (absent("not recorded", "nothing extracted from this source"),
                 -1),
                (absent("not recorded"), -1), (absent("not recorded"), -1),
                (absent("not recorded"), -1),
            ])
            continue
        rows.append([
            (H.escape(tool), tool),
            (count(c["sessions"]), c["sessions"]),
            (pair(f"{c['repo_join'] / c['sessions']:.0%}",
                  f"{c['repo_join']}/{c['sessions']}"),
             c["repo_join"] / c["sessions"]),
            (count(c["with_tokens"]) if c["with_tokens"]
             else absent("not recorded", "source logs no tokens"),
             c["with_tokens"] or -1),
            (count(c["with_units"]) if c["with_units"]
             else absent("not recorded", "source has no prompt grain"),
             c["with_units"] or -1),
            (f'<span class="fig">{c["range"][0]} → {c["range"][1]}</span>',
             c["range"][0]),
        ])
    cols = [("tool", False), ("sessions", True), ("mapped to a project", True),
            ("with tokens", True), ("with prompt units", True),
            ("date range", False)]
    return (table(cols, rows)
            + evidence("~/.caliper/extracted/*/sessions.jsonl, "
                       "prompt_units.jsonl · 'mapped to a project' is the "
                       "display-name proxy — cite ADR-0006 "
                       "(claude_code 95%, codex 81%, cursor 60%) for "
                       "measured session→repo join rates"))


def coverage_view(raw: dict, s: dict, filters: dict, loaded_at: str) -> str:
    body = "<h2>Coverage &amp; honesty</h2>"
    if not s["n_sessions"] and not raw["signals"]:
        body += (_empty("No sessions extracted yet. Run", "caliper extract")
                 if not filters else
                 _empty("No sessions match this filter.", "")
                 + '<p class="empty"><a href="?">Clear the filter</a>.</p>')
        return page("Caliper — coverage", body, "coverage", loaded_at,
                    filters, s["filters"])
    src = s["sources"]
    rows = [
        [("session records", None), (count(sum(src["sessions"].values())),
                                     sum(src["sessions"].values()))],
        [("task_class records", None), (count(src["task_classes"]),
                                        src["task_classes"])],
        [("production_signal records", None),
         (count(src["production_signals"]), src["production_signals"])],
    ]
    body += ('<div class="grid2"><div>' + _coverage_table(s)
             + "</div><div><h2>Record counts on disk</h2>"
             + table([("record", False), ("count", True)], rows)
             + evidence("~/.caliper/extracted/ and ~/.caliper/derived/ — "
                        "counts are records in scope of the active filter")
             + "</div></div>")
    body += caveat_block([
        _SOLO,
        "Claude Code rotates logs at its cleanupPeriodDays setting (~30d "
        "default; measured, ADR-0011 postscript) — sessions whose raw logs "
        "aged out survive only as previously extracted records. Codex and "
        "Cursor showed no rotation.",
        "Cursor sessions are shape-only: no tokens, no turns, session-grain "
        "classification only (ADR-0004).",
        "The 'mapped to a project' column is an approximate display-name "
        "join; the measured session→repo join rates are ADR-0006's.",
        _LIST_PRICE,
    ])
    return page("Caliper — coverage", body, "coverage", loaded_at,
                filters, s["filters"])


def repo_detail(raw: dict, s: dict, ref: str, filters: dict,
                loaded_at: str) -> str | None:
    sigs = [r for r in raw["signals"] if r["change_ref"]["repo_ref"] == ref]
    if not sigs:
        return None
    now = datetime.now(timezone.utc)
    name = _repo_names(raw).get(ref, ref)
    rp = s["repos"].get(ref, {})
    surv = rp.get("surv30_median")
    cost = s["proj_cost"].get(name)

    head = (f'<h2>Repo · <span class="mono">{H.escape(name)}</span></h2>'
            f'<p class="meta">{rp.get("commits", len(sigs))} measured commits'
            " · 30d survival (per-commit median) "
            + (f'{surv:.0%} (n={rp.get("surv30_n")})' if surv is not None
               else "not yet measurable")
            + f' · rework {rp.get("rework_y", 0)}/{rp.get("rework_m", 0)}'
            f" · session list-$ "
            + (f'${cost:,.2f}' if cost is not None else "not recorded")
            + f' · ref <span class="mono">{H.escape(ref)}</span></p>')

    commits = ("<h2>Commits</h2>"
               + table(_COMMIT_COLS, _commit_rows(sigs, now),
                       sort_note="sorted newest first")
               + evidence("~/.caliper/extracted/git_history/"
                          "production_signals.jsonl → change_ref, survival, "
                          "rework, ai_attribution, generated"))

    # sessions that referenced this repo — approximate name join, said so
    sess_rows = []
    for sid, rec in raw["sessions"].items():
        if raw["names"].get(rec.get("project_ref")) != name:
            continue
        cls = _session_class(raw, sid)
        label = (cls["task_type"] or "unclassified") if cls else None
        c = _session_cost(raw, rec)
        model = next(iter(_dominant_models(rec)), None)
        sess_rows.append([
            (f'<a class="mono" href="/session/{quote(sid)}{_qs(filters)}">'
             f"{H.escape(sid[:18])}</a>", sid),
            (H.escape(rec["source_tool"]), rec["source_tool"]),
            (f'<span class="fig">{H.escape(rec["started_at"][:16].replace("T", " "))}</span>',
             rec["started_at"]),
            (f'<span class="mono">{H.escape(model)}</span>' if model
             else absent("not recorded"), model or ""),
            (money(c, word="not priced" if rec.get("tokens")
                   else "not recorded"), c if c is not None else -1),
            ((absent("unclassified") if label == "unclassified"
              else H.escape(label)) if label is not None
             else absent("unclassified", "no session-grain record"),
             label or ""),
        ])
    sessions = "<h2>Sessions that referenced this repo</h2>"
    if sess_rows:
        sessions += (
            '<p class="note">Join is by project display name — approximate '
            "(working-directory mapping), and it is presence in the repo's "
            "directory, not attribution of any commit.</p>"
            + table([("session", False), ("tool", False), ("started", False),
                     ("model", False), ("list-$", True), ("task class", False)],
                    sess_rows, sort_note="sortable; join is approximate")
            + evidence("sessions.jsonl → project_ref × local display-name "
                       "map × task_classes.jsonl (session grain)"))
    else:
        sessions += ('<p class="note">No extracted sessions joined to this '
                     "repo by display name — the join is approximate and "
                     "misses worktrees and renamed directories.</p>")

    body = head + commits + sessions + caveat_block([
        _LIST_PRICE,
        "The session list is an approximate display-name join, not "
        "session→commit attribution — the trace layer does not exist yet.",
        "Generated paths are excluded from work-line counts (gen-0.1.0 + "
        ".gitattributes, ADR-0015); the excluded delta is its own column.",
        _SOLO,
    ])
    return page(f"Caliper — {name}", body, "", loaded_at, filters)


def session_detail(raw: dict, s: dict, sid: str, filters: dict,
                   loaded_at: str) -> str | None:
    rec = raw["sessions"].get(sid)
    if rec is None:
        return None
    now = datetime.now(timezone.utc)
    tool = rec["source_tool"]
    tok = rec.get("tokens")
    cost = _session_cost(raw, rec)
    units = [u for u in raw["units"].get(tool, [])
             if u["session_id"] == sid]
    active_ms = sum(u["window"].get("active_ms") or 0 for u in units) \
        if units else None
    proj = raw["names"].get(rec.get("project_ref"))

    def kv(label, val):
        return f"<tr><td>{H.escape(label)}</td><td>{val}</td></tr>"

    models = rec.get("models") or []
    model_html = (", ".join(
        f'<span class="mono">{H.escape(m["model_id"])}</span>'
        for m in sorted(models,
                        key=lambda m: -(m.get("assistant_messages") or 0)))
        or absent("not recorded", f"{tool} logs no model ids"))
    turns = rec.get("turns") or {}
    facts = ('<h2>Session</h2><div class="wrap"><table class="kv"><tbody>'
             + kv("session id", f'<span class="mono">{H.escape(sid)}</span>')
             + kv("tool", H.escape(tool))
             + kv("project", H.escape(proj) if proj else
                  absent("not recorded", "no display-name mapping"))
             + kv("started", f'<span class="fig">{H.escape(rec["started_at"])}</span>')
             + kv("ended", f'<span class="fig">{H.escape(rec["ended_at"])}</span>'
                  + ("" if rec.get("end_observed") else
                     ' <span class="why">— end not observed, last activity'
                     "</span>"))
             + kv("wall clock", _dur(rec.get("wall_clock_ms")))
             + kv("active time", _dur(active_ms) if active_ms is not None
                  else absent("not recorded", "no prompt units for this "
                              "session"))
             + kv("model(s)", model_html)
             + kv("turns", (f'<span class="fig">{turns.get("user_messages", 0)}'
                            f" user · {turns.get('assistant_messages', 0)}"
                            f" assistant · {turns.get('tool_calls', 0)} tool"
                            "</span>") if turns else absent("not recorded"))
             + "</tbody></table></div>"
             + evidence(f"~/.caliper/extracted/{tool}/sessions.jsonl"))

    if tok:
        tok_rows = [[(H.escape(b.replace("_", " ")), b),
                     (count(tok.get(b, 0)), tok.get(b, 0))]
                    for b in ("input", "output", "cache_read",
                              "cache_creation")]
        tok_html = ("<h2>Tokens and cost</h2>"
                    + table([("bucket", False), ("tokens", True)], tok_rows)
                    + f'<p class="note">List-price equivalent: {money(cost)}'
                    + (" — priced at the dominant model (approximation)"
                       if cost is not None else "")
                    + f". {H.escape(_LIST_PRICE)}</p>"
                    + evidence("sessions.jsonl → tokens (four buckets, never "
                               "pooled) · sheet " + s["pricing"]["as_of"]))
    else:
        tok_html = ("<h2>Tokens and cost</h2><p class='note'>"
                    + absent("not recorded",
                             f"{tool} logs no token counts — spend is a "
                             "structural hole here, never zero (ADR-0004)")
                    + "</p>")

    cls = _session_class(raw, sid)
    if cls:
        m = cls.get("method") or {}
        label = cls["task_type"] or "unclassified"
        cls_html = ("<h2>Task classification (session grain)</h2>"
                    + '<div class="wrap"><table class="kv"><tbody>'
                    + kv("task type", absent("unclassified")
                         if label == "unclassified" else H.escape(label))
                    + kv("confidence", pair(f"{cls.get('confidence', 0):.2f}",
                                            "rule confidence, not a "
                                            "measured rate"))
                    + kv("rule", '<span class="mono">'
                         + H.escape(", ".join(m.get("rule_ids") or []))
                         + "</span>")
                    + kv("rationale", H.escape(m.get("rationale") or ""))
                    + (kv("alternatives", H.escape(
                        ", ".join(a.get("task_type", "") if isinstance(a, dict)
                                  else str(a) for a in cls["alternatives"])))
                       if cls.get("alternatives") else "")
                    + "</tbody></table></div>"
                    + evidence("~/.caliper/derived/classes/task_classes.jsonl "
                               f"· classifier {cls['classifier_version']} — "
                               "53.1% agreement (n=81, κ=0.41), ADR-0009"))
    else:
        cls_html = ("<h2>Task classification (session grain)</h2>"
                    + _empty("No session-grain classification record for "
                             "this session. Run", "caliper classify"))

    seen, file_rows = set(), []
    for u in units:
        for f in u["window"].get("files_edited") or []:
            if f["file_ref"] in seen:
                continue
            seen.add(f["file_ref"])
            flags = [w for w, k in (("test", "is_test_path"),
                                    ("config", "is_config_path"),
                                    ("agent-config", "is_agent_config_path"),
                                    ("docs", "is_docs_path"),
                                    ("new file", "is_new_file"))
                     if f.get(k)]
            file_rows.append([
                (f'<span class="mono">{H.escape(f["file_ref"])}</span>',
                 f["file_ref"]),
                (H.escape(f.get("extension") or ""), f.get("extension") or ""),
                (H.escape(", ".join(flags)) if flags else
                 '<span class="faint">none</span>', len(flags)),
            ])
    files_html = "<h2>Files touched (salted refs)</h2>"
    if file_rows:
        files_html += (table([("file ref", False), ("ext", False),
                              ("path flags", False)], file_rows)
                       + evidence(f"~/.caliper/extracted/{tool}/"
                                  "prompt_units.jsonl → window.files_edited "
                                  "— refs are salted, paths never leave the "
                                  "machine"))
    elif tool == "cursor":
        files_html += ("<p class='note'>"
                       + absent("not recorded",
                                "Cursor logs no per-prompt file activity "
                                "(ADR-0004)") + "</p>")
    elif units:
        files_html += ('<p class="note">No files edited in this session\'s '
                       "recorded windows.</p>")
    else:
        files_html += ("<p class='note'>"
                       + absent("not recorded",
                                "no prompt units extracted for this session")
                       + "</p>")

    body = (f'<div class="grid2"><div>{facts}</div><div>{tok_html}</div>'
            f'</div><div class="grid2"><div>{cls_html}</div>'
            f"<div>{files_html}</div></div>"
            + _nearby_commits(raw, rec, now)
            + caveat_block([
                _LIST_PRICE,
                "Nearby commits are temporal proximity only — the trace "
                "layer that could attribute commits to sessions does not "
                "exist (it is stubbed, and this page will say so until it "
                "isn't).",
                _SOLO,
            ]))
    return page(f"Caliper — session {sid[:12]}", body, "", loaded_at, filters)


def not_found(what: str, filters: dict, loaded_at: str) -> str:
    body = (f'<p class="empty">{H.escape(what)} is not in the current '
            'records — it may be outside the active filter, or not '
            'extracted yet. <a href="/">Back to the overview</a>.</p>')
    return page("Caliper — not found", body, "", loaded_at, filters)
