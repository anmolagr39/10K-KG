"""Turn the executor's result into a typed answer with citations (deterministic template, no LLM).

    python -m kg ask "Which of NVIDIA's competitors spent the most on R&D?" --explain
"""
import json

from kg.query.executor import answer_question
from kg.query.store import store


def typed_answer(res: dict) -> dict:
    """{"kind": number|percent|entity|list|ranking|compare|text|none, "value": ..., "unit": ...}"""
    items, op, args = res.get("items") or [], res.get("final_op"), res.get("final_args") or {}
    if not items:
        return {"kind": "none", "value": None}
    first = items[0]
    if op == "compare":
        return {"kind": "compare", "winner": first["winner"], "difference": first["value"], "unit": first.get("unit"),
                "ranking": first.get("ranking")}
    if op == "rank":
        if args.get("k") == 1 or len(items) == 1 and args.get("k"):
            return {"kind": "entity", "value": first["ticker"], "metric_value": first["value"], "unit": first.get("unit")}
        return {"kind": "ranking", "value": [it["ticker"] for it in items], "values": [it["value"] for it in items]}
    if op in ("related", "filter", "companies") and (len(items) != 1 or "value" not in first):
        names = [it.get("ticker") or it.get("name") for it in items]
        if len(names) == 1 and op == "related":
            return {"kind": "entity", "value": names[0], "list": names}
        return {"kind": "list", "value": names}
    if len(items) == 1:
        v, unit = first.get("value"), first.get("unit")
        if isinstance(v, str):
            return {"kind": "text", "value": v}
        return {"kind": "percent" if unit == "pct" else "number", "value": v, "unit": unit}
    return {"kind": "list_values", "value": [(it.get("ticker"), it.get("value")) for it in items]}


def citations(res: dict) -> list[dict]:
    s = store()
    out = []
    for fid in res.get("touched", []):
        a = s.node(fid)
        src = s.source_of(fid)
        out.append({"fact": fid, "ticker": a.get("ticker"), "metric": a.get("metric") or a.get("relation") or a.get("label"),
                    "kind": "relation" if a.get("kind") == "relation" else "value", "relation": a.get("relation"),
                    "object": a.get("object"),
                    "value": a.get("value", a.get("object")), "unit": a.get("unit"), "period_end": a.get("period_end"),
                    "doc": src.get("doc", a.get("doc")), "page": src.get("page", a.get("page")),
                    "quote": (src.get("text") or a.get("quote") or "")[:160], "verification": a.get("verification")})
    return out


def fmt_value(v, unit) -> str:
    if not isinstance(v, (int, float)):
        return str(v)
    if unit == "USD":
        return f"${v / 1e9:,.2f} billion" if abs(v) >= 1e9 else f"${v / 1e6:,.1f} million" if abs(v) >= 1e6 else f"${v:,.0f}"
    if unit == "pct":
        return f"{v:.2f}%"
    if unit == "USD/share":
        return f"${v:.2f} per share"
    if unit == "x":
        return f"{v:.2f}x"
    return f"{v:,.0f}"


def render(res: dict, ans: dict) -> str:
    k = ans["kind"]
    if k == "none":
        return f"Not found in the graph (abstained). Reason: {res.get('error')}"
    if k == "compare":
        return f"{ans['winner']}, higher by {fmt_value(ans['difference'], ans.get('unit'))} (ranking: {ans.get('ranking')})"
    if k == "entity":
        extra = f" ({fmt_value(ans['metric_value'], ans.get('unit'))})" if "metric_value" in ans else ""
        return f"{ans['value']}{extra}"
    if k in ("list", "ranking"):
        return (" > " if k == "ranking" else ", ").join(str(x) for x in ans["value"])
    if k in ("number", "percent"):
        return fmt_value(ans["value"], ans.get("unit"))
    return str(ans.get("value"))


def ask_cli(question: str, explain: bool = False) -> None:
    res = answer_question(question)
    ans = typed_answer(res)
    print("Q:", question)
    print("A:", render(res, ans))
    cites = citations(res)
    print("Sources:")
    for c in cites[:20]:
        v = fmt_value(c["value"], c["unit"]) if isinstance(c["value"], (int, float)) else c["value"]
        print(f"  - {c['ticker']} {c['metric']}: {v} {('(' + c['period_end'] + ')') if c.get('period_end') else ''}"
              f" -> {c['doc']} p.{c['page']}  [{c.get('verification')}]  \"{c['quote'][:90]}\"")
    if explain:
        print("\nPlan:")
        print(json.dumps(res["plans"][-1], indent=1))
        print("\nExecution trace:")
        for t in res.get("trace", []):
            print(f"  {t['step']} {t['op']} -> {t['n']} item(s): {t['result'][:6]}")
        print(f"\nRetrieved fact nodes ({len(res.get('touched', []))}): {res.get('touched', [])[:30]}")
        if res.get("repaired"):
            print("(the first plan failed and was repaired once)")
