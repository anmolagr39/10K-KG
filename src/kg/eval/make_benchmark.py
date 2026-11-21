"""Build benchmark/test.jsonl and dev.jsonl from benchmark/gold_source.yaml.

Golden answers of derived questions (margins, growth, sums, differences) are COMPUTED here from
the gold facts with the recorded formula, never typed by hand.

    python -m kg.eval.make_benchmark
"""
import json
import re

import yaml

from kg.config import BENCH_DIR, load_manifest

DEFAULT_TOL = {"number": {"rel": 0.005}, "percent": {"abs": 0.1}, "per_share": {"abs": 0.005}}


def doc_for(ticker: str, role: str = "main") -> str:
    for r in load_manifest():
        if r["ticker"] == ticker and r["doc_role"] == role:
            return r["pdf"]
    raise KeyError((ticker, role))


def fact_value(f: dict) -> float | str:
    if "rel" in f:
        return f["obj"]
    if f.get("unit") == "text":
        return f["printed"]
    if "value" in f:
        raw = float(f["value"])
    else:
        raw = float(re.sub(r"[,$()]", "", str(f["printed"])))
        if str(f["printed"]).startswith("("):
            raw = -raw
    scale = float(f.get("scale", 1e6 if f.get("unit") == "USD" else 1))
    return raw * scale


def build_item(item: dict, split: str) -> dict:
    facts = {}
    gold = []
    for key, f in item["facts"].items():
        v = fact_value(f)
        facts[key] = v
        g = {"key": key, "ticker": f["t"], "doc": doc_for(f["t"], f.get("doc", "main")), "page": f["page"],
             "alt_pages": f.get("alt", [])}
        if "rel" in f:
            g.update({"kind": "relation", "relation": f["rel"], "object": f["obj"], "quote": f["quote"]})
        else:
            g.update({"kind": "value", "metric": f["m"], "value": v, "unit": f.get("unit"),
                      "period_end": str(f["end"]) if f.get("end") else None, "printed": str(f["printed"]),
                      "xbrl": f.get("xbrl")})
        gold.append(g)
    a = dict(item["answer"])
    kind = a["kind"]
    ans = {"kind": kind}
    if kind in ("number", "percent"):
        val = eval(a["formula"], {"__builtins__": {}}, facts)  # formula over gold fact values only
        ans.update({"value": round(val, 6), "unit": a.get("unit", "pct" if kind == "percent" else None),
                    "formula": a["formula"]})
        tol_kind = "per_share" if a.get("unit") == "USD/share" else kind
        ans["tolerance"] = {"rel": a["tolerance_rel"]} if "tolerance_rel" in a else DEFAULT_TOL[tol_kind]
    elif kind == "compare":
        val = eval(a["formula"], {"__builtins__": {}}, facts)
        ans.update({"winner": a["winner"], "aliases": a.get("aliases", []), "difference": val,
                    "formula": a["formula"], "tolerance": {"rel": 0.005}})
    elif kind in ("entity", "list", "ranking"):
        ans.update({"value": a["value"], "aliases": a.get("aliases", [])})
    return {"id": item["id"], "split": split, "type": item["type"], "question": item["question"],
            "answer": ans, "gold_facts": gold, "part": item.get("part", ""), "note": item.get("note", "")}


def fmt_answer(a: dict) -> str:
    k = a["kind"]
    if k == "percent":
        return f"{a['value']:.2f}%  (= {a['formula']})"
    if k == "number":
        v = a["value"]
        if a.get("unit") == "USD":
            return f"${v/1e6:,.0f} million" + (f"  (= {a['formula']})" if a["formula"] != "f1" else "")
        if a.get("unit") == "USD/share":
            return f"${v:,.2f} per share"
        return f"{v:,.0f}" + (f"  (= {a['formula']})" if a["formula"] != "f1" else "")
    if k == "compare":
        return f"{a['winner']}, by ${a['difference']/1e6:,.0f} million  (= {a['formula']})"
    if k == "ranking":
        return " > ".join(a["value"])
    if k == "list":
        return ", ".join(a["value"])
    return str(a["value"])


def write_review(rows_by_split: dict) -> None:
    out = ["# Benchmark review sheet", "",
           "Generated from `benchmark/gold_source.yaml` by `python -m kg.eval.make_benchmark`.",
           "Every gold fact was checked by `python -m kg.eval.gold_check` (value printed on the cited page; "
           "numbers equal to SEC XBRL). Pages are 1-based physical pages of the PDF in `data/pdfs/`.", ""]
    for split, rows in rows_by_split.items():
        out += [f"## {split} set ({len(rows)} questions)", ""]
        for r in rows:
            out += [f"### {r['id']} · {r['type']} · {r['part']}", "", f"**Q:** {r['question']}", "",
                    f"**Gold answer:** {fmt_answer(r['answer'])}", ""]
            if r.get("note"):
                out += [f"_Note: {r['note']}_", ""]
            out += ["| fact | company | what | value as printed | period end | doc | page |", "|---|---|---|---|---|---|---|"]
            for g in r["gold_facts"]:
                what = g.get("metric") or f"{g['relation']} → {g['object']}"
                val = g.get("printed") or f"\"{g['quote']}\""
                out.append(f"| {g['key']} | {g['ticker']} | {what} | {val} | {g.get('period_end') or ''} | "
                           f"{g['doc']} | {g['page']} |")
            out.append("")
    (BENCH_DIR / "REVIEW.md").write_text("\n".join(out), encoding="utf-8")


def main() -> None:
    src = yaml.safe_load((BENCH_DIR / "gold_source.yaml").read_text(encoding="utf-8"))
    rows_by_split = {}
    for split in ("test", "dev"):
        rows = [build_item(it, split) for it in src[split]]
        rows_by_split[split] = rows
        with open(BENCH_DIR / f"{split}.jsonl", "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        by_type = {}
        for r in rows:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        print(f"{split}: {len(rows)} questions {by_type}")
    write_review(rows_by_split)


if __name__ == "__main__":
    main()
