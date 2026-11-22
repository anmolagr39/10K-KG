"""Deterministic scoring (no LLM judge).

Answer accuracy
  number    relative tolerance (default 0.5%); per-share absolute 0.005
  percent   absolute tolerance in percentage points (default 0.1)
  entity    alias-normalised match (ticker, company name, firm name, state)
  list      set equality;  ranking: exact order;  compare: same winner and difference within 0.5%
Fact-level retrieval (per question, then macro-averaged)
  a retrieved fact node matches a gold fact if it is about the same company and
    numeric/text: same period end (+-7 days) and value within tolerance (text: same normalised string)
    relation:     same relation and same normalised object
  precision = matched retrieved / retrieved,  recall = matched gold / gold
  citation page accuracy = matched retrieved facts whose page is the gold page (or an alt page)
"""
from datetime import date

from kg.build.entity_resolution import canonical_entity, norm_name, resolve_company


def _norm_ent(x) -> str:
    if x is None:
        return ""
    s = str(x)
    t = s.upper() if s.upper() in _tickers() else resolve_company(s)
    return t if t else norm_name(canonical_entity(s))


_T = None


def _tickers():
    global _T
    if _T is None:
        from kg.config import load_companies
        _T = {c["ticker"] for c in load_companies()}
    return _T


def answer_correct(gold: dict, pred: dict) -> bool:
    k = gold["kind"]
    if pred.get("kind") in (None, "none"):
        return False
    if k in ("number", "percent"):
        v = pred.get("value")
        if not isinstance(v, (int, float)):
            return False
        if k == "percent" and pred.get("unit") not in ("pct", None):
            return False
        g = gold["value"]
        tol = gold.get("tolerance", {})
        if "abs" in tol:
            return abs(v - g) <= tol["abs"]
        return abs(v - g) <= abs(g) * tol.get("rel", 0.005)
    if k == "entity":
        cands = {_norm_ent(gold["value"])} | {_norm_ent(a) for a in gold.get("aliases", [])}
        val = pred.get("value")
        if pred.get("kind") == "list" and isinstance(val, list) and len(val) == 1:
            val = val[0]
        return _norm_ent(val) in cands
    if k == "list":
        val = pred.get("value") if isinstance(pred.get("value"), list) else [pred.get("value")]
        return {_norm_ent(x) for x in val} == {_norm_ent(x) for x in gold["value"]}
    if k == "ranking":
        val = pred.get("value") if isinstance(pred.get("value"), list) else []
        return [_norm_ent(x) for x in val] == [_norm_ent(x) for x in gold["value"]]
    if k == "compare":
        if pred.get("kind") != "compare":
            return False
        win_ok = _norm_ent(pred.get("winner")) in {_norm_ent(gold["winner"])} | {_norm_ent(a) for a in gold.get("aliases", [])}
        d = pred.get("difference")
        return win_ok and isinstance(d, (int, float)) and abs(d - gold["difference"]) <= abs(gold["difference"]) * 0.005
    return False


def _close_dates(a, b) -> bool:
    if not a or not b:
        return True
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days) <= 7


def fact_matches(r: dict, g: dict) -> bool:
    if r.get("ticker") != g["ticker"]:
        return False
    if g["kind"] == "relation":
        rel = (r.get("relation") or "").upper()
        if not rel and r.get("kind") == "relation":   # baseline facts carry no relation type: object only
            return _norm_ent(r.get("object")) == _norm_ent(g["object"])
        return rel == g["relation"].upper() and _norm_ent(r.get("object")) == _norm_ent(g["object"])
    if r.get("kind") == "relation":
        return False
    rv, gv = r.get("value"), g["value"]
    if isinstance(gv, str) or isinstance(rv, str):
        return norm_name(str(rv)) == norm_name(str(gv))
    if not isinstance(rv, (int, float)):
        return False
    tol = 0.006 if abs(gv) < 1000 else max(abs(gv) * 0.005, 0.6e6 if g.get("unit") == "USD" else 0.5)
    return abs(rv - gv) <= tol and _close_dates(r.get("period_end"), g.get("period_end"))


def retrieval_scores(retrieved: list[dict], gold: list[dict]) -> dict:
    matched_r = [r for r in retrieved if any(fact_matches(r, g) for g in gold)]
    matched_g = [g for g in gold if any(fact_matches(r, g) for r in retrieved)]
    page_ok = 0
    for r in matched_r:
        g = next(g for g in gold if fact_matches(r, g))
        if r.get("page") in [g["page"]] + list(g.get("alt_pages", [])):
            page_ok += 1
    return {"precision": len(matched_r) / len(retrieved) if retrieved else 0.0,
            "recall": len(matched_g) / len(gold) if gold else 0.0,
            "n_retrieved": len(retrieved), "n_gold": len(gold), "n_matched_retrieved": len(matched_r),
            "n_matched_gold": len(matched_g),
            "page_accuracy": page_ok / len(matched_r) if matched_r else None}
