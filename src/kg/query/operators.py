"""Deterministic query operators over the graph.

Every operator returns a list of items (dicts) and records every fact node it touched in
`ctx.touched`. That set is the "retrieved facts" used for precision/recall: an answer can
only be built from facts the operators actually fetched, and every fact carries its source page.

Item shapes
  value item:   {"ticker", "value", "unit", "period_end", "fy_label", "fact_ids", "label"}
  entity item:  {"ticker" | "entity", "name", "fact_ids"}
"""
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from kg.build.entity_resolution import canonical_entity, norm_name, resolve_company
from kg.build.normalize import ontology
from kg.query.store import GraphStore


class OpError(Exception):
    """A structured error the planner can repair (unknown metric, nothing found, bad args)."""


@dataclass
class Ctx:
    s: GraphStore
    touched: list = field(default_factory=list)     # fact ids in retrieval order
    trace: list = field(default_factory=list)

    def touch(self, fids):
        for f in fids:
            if f not in self.touched:
                self.touched.append(f)


RELATIONS = {"competes_with": "COMPETES_WITH", "supplied_by": "SUPPLIED_BY", "customer": "CUSTOMER",
             "has_segment": "HAS_SEGMENT", "acquired": "ACQUIRED", "audited_by": "AUDITED_BY",
             "has_ceo": "HAS_CEO", "has_cfo": "HAS_CFO"}


# ---------------------------------------------------------------- helpers

def tickers_of(ctx: Ctx, x) -> list[str]:
    """Accept a ticker, a name, a list of them, or the items of an earlier step."""
    if x is None:
        return []
    if isinstance(x, dict):
        x = [x]
    if isinstance(x, str):
        x = [x]
    out = []
    for v in x:
        if isinstance(v, dict):
            t = v.get("ticker") if v.get("ticker") in ctx.s.companies else None
            if not t and v.get("name"):
                t = resolve_company(v["name"])
        else:
            t = v.upper() if isinstance(v, str) and v.upper() in ctx.s.companies else resolve_company(str(v))
        if t and t not in out:
            out.append(t)
    return out


def resolve_period(ctx: Ctx, ticker: str, period: str | int | None) -> dict | None:
    """latest_fy | prior_fy | fy:<label year> | end:<YYYY-MM-DD> | rank:<n> | a bare year (= fiscal label)."""
    ps = ctx.s.periods.get(ticker, [])
    if not ps:
        return None
    p = str(period or "latest_fy").strip().lower()
    if p in ("latest_fy", "latest", "current", "last_fy", "most_recent"):
        return ps[0]
    if p in ("prior_fy", "previous_fy", "prior"):
        return ps[1] if len(ps) > 1 else None
    m = re.match(r"^(?:rank:)?(\d)$", p)
    if m:
        r = int(m.group(1))
        return ps[r] if r < len(ps) else None
    m = re.match(r"^(?:fy:?|fiscal\s*)?(\d{4})$", p)
    if m:
        y = int(m.group(1))
        return next((x for x in ps if x["fy_label"] == y), None)
    m = re.match(r"^(?:end:)?(\d{4}-\d{2}-\d{2})$", p)
    if m:
        from datetime import date
        d = date.fromisoformat(m.group(1))
        return next((x for x in ps if abs((date.fromisoformat(x["end"]) - d).days) <= 7), None)
    return None


def _value_item(ctx: Ctx, fid: str, extra: dict | None = None) -> dict:
    a = ctx.s.node(fid)
    per = next((p for p in ctx.s.periods[a["ticker"]] if p["end"] == a.get("period_end")), {})
    it = {"ticker": a["ticker"], "value": a["value"], "unit": a.get("unit"), "period_end": a.get("period_end"),
          "fy_label": per.get("fy_label"), "label": a.get("label"), "fact_ids": [fid],
          "verification": a.get("verification")}
    if extra:
        it.update(extra)
    return it


# ---------------------------------------------------------------- operators

def op_companies(ctx: Ctx, sector: str | None = None, tickers=None) -> list[dict]:
    """Companies in the corpus, optionally one sector (Big Tech, Enterprise Software, Chips, Banks,
    Payments, Retail, Pharma) or an explicit list."""
    if tickers:
        return [{"ticker": t, "name": ctx.s.companies[t]["name"]} for t in tickers_of(ctx, tickers)]
    out = []
    for t, a in ctx.s.companies.items():
        if not sector or a["sector"].lower() == str(sector).lower():
            out.append({"ticker": t, "name": a["name"], "sector": a["sector"]})
    if not out:
        raise OpError(f"no companies for sector {sector!r}")
    return out


def op_get_fact(ctx: Ctx, companies, metric: str, period="latest_fy") -> list[dict]:
    """The value of a canonical metric for each company in the requested fiscal period."""
    if metric not in ctx.s.metrics or ctx.s.metrics[metric].get("kind") == "derived":
        raise OpError(f"unknown metric {metric!r}; use derive for derived metrics or find_line_item for other rows")
    out, missing = [], []
    for t in tickers_of(ctx, companies):
        fids = ctx.s.facts.get((t, metric), [])
        per = resolve_period(ctx, t, period)
        cands = [f for f in fids if per and ctx.s.node(f).get("period_end") == per["end"]]
        if not cands and ctx.s.metrics[metric].get("statement") in ("cover", "text", "auditor") and fids:
            cands = fids           # cover/prose facts are reported once, as of the filing
        if not cands:
            missing.append(t)
            continue
        out.append(_value_item(ctx, cands[0]))
        ctx.touch([cands[0]])
    if not out:
        raise OpError(f"no {metric} fact for {missing} in period {period}")
    return out


def op_derive(ctx: Ctx, companies, metric: str, period="latest_fy") -> list[dict]:
    """A derived metric (operating_margin_pct, free_cash_flow, ...) computed from its formula's inputs,
    following the Metric -DERIVED_FROM-> Metric edges. Inputs are facts in the graph."""
    spec = ontology()["derived"].get(metric)
    if not spec:
        raise OpError(f"unknown derived metric {metric!r}")
    out = []
    for t in tickers_of(ctx, companies):
        for formula in [spec["formula"]] + ([spec["fallback"]] if spec.get("fallback") else []):
            names = sorted(set(re.findall(r"[a-z_]+", formula)))
            vals, fids = {}, []
            for n in names:
                try:
                    it = op_get_fact(ctx, [t], n, period)[0]
                except OpError:
                    break
                vals[n] = it["value"]
                fids += it["fact_ids"]
            if len(vals) == len(names):
                try:
                    v = eval(formula, {"__builtins__": {}}, vals)
                except ZeroDivisionError:
                    continue
                per = resolve_period(ctx, t, period) or {}
                out.append({"ticker": t, "value": v, "unit": spec["unit"], "period_end": per.get("end"),
                            "fy_label": per.get("fy_label"), "label": spec["name"], "fact_ids": fids,
                            "formula": formula, "inputs": vals})
                break
    if not out:
        raise OpError(f"cannot derive {metric} for {companies} ({period}): inputs missing")
    return out


def op_yoy(ctx: Ctx, companies, metric: str, period="latest_fy") -> list[dict]:
    """Year-over-year growth (%) of a metric: period vs the period that PRECEDES it."""
    out = []
    for t in tickers_of(ctx, companies):
        cur = resolve_period(ctx, t, period)
        if not cur:
            continue
        prev = next((p for p in ctx.s.periods[t] if p["rank"] == cur["rank"] + 1), None)
        if not prev:
            continue
        try:
            a = op_get_fact(ctx, [t], metric, cur["end"])[0]
            b = op_get_fact(ctx, [t], metric, prev["end"])[0]
        except OpError:
            continue
        if b["value"]:
            out.append({"ticker": t, "value": (a["value"] - b["value"]) / abs(b["value"]) * 100, "unit": "pct",
                        "period_end": cur["end"], "fy_label": cur["fy_label"], "label": f"{metric} YoY growth",
                        "fact_ids": a["fact_ids"] + b["fact_ids"], "inputs": {"current": a["value"], "prior": b["value"]}})
    if not out:
        raise OpError(f"cannot compute YoY {metric} for {companies}")
    return out


def op_find_line_item(ctx: Ctx, company, query: str, period="latest_fy", k: int = 1) -> list[dict]:
    """Scoped label search over ONE company's own line items (rows not mapped to a metric),
    e.g. Apple 'Services net sales', Amazon 'AWS segment net sales'. Matches label + section + table context."""
    out = []
    q = query.lower()
    for t in tickers_of(ctx, company):
        per = resolve_period(ctx, t, period)
        scored = []
        for fid in ctx.s.line_items.get(t, []):
            a = ctx.s.node(fid)
            if per and a.get("period_end") != per["end"]:
                continue
            if a.get("unit") in ("pct", "number"):
                continue
            text = f"{a.get('section', '')} {a['label']}".lower()
            sc = 0.6 * fuzz.token_set_ratio(q, text) + 0.3 * fuzz.partial_ratio(a["label"].lower(), q) \
                + 0.1 * fuzz.token_set_ratio(q, a.get("context", "").lower()[:200])
            sc += 6 if a.get("statement") in ("IS", "BS", "CF") else 0   # audited statements first
            # section words the question does not mention ("Cost of revenue:" vs "Revenue: Service and other")
            q_words = set(re.findall(r"[a-z]+", q))
            sec_words = set(re.findall(r"[a-z]+", a.get("section", "").lower().split(">")[-1])) - {"and", "the", "of", "in", "for", "net"}
            sc -= 3 * len(sec_words - q_words)
            scored.append((sc, fid))
        scored.sort(reverse=True)
        for sc, fid in scored[:k]:
            out.append(_value_item(ctx, fid, {"match_score": round(sc, 1)}))
            ctx.touch([fid])
    if not out:
        raise OpError(f"no line item like {query!r} for {company}")
    return out


def _target_node(ctx: Ctx, x) -> list[str]:
    nodes = []
    for v in (x if isinstance(x, list) else [x]):
        if isinstance(v, dict):
            if v.get("ticker") in ctx.s.companies:
                nodes.append(f"company:{v['ticker']}")
            elif v.get("node"):
                nodes.append(v["node"])
            elif v.get("name"):
                nodes += _target_node(ctx, v["name"])
            continue
        t = v.upper() if isinstance(v, str) and v.upper() in ctx.s.companies else resolve_company(str(v))
        if t:
            nodes.append(f"company:{t}")
            continue
        canon = canonical_entity(str(v))
        cand = [n for n in ctx.s.g.nodes if n.startswith("entity:") and
                (n[7:].lower() == canon.lower() or norm_name(n[7:]) == norm_name(str(v)))]
        nodes += cand
    return nodes


def op_related(ctx: Ctx, subject, relation: str, direction: str = "out", in_corpus: bool | None = None,
               exclude=None) -> list[dict]:
    """Follow relation edges. direction='out': what the subject company names (its competitors, suppliers,
    auditor, CEO...). direction='in': which companies name the subject (e.g. who is supplied by TSMC,
    who is audited by the same firm). in_corpus=True keeps only companies of the corpus."""
    rel = RELATIONS.get(relation.lower(), relation.upper())
    if rel not in RELATIONS.values():
        raise OpError(f"unknown relation {relation!r}; use one of {list(RELATIONS)}")
    excl = set(tickers_of(ctx, exclude)) if exclude else set()
    out, seen = [], set()
    if direction == "out":
        for t in tickers_of(ctx, subject):
            for target, fid in ctx.s.rel_out.get((t, rel), []):
                key = target
                if key in seen:
                    continue
                is_co = target.startswith("company:")
                if in_corpus and not is_co:
                    continue
                tt = target.split(":", 1)[1] if is_co else None
                if tt in excl:
                    continue
                seen.add(key)
                out.append({"ticker": tt, "name": ctx.s.companies[tt]["name"] if is_co else ctx.s.node(target).get("name"),
                            "node": target, "fact_ids": [fid], "via": t})
                ctx.touch([fid])
    else:
        for node in _target_node(ctx, subject):
            hits = list(ctx.s.rel_in.get((node, rel), []))
            # an entity mentioned under several names: also follow SAME_AS company links
            for t, fid in hits:
                if t in excl or t in seen:
                    continue
                seen.add(t)
                out.append({"ticker": t, "name": ctx.s.companies[t]["name"], "node": f"company:{t}",
                            "fact_ids": [fid], "via": node})
                ctx.touch([fid])
    if not out:
        raise OpError(f"no {relation} ({direction}) relations for {subject}")
    return out


def op_filter(ctx: Ctx, items: list[dict], sector: str | None = None, exclude=None, min_value=None,
              max_value=None) -> list[dict]:
    """Keep items by company sector, drop given companies, or keep values in a range."""
    excl = set(tickers_of(ctx, exclude)) if exclude else set()
    out = []
    for it in items:
        t = it.get("ticker")
        if sector and (not t or ctx.s.companies[t]["sector"].lower() != str(sector).lower()):
            continue
        if t in excl:
            continue
        if min_value is not None and it.get("value", float("-inf")) < float(min_value):
            continue
        if max_value is not None and it.get("value", float("inf")) > float(max_value):
            continue
        out.append(it)
    if not out:
        raise OpError("filter removed every item")
    return out


def op_rank(ctx: Ctx, items: list[dict], order: str = "desc", k: int | None = None) -> list[dict]:
    """Sort value items; k=1 gives the top company (e.g. 'which has the highest ...')."""
    vals = [it for it in items if isinstance(it.get("value"), (int, float))]
    vals.sort(key=lambda it: it["value"], reverse=str(order).lower() != "asc")
    return vals[:k] if k else vals


def op_aggregate(ctx: Ctx, items: list[dict], fn: str = "sum") -> list[dict]:
    """sum | avg | count | min | max over value items."""
    vals = [it["value"] for it in items if isinstance(it.get("value"), (int, float))]
    fids = [f for it in items for f in it.get("fact_ids", [])]
    fn = fn.lower()
    if fn == "count":
        v = len(items)
    elif not vals:
        raise OpError("nothing to aggregate")
    else:
        v = {"sum": sum(vals), "avg": sum(vals) / len(vals), "mean": sum(vals) / len(vals),
             "min": min(vals), "max": max(vals)}[fn]
    unit = items[0].get("unit") if items and fn != "count" else "count"
    return [{"ticker": None, "value": v, "unit": unit, "label": f"{fn} of {len(items)}", "fact_ids": fids,
             "members": [it.get("ticker") for it in items]}]


def op_compute(ctx: Ctx, op: str, a: list[dict], b: list[dict]) -> list[dict]:
    """Arithmetic between two steps: ratio, ratio_pct, diff, sum, growth_pct. Items are aligned by
    company; a single item is broadcast."""
    def pick(items, t):
        if len(items) == 1:
            return items[0]
        return next((x for x in items if x.get("ticker") == t), None)
    keys = [x.get("ticker") for x in a] if len(a) >= len(b) else [x.get("ticker") for x in b]
    out = []
    for t in keys:
        x, y = pick(a, t), pick(b, t)
        if not x or not y:
            continue
        xv, yv = x["value"], y["value"]
        try:
            v = {"ratio": lambda: xv / yv, "ratio_pct": lambda: xv / yv * 100, "diff": lambda: xv - yv,
                 "sum": lambda: xv + yv, "growth_pct": lambda: (xv - yv) / abs(yv) * 100}[op]()
        except ZeroDivisionError:
            continue
        except KeyError:
            raise OpError(f"unknown compute op {op!r}")
        unit = "pct" if op in ("ratio_pct", "growth_pct") else ("x" if op == "ratio" and x.get("unit") == y.get("unit") else x.get("unit"))
        if op == "ratio" and x.get("unit") == "USD" and y.get("unit") == "count":
            unit = "USD"
        out.append({"ticker": x.get("ticker") or y.get("ticker"), "value": v, "unit": unit,
                    "label": f"{op}({x.get('label')}, {y.get('label')})", "fact_ids": x["fact_ids"] + y["fact_ids"],
                    "inputs": {"a": xv, "b": yv}})
    if not out:
        raise OpError("compute: inputs could not be aligned")
    return out


def op_compare(ctx: Ctx, items: list[dict]) -> list[dict]:
    """Which of two (or more) items is larger, and by how much (top minus second)."""
    vals = op_rank(ctx, items, "desc")
    if len(vals) < 2:
        raise OpError("compare needs at least two values")
    top, second = vals[0], vals[1]
    return [{"ticker": top["ticker"], "value": top["value"] - second["value"], "unit": top.get("unit"),
             "label": f"{top['ticker']} exceeds {second['ticker']}", "winner": top["ticker"],
             "fact_ids": [f for it in vals for f in it["fact_ids"]], "ranking": [v["ticker"] for v in vals]}]


OPS = {"companies": op_companies, "get_fact": op_get_fact, "derive": op_derive, "yoy": op_yoy,
       "find_line_item": op_find_line_item, "related": op_related, "filter": op_filter, "rank": op_rank,
       "aggregate": op_aggregate, "compute": op_compute, "compare": op_compare}
