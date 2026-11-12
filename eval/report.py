"""Static HTML reports.

  python -m eval.report run runs/<id> [--vs runs/<earlier>]   # one run, with a flip diff
  python -m eval.reproduce                                    # headline, reports/phase6/*

The headline is built by eval.reproduce from reports/phase6/manifest.yaml and
written to reports/phase6/{results.html, results.md, tradeoff.svg}.
"""
import argparse
import html
import json
from pathlib import Path

import yaml

from eval.stats import ci95, load, mcnemar

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports/phase6"

STYLE = """
:root { color-scheme: light; --surface: #fcfcfb; --page: #f4f4f2; --text: #0b0b0b;
  --text-2: #52514e; --muted: #8a8984; --grid: #e6e5e1; --border: #dcdbd6;
  --s1: #2a78d6; --s2: #eb6834; }
@media (prefers-color-scheme: dark) { :root:where(:not([data-theme="light"])) {
  color-scheme: dark; --surface: #1a1a19; --page: #121211; --text: #f0efec;
  --text-2: #c3c2b7; --muted: #8f8e88; --grid: #2c2c2a; --border: #3a3a37;
  --s1: #3987e5; --s2: #d95926; } }
:root[data-theme="dark"] { color-scheme: dark; --surface: #1a1a19; --page: #121211;
  --text: #f0efec; --text-2: #c3c2b7; --muted: #8f8e88; --grid: #2c2c2a;
  --border: #3a3a37; --s1: #3987e5; --s2: #d95926; }
"""
PAGE_CSS = STYLE + """
body { margin: 0; background: var(--page); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 16px; margin: 28px 0 8px; }
p.sub, .note { color: var(--text-2); font-size: 14px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px; overflow-x: auto; position: relative; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--grid);
  white-space: nowrap; font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-2); font-weight: 600; }
details summary { cursor: pointer; color: var(--text-2); }
code { font-size: 12.5px; }
#tip { position: absolute; pointer-events: none; background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 12.5px;
  box-shadow: 0 2px 8px rgba(0,0,0,.12); display: none; white-space: nowrap; }
"""


def summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text())


def mean_latency(run_dir: Path) -> float:
    rows = [json.loads(line) for line in open(run_dir / "log.jsonl")]
    return sum(r["latency_s"] for r in rows) / len(rows)


# ---------- tradeoff chart ----------

def tradeoff_svg(points: list[dict], standalone: bool) -> str:
    """x = mean seconds per question, y = EX; one colour per hint condition."""
    w, h, ml, mr, mt, mb = 760, 380, 56, 150, 20, 48
    xs = [p["x"] for p in points]
    ymin = max(0, min(p["y"] for p in points) // 10 * 10 - 10)
    ymax = min(100, max(p["y"] for p in points) // 10 * 10 + 10)
    xmax = (max(xs) // 5 + 1) * 5
    sx = lambda x: ml + (w - ml - mr) * x / xmax  # noqa: E731
    sy = lambda y: mt + (h - mt - mb) * (1 - (y - ymin) / (ymax - ymin))  # noqa: E731
    parts = []
    if standalone:
        parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
                     f'width="{w}" height="{h}" role="img" aria-label="Accuracy vs time per question">'
                     f'<style>{STYLE} text {{ font: 12px system-ui, sans-serif; fill: var(--text-2); }}'
                     f' .lbl {{ fill: var(--text); }}</style>'
                     f'<rect width="{w}" height="{h}" rx="10" fill="var(--surface)"/>')
    else:
        parts.append(f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
                     f'aria-label="Accuracy vs time per question" style="max-width:{w}px">'
                     '<style>text { font: 12px system-ui, sans-serif; fill: var(--text-2); }'
                     ' .lbl { fill: var(--text); }</style>')
    for y in range(int(ymin), int(ymax) + 1, 10):
        parts.append(f'<line x1="{ml}" x2="{w - mr}" y1="{sy(y):.1f}" y2="{sy(y):.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"/>'
                     f'<text x="{ml - 8}" y="{sy(y) + 4:.1f}" text-anchor="end">{y}</text>')
    for x in range(0, int(xmax) + 1, 5):
        parts.append(f'<text x="{sx(x):.1f}" y="{h - mb + 18}" text-anchor="middle">{x}</text>')
    parts.append(f'<line x1="{ml}" x2="{w - mr}" y1="{h - mb}" y2="{h - mb}" stroke="var(--border)"/>'
                 f'<text x="{(ml + w - mr) / 2:.0f}" y="{h - 10}" text-anchor="middle">'
                 'Seconds per question (mean, local M4 Pro)</text>'
                 f'<text x="14" y="{(mt + h - mb) / 2:.0f}" text-anchor="middle" '
                 f'transform="rotate(-90 14 {(mt + h - mb) / 2:.0f})">Execution accuracy (%)</text>')
    for p in points:
        color = "var(--s1)" if p["hints"] else "var(--s2)"
        cx, cy = sx(p["x"]), sy(p["y"])
        tip = html.escape(f'{p["label"]}: EX {p["y"]:.1f}%, {p["x"]:.1f} s/question')
        parts.append(f'<g class="pt" data-tip="{tip}"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="12" '
                     f'fill="transparent"/><circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{color}" '
                     f'stroke="var(--surface)" stroke-width="2"/>'
                     f'<text class="lbl" x="{cx + 9:.1f}" y="{cy + 4:.1f}">{html.escape(p["short"])}</text></g>')
    lx = w - mr + 16
    for i, (name, color) in enumerate((("With BIRD hints", "var(--s1)"), ("Without hints", "var(--s2)"))):
        parts.append(f'<circle cx="{lx}" cy="{mt + 10 + i * 20}" r="5" fill="{color}"/>'
                     f'<text class="lbl" x="{lx + 10}" y="{mt + 14 + i * 20}">{name}</text>')
    parts.append("</svg>")
    return "".join(parts)


TIP_JS = """<div id="tip"></div><script>
const tip = document.getElementById('tip');
document.querySelectorAll('.pt').forEach(g => {
  g.addEventListener('mousemove', e => {
    const box = g.closest('.card').getBoundingClientRect();
    tip.textContent = g.dataset.tip; tip.style.display = 'block';
    tip.style.left = (e.clientX - box.left + 12) + 'px'; tip.style.top = (e.clientY - box.top - 30) + 'px';
  });
  g.addEventListener('mouseleave', () => tip.style.display = 'none');
});</script>"""


# ---------- headline ----------

def headline(entries: list[dict], notes: list[str] | None = None) -> None:
    """entries: manifest rows with "run" (and optional "vs") resolved to run directories."""
    rows, points = [], []
    for item in entries:
        d = ROOT / item["run"]
        s = summary(d)["all"]
        correct = round(s["ex"] * s["n"] / 100)
        row = {**item, "n": s["n"], "ex": s["ex"], "ci": ci95(correct, s["n"]),
               "ex_tol": s["ex_tol"], "soft_f1": s["soft_f1"], "err": s["exec_error_rate"],
               "p50": s["latency_p50_s"], "mean_s": mean_latency(d),
               "tokens": s["input_tokens_mean"] + s["output_tokens_mean"]}
        if item.get("vs"):
            row["paired"] = mcnemar(load(ROOT / item["vs"]), load(d))
        rows.append(row)
        if item.get("chart", True) and item.get("dataset", "bird") == "bird":
            points.append({"x": row["mean_s"], "y": row["ex"], "hints": item["hints"],
                           "label": item["label"], "short": item["short"]})

    def paired_txt(r):
        pr = r.get("paired")
        if not pr:
            return "—"
        sign = "+" if pr["b_ex"] >= pr["a_ex"] else ""
        return f'{sign}{pr["b_ex"] - pr["a_ex"]:.1f} (p={pr["p"]:.3g})'

    head = ["Config", "Set", "n", "EX", "±95%", "EX tol.", "Soft-F1", "Exec err.",
            "s/question", "tokens/q", "vs. reference"]
    md = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    trs = []
    for r in rows:
        cells = [r["label"], r.get("dataset", "bird") + (" + hints" if r["hints"] else ""),
                 str(r["n"]), f'{r["ex"]:.1f}', f'{r["ci"]:.1f}', f'{r["ex_tol"]:.1f}',
                 f'{r["soft_f1"]:.1f}', f'{r["err"]:.1f}%', f'{r["mean_s"]:.1f}',
                 f'{r["tokens"]:,}', paired_txt(r)]
        md.append("| " + " | ".join(cells) + " |")
        trs.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
    (OUT / "results.md").write_text("\n".join(md) + "\n")
    (OUT / "tradeoff.svg").write_text(tradeoff_svg(points, standalone=True))
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in notes or [])
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>SQL Analyst Results</title>
<style>{PAGE_CSS}</style></head><body><main>
<h1>SQL analyst agent: results</h1>
<p class="sub">BIRD Mini-Dev (PostgreSQL, 500 questions) and a 40-question Pagila held-out set.
qwen2.5-coder via Ollama, $0. EX = execution accuracy, scored exactly as BIRD scores it.</p>
<h2>Accuracy vs time per question</h2>
<div class="card">{tradeoff_svg(points, standalone=False)}{TIP_JS}</div>
<h2>All configurations</h2>
<div class="card"><table><thead><tr>{''.join(f'<th>{h}</th>' for h in head)}</tr></thead>
<tbody>{''.join(trs)}</tbody></table></div>
<p class="note">"vs. reference": EX difference against the row's reference run on the same
questions, with an exact paired McNemar p-value.</p>
{'<h2>Notes</h2><ul class="note">' + notes + '</ul>' if notes else ''}
</main></body></html>"""
    (OUT / "results.html").write_text(page)
    print(f"wrote {OUT / 'results.html'}, results.md, tradeoff.svg")


# ---------- single run ----------

def run_report(run_dir: Path, vs: Path | None) -> Path:
    s = summary(run_dir)
    cfg = yaml.safe_load(open(run_dir / "config.yaml"))
    keys = ["n", "ex", "ex_tol", "soft_f1", "exec_error_rate", "latency_p50_s",
            "latency_p95_s", "input_tokens_mean", "output_tokens_mean"]
    trs = "".join(
        f"<tr><td>{d}</td>" + "".join(f"<td>{s[d].get(k, '')}</td>" for k in keys) + "</tr>"
        for d in ("all", "simple", "moderate", "challenging") if s.get(d))
    diff = ""
    if vs:
        a, b = load(vs), load(run_dir)
        pr = mcnemar(a, b)
        fixed = sorted(q for q in a if q in b and a[q] == 0 and b[q] == 1)
        broke = sorted(q for q in a if q in b and a[q] == 1 and b[q] == 0)
        diff = (f"<h2>Against {html.escape(vs.name)}</h2><p>EX {pr['a_ex']} → {pr['b_ex']} on "
                f"{pr['n']} shared questions; fixed {pr['fixed']}, broke {pr['broke']}, "
                f"McNemar p = {pr['p']}.</p>"
                f"<details><summary>Fixed ({len(fixed)})</summary><p><code>{', '.join(map(str, fixed))}</code></p></details>"
                f"<details><summary>Broke ({len(broke)})</summary><p><code>{', '.join(map(str, broke))}</code></p></details>")
    errs = "".join(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
                   for k, v in s.get("error_types", {}).items())
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Run Report</title>
<style>{PAGE_CSS}</style></head><body><main>
<h1>{html.escape(run_dir.name)}</h1>
<p class="sub">{html.escape(cfg.get('prompt_version', ''))} · {html.escape(cfg['model']['model'])}
 · config {html.escape(cfg.get('config_hash', ''))}</p>
<div class="card"><table><thead><tr><th>Split</th>{''.join(f'<th>{k}</th>' for k in keys)}</tr></thead>
<tbody>{trs}</tbody></table></div>
<h2>Final error types</h2><div class="card"><table><tbody>{errs or '<tr><td>none</td></tr>'}</tbody></table></div>
{diff}</main></body></html>"""
    out = run_dir / "report.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["run"])
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--vs")
    args = ap.parse_args()
    print(run_report(Path(args.run_dir), Path(args.vs) if args.vs else None))
