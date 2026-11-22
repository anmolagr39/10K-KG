"""Build results/results.pdf (1-2 pages) from the evaluation outputs + results/analysis.md.

    python -m kg.eval.report
"""
import html
import json
import re
from pathlib import Path

from kg.build.render_pdf import render
from kg.config import RESULTS_DIR

TYPES = [("overall", "Overall"), ("single_fact", "Single-fact"), ("multi_hop", "Multi-hop"), ("cross_filing", "Cross-filing")]


def _load(name: str) -> dict | None:
    p = RESULTS_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _table(cols: list[tuple[str, dict | None]]) -> str:
    head = "".join(f"<th colspan=3>{html.escape(c)}</th>" for c, _ in cols)
    sub = "".join("<th>Acc</th><th>P</th><th>R</th>" for _ in cols)
    rows = []
    for key, label in TYPES:
        cells = ""
        for _, s in cols:
            v = (s or {}).get(key) or {}
            cells += "".join(f"<td>{v[m]:.2f}</td>" if v else "<td>-</td>" for m in ("accuracy", "precision", "recall"))
        n = next(((s or {}).get(key) or {}).get("n", "") for _, s in cols if s)
        rows.append(f"<tr><td>{label} (n={n})</td>{cells}</tr>")
    return f"<table><tr><th></th>{head}</tr><tr><th></th>{sub}</tr>{''.join(rows)}</table>"


def _md(text: str) -> str:
    """Tiny markdown: ## headings, - bullets, **bold**, `code`, paragraphs."""
    out, in_list = [], False
    for line in text.splitlines():
        s = html.escape(line.rstrip())
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        if s.startswith("## "):
            out.append(("</ul>" if in_list else "") + f"<h2>{s[3:]}</h2>")
            in_list = False
        elif s.lstrip().startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{s.lstrip()[2:]}</li>")
        elif not s.strip():
            if in_list:
                out.append("</ul>")
                in_list = False
        else:
            out.append(("</ul>" if in_list else "") + f"<p>{s}</p>")
            in_list = False
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def main() -> None:
    first = _load("first_frozen_run_summary.json")
    final = (_load("eval_test_graph.json") or {}).get("summary")
    bm25 = (_load("eval_test_bm25.json") or {}).get("summary")
    xb = _load("xbrl_extraction_summary.json") or {}
    analysis = (RESULTS_DIR / "analysis.md").read_text(encoding="utf-8") if (RESULTS_DIR / "analysis.md").exists() else ""
    cols = [("Graph, first frozen run", first), ("Graph, final", final), ("BM25 chunks + LLM", bm25)]
    cols = [c for c in cols if c[1]]
    css = """body{font-family:Segoe UI,Arial,sans-serif;font-size:9.3pt;line-height:1.32;margin:0;color:#111}
    h1{font-size:14pt;margin:0 0 4px} h2{font-size:10.5pt;margin:9px 0 3px;border-bottom:1px solid #999}
    p{margin:3px 0} ul{margin:2px 0 2px 16px;padding:0} li{margin:1px 0}
    table{border-collapse:collapse;margin:4px 0;font-size:8.8pt} td,th{border:1px solid #bbb;padding:2px 6px;text-align:center}
    td:first-child{text-align:left} code{font-size:8.5pt;background:#f2f2f2;padding:0 2px} .sub{color:#444}"""
    body = (f"<h1>Knowledge graph over 35 SEC 10-K filings: results</h1>"
            f"<p class=sub>Accuracy = correct answers / questions. P / R = fact-level precision / recall "
            f"(retrieved fact nodes vs gold supporting facts, macro-averaged). 30 frozen test questions.</p>"
            + _table(cols)
            + (f"<p>Extraction accuracy of core statement facts vs SEC XBRL: <b>{xb.get('matched')}/{xb.get('scored')} "
               f"({xb.get('accuracy', 0):.1%})</b>, 0 wrong values.</p>" if xb else "")
            + _md(analysis))
    page = f"<!doctype html><html><head><meta charset=utf-8><style>{css}</style></head><body>{body}</body></html>"
    out_html = RESULTS_DIR / "results.html"
    out_html.write_text(page, encoding="utf-8")
    render(out_html, RESULTS_DIR / "results.pdf")
    print("wrote", RESULTS_DIR / "results.pdf")


if __name__ == "__main__":
    main()
