"""Render a campaign journal as one self-contained HTML page (no external assets)."""

from __future__ import annotations

import json
from html import escape

from .journal import badge, num, primary_metric

CSS = """
:root { color-scheme: light dark; --surface:#fcfcfb; --panel:#f3f2ef; --ink:#0b0b0b;
  --ink2:#52514e; --line:#d9d8d3; --series:#2a78d6; }
@media (prefers-color-scheme: dark) { :root { --surface:#1a1a19; --panel:#242423; --ink:#f0efec;
  --ink2:#c3c2b7; --line:#3a3a37; --series:#3987e5; } }
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--surface); color:var(--ink);
  font:15px/1.5 system-ui, sans-serif; }
main { max-width:1120px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:16px; margin:36px 0 10px; }
p.sub, .muted { color:var(--ink2); } p.sub { margin:0 0 20px; }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; }
.tile { background:var(--panel); border-radius:8px; padding:12px 14px; }
.tile b { display:block; font-size:22px; font-variant-numeric:tabular-nums; }
.tile span { color:var(--ink2); font-size:13px; }
svg { width:100%; height:auto; display:block; } svg text { fill:var(--ink2); font-size:12px; }
.grid { stroke:var(--line); stroke-width:1; } .whisker { stroke:var(--ink2); stroke-width:1.5; }
.dot { fill:var(--series); stroke:var(--surface); stroke-width:2; }
.dot.hollow { fill:var(--surface); stroke:var(--series); }
.base { stroke:var(--ink2); stroke-width:1.5; stroke-dasharray:5 4; }
.scroll { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { text-align:left; padding:6px 7px; border-bottom:1px solid var(--line);
  vertical-align:top; white-space:nowrap; }
th { color:var(--ink2); font-weight:500; font-size:12px; }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
td.wide { white-space:normal; } details { white-space:normal; } details[open] { min-width:320px; }
summary { cursor:pointer; } pre { white-space:pre-wrap; word-break:break-word;
  background:var(--panel); padding:8px 10px; border-radius:6px; font-size:12px; margin:6px 0; }
ul.tree, ul.tree ul { list-style:none; margin:0; padding-left:20px;
  border-left:1px solid var(--line); }
ul.tree { padding-left:0; border-left:0; } ul.tree li { padding:3px 0 3px 8px; }
#tip { position:fixed; pointer-events:none; background:var(--ink); color:var(--surface);
  padding:6px 9px; border-radius:6px; font-size:12px; white-space:pre; display:none; z-index:2; }
"""

JS = """
const tip = document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el => {
  el.addEventListener('mousemove', e => { tip.textContent = el.dataset.tip;
    tip.style.display = 'block';
    tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (e.clientY + 14) + 'px'; });
  el.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
});
"""


def _chart(evals: list[dict], primary: str) -> str:
    """Discovery score of every idea in the order tried; whiskers are ±2·noise of the delta."""
    points = [(r, r["metrics"][primary]) for r in evals if r["metrics"][primary] is not None]
    if not points:
        return ""
    width, height, left, right, top, bottom = 960, 300, 56, 150, 16, 40
    lows = [v - 2 * (r.get("noise") or 0) for r, v in points]
    highs = [v + 2 * (r.get("noise") or 0) for r, v in points]
    lo, hi = min(lows), max(highs)
    pad = (hi - lo) * 0.12 or 0.01
    lo, hi = lo - pad, hi + pad

    def y(value: float) -> float:
        return top + (hi - value) / (hi - lo) * (height - top - bottom)

    def x(i: int) -> float:
        return left + (i + 0.5) * (width - left - right) / len(points)

    parts = []
    for i in range(5):
        value = lo + (hi - lo) * i / 4
        parts.append(
            f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(value):.1f}" '
            f'y2="{y(value):.1f}"/><text x="{left - 8}" y="{y(value) + 4:.1f}" '
            f'text-anchor="end">{value:.3f}</text>'
        )
    base = points[0][1]
    parts.append(
        f'<line class="base" x1="{left}" x2="{width - right}" y1="{y(base):.1f}" '
        f'y2="{y(base):.1f}"/>'
        f'<text x="{width - right + 8}" y="{y(base) + 4:.1f}">baseline {base:.4f}</text>'
    )
    for i, (r, value) in enumerate(points):
        spread = 2 * (r.get("noise") or 0)
        if spread:
            parts.append(
                f'<line class="whisker" x1="{x(i):.1f}" x2="{x(i):.1f}" '
                f'y1="{y(value - spread):.1f}" y2="{y(value + spread):.1f}"/>'
            )
        delta = (r.get("delta") or {}).get(primary)
        tip = f"#{r['seq']} {r['rule']}\n{primary} {num(value)}"
        tip += f"   Δ {num(delta, signed=True)}" if delta is not None else ""
        tip += f"\n{badge(r)}"
        hollow = " hollow" if r.get("verdict") == "guard-broken" else ""
        parts.append(
            f'<circle class="dot{hollow}" cx="{x(i):.1f}" cy="{y(value):.1f}" r="6"/>'
            f'<rect x="{x(i) - 16:.1f}" y="{top}" width="32" height="{height - top - bottom}" '
            f'fill="transparent" data-tip="{escape(tip, quote=True)}"/>'
            f'<text x="{x(i):.1f}" y="{height - bottom + 18}" text-anchor="middle">'
            f"#{r['seq']}</text>"
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(primary)} of each '
        f'idea on discovery data">{"".join(parts)}</svg>'
        '<p class="muted">Filled dot: guards hold. Hollow dot: a guard metric broke. Whiskers: '
        "±2 × noise of the difference from the baseline. Hover a column for details; the table "
        "below has every number.</p>"
    )


def _tree(evals: list[dict], primary: str) -> str:
    children: dict[str | None, list[dict]] = {}
    for r in evals:
        children.setdefault(r.get("parent"), []).append(r)

    def branch(parent: str | None) -> str:
        items = []
        for r in children.get(parent, []):
            delta = (r.get("delta") or {}).get(primary)
            change = f" Δ {num(delta, signed=True)}" if delta is not None else ""
            items.append(
                f"<li><b>{escape(r['rule'])}</b> <span class='muted'>#{r['seq']}, "
                f"{num(r['metrics'][primary])}{change}, {escape(r.get('verdict', ''))}</span>"
                f"{branch(r['rule'])}</li>"
            )
        return f"<ul>{''.join(items)}</ul>" if items else ""

    return branch(None).replace("<ul>", '<ul class="tree">', 1)


def _details(r: dict) -> str:
    blocks = []
    if r.get("hypothesis"):
        blocks.append(f"<p>{escape(r['hypothesis'])}</p>")
    if r.get("formula"):
        blocks.append(f"<pre>{escape(r['formula'])}</pre>")
    if r.get("guards_broken"):
        blocks.append(f"<p>Guards broken: {escape(', '.join(r['guards_broken']))}</p>")
    extra = {
        k: r[k]
        for k in ("folds", "fold_sd", "finalists", "baseline_metrics", "dev_gain",
                  "transfer_gain", "optimism_gap", "ideas_evaluated_before", "rule_json")
        if r.get(k) is not None
    }  # fmt: skip
    if extra:
        blocks.append(f"<pre>{escape(json.dumps(extra, indent=2))}</pre>")
    if not blocks:
        return ""
    return f"<details><summary>details</summary>{''.join(blocks)}</details>"


def _table(rows: list[dict], primary: str) -> str:
    scored = [r for r in rows if "metrics" in r]
    others = [k for k in (scored[0]["metrics"] if scored else {}) if k != primary]
    head = ["#", "kind", "data", "rule", "parent"]
    numeric = [primary, "Δ", "±noise", *others]
    cells = "".join(f"<th>{escape(h)}</th>" for h in head)
    cells += "".join(f'<th class="n">{escape(h.replace("precision@", "P@"))}</th>' for h in numeric)
    out = [f"<tr>{cells}<th>verdict</th><th></th></tr>"]
    span = len(head) + len(numeric) - 1
    for r in rows:
        start = f"<td>{r['seq']}</td><td>{escape(r['kind'])}</td>"
        if "metrics" not in r:
            if r["kind"] == "prepare":
                text = f"{r['dataset']}: " + ", ".join(f"{k} {v}" for k, v in r["rows"].items())
                text += " rows. Oriented discovery AUC per signal: " + ", ".join(
                    f"{k} {v:.3f}" for k, v in r["signal_auc"].items()
                )
            else:
                text = r.get("text") or f"{r.get('rule', '')}: ✕ {r.get('error', '')}"
            out.append(f'<tr>{start}<td class="wide" colspan="{span}">{escape(text)}</td></tr>')
            continue
        m, d = r["metrics"], r.get("delta") or {}
        values = [num(m[primary]), num(d.get(primary), signed=True), num(r.get("noise"))]
        values += [num(m[k]) for k in others]
        out.append(
            f"<tr>{start}<td>{escape(r['data'])}</td><td>{escape(r['rule'])}</td>"
            f"<td>{escape(r.get('parent') or '–')}</td>"
            + "".join(f'<td class="n">{v}</td>' for v in values)
            + f"<td>{escape(badge(r))}</td><td>{_details(r)}</td></tr>"
        )
    return f'<div class="scroll"><table>{"".join(out)}</table></div>'


def render(rows: list[dict], name: str) -> str:
    primary = primary_metric(rows)
    evals = [r for r in rows if r["kind"] == "eval" and "metrics" in r]
    ideas = evals[1:]
    verify = next((r for r in rows if r["kind"] == "verify"), None)
    final = next((r for r in rows if r["kind"] == "final"), None)
    gains = [(r["delta"][primary], r) for r in ideas if r["delta"].get(primary) is not None]
    best = max(gains, key=lambda g: g[0], default=None)
    best_label = f"largest discovery Δ ({best[1]['rule']}, {best[1]['verdict']})" if best else ""
    tiles = [
        (num(evals[0]["metrics"][primary]) if evals else "–", f"baseline {primary}, discovery"),
        (str(len(ideas)), "ideas evaluated"),
        (num(best[0], signed=True) if best else "–", best_label or "no ideas yet"),
        (badge(verify) if verify else "open",
         f"verification; frozen rule: {verify['frozen']}" if verify else "verification not used"),
        (num(final["metrics"][primary]) if final else "–",
         f"final holdout {primary}" if final else "final holdout not used"),
    ]  # fmt: skip
    tile_html = "".join(
        f'<div class="tile"><b>{escape(v)}</b><span>{escape(label)}</span></div>'
        for v, label in tiles
    )
    period = f"{rows[0]['time'][:10]} to {rows[-1]['time'][:10]}" if rows else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(name)} journal</title><style>{CSS}</style></head>
<body><main>
<h1>Campaign: {escape(name)}</h1>
<p class="sub">{len(rows)} journal entries, {period}. Numbers on different data piles are not
comparable with each other; Δ is always against the baseline on the same pile.</p>
<div class="tiles">{tile_html}</div>
<h2>{escape(primary)} on discovery, in the order ideas were tried</h2>
{_chart(evals, primary)}
<h2>Lineage: which idea came from which</h2>
{_tree(evals, primary)}
<h2>Full journal</h2>
{_table(rows, primary)}
</main><div id="tip"></div><script>{JS}</script></body></html>
"""
