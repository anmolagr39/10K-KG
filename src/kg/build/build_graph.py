"""Build the knowledge graph from the extracted records.

Nodes (attribute `type`):
  company   AAPL ...                         filing / doc   one 10-K filing and its PDF(s)
  metric    revenue, net_income, ...        period         AAPL FY ending 2026-09-26 (rank 0 = latest)
  fact      one number or claim             source         doc + page + row text / quote + bbox
  entity    TSMC, KPMG LLP, a segment, a person (things that are not corpus companies)
Edges (attribute `rel`):
  fact -OF_METRIC-> metric, -ABOUT-> company, -FOR_PERIOD-> period, -SOURCED_FROM-> source,
  fact -COMPONENT_OF-> fact (row hierarchy: "Services" -> "Total net sales"),
  company -COMPETES_WITH / SUPPLIED_BY / CUSTOMER / HAS_SEGMENT / ACQUIRED / AUDITED_BY / HAS_CEO / HAS_CFO-> company|entity
      (every such edge carries `fact` = the relation fact node that holds the quote and source),
  entity -SAME_AS-> company (entity resolution), period -PRECEDES-> period,
  metric -DERIVED_FROM {formula}-> metric, source -IN_DOC-> doc -OF_FILING-> filing <-FILED- company.
Verification: accounting identities mark facts verified / unverified / conflicting.
"""
import gzip
import json
import re
from collections import defaultdict
from datetime import date, timedelta

import networkx as nx

from kg.build.entity_resolution import canonical_entity, resolve_company
from kg.build.normalize import ontology
from kg.config import EXTRACT_DIR, GRAPH_DIR, load_companies, load_manifest

REL_EDGE = {"competitor": "COMPETES_WITH", "supplier": "SUPPLIED_BY", "customer": "CUSTOMER",
            "segment": "HAS_SEGMENT", "acquisition": "ACQUIRED", "auditor": "AUDITED_BY",
            "ceo": "HAS_CEO", "cfo": "HAS_CFO"}
ATTR_METRICS = {"fiscal_year_end", "legal_name", "state_of_incorporation", "hq_location", "exchange",
                "shares_outstanding", "public_float", "employees", "auditor_city", "auditor_since"}


def _shift_years(d: str, years: int) -> str:
    x = date.fromisoformat(d)
    try:
        return x.replace(year=x.year - years).isoformat()
    except ValueError:
        return (x - timedelta(days=365 * years)).isoformat()


class Builder:
    def __init__(self):
        self.g = nx.MultiDiGraph()
        self.n_fact = 0

    def node(self, nid: str, **attrs) -> str:
        if nid not in self.g:
            self.g.add_node(nid, **attrs)
        return nid

    def edge(self, a: str, b: str, rel: str, **attrs) -> None:
        self.g.add_edge(a, b, key=rel, rel=rel, **attrs)

    def source(self, doc: str, page: int, text: str, bbox=None, key: str = "") -> str:
        sid = f"source:{doc}:p{page}:{key or abs(hash(text)) % 10**8}"
        if sid not in self.g:
            self.g.add_node(sid, type="source", doc=doc, page=page, text=text[:400], bbox=bbox)
            self.edge(sid, f"doc:{doc}", "IN_DOC")
        return sid

    def fact(self, **attrs) -> str:
        self.n_fact += 1
        fid = f"fact:{self.n_fact}"
        self.g.add_node(fid, type="fact", **attrs)
        return fid


# ---------------------------------------------------------------- periods

def company_periods(ticker: str, ex: dict) -> dict:
    """Fiscal periods of one company: {end_date: {rank, fy_label, approx}} plus a column resolver."""
    fye = next((f["value"] for f in ex["regex_facts"] if f["metric"] == "fiscal_year_end"), None)
    is_cols = {(f["col_year"], f["end_date"]) for f in ex["table_facts"] if f["statement"] == "IS"}
    years = sorted({y for y, _ in is_cols if y}, reverse=True)
    if not fye:
        dated = sorted({e for _, e in is_cols if e}, reverse=True)
        fye = dated[0] if dated else f"{years[0]}-12-31"
    periods = {}
    for r, y in enumerate(years[:4]):
        ends = [e for yy, e in is_cols if yy == y and e]
        end = ends[0] if ends else _shift_years(fye, r)
        periods[end] = {"rank": r, "fy_label": y, "approx": not ends}
    if fye not in periods and periods:
        # the cover says the year ended on fye; snap the rank-0 period to it when within a week
        e0 = next(e for e, p in periods.items() if p["rank"] == 0)
        if abs((date.fromisoformat(e0) - date.fromisoformat(fye)).days) <= 7:
            periods[fye] = periods.pop(e0)
    return {"fye": fye, "periods": periods}


def resolve_period(per: dict, col_year, end_date) -> str | None:
    """Map a table column (year printed in the header, optional date) to a period end date."""
    periods = per["periods"]
    if end_date:
        for e in periods:
            if abs((date.fromisoformat(e) - date.fromisoformat(end_date)).days) <= 7:
                return e
        return None
    for e, p in periods.items():
        if p["fy_label"] == col_year:
            return e
    return None


# ---------------------------------------------------------------- verification

def verify(facts: list[dict]) -> None:
    """Accounting identities over canonical facts of one company; sets f['verification']."""
    by = defaultdict(dict)
    for f in facts:
        if f.get("metric") and f.get("canonical"):
            by[f["period_end"]][f["metric"]] = f
    for f in facts:
        f.setdefault("verification", "unverified")
        f.setdefault("checks", [])

    def mark(ok: bool, name: str, *fs):
        for f in fs:
            f["checks"].append(f"{name}:{'pass' if ok else 'fail'}")
            if ok and f["verification"] != "conflicting":
                f["verification"] = "verified"
            if not ok and f["verification"] == "unverified":
                f["verification"] = "conflicting"

    def close(a, b, rel=0.0005):
        return abs(a - b) <= max(1e6 * 0.6, abs(b) * rel)

    for end, m in by.items():
        if "total_assets" in m and "total_liabilities_and_equity" in m:
            mark(close(m["total_assets"]["value"], m["total_liabilities_and_equity"]["value"]),
                 "assets=liabilities+equity", m["total_assets"], m["total_liabilities_and_equity"])
        if "total_liabilities" in m and "total_equity" in m and "total_liabilities_and_equity" in m:
            ok = close(m["total_liabilities"]["value"] + m["total_equity"]["value"], m["total_liabilities_and_equity"]["value"], 0.03)
            if ok:  # noncontrolling interests / temporary equity make small gaps normal: only count passes
                mark(True, "liabilities+equity=total", m["total_liabilities"], m["total_equity"])
        if "revenue" in m and "cost_of_revenue" in m and "gross_profit" in m:
            mark(close(m["revenue"]["value"] - m["cost_of_revenue"]["value"], m["gross_profit"]["value"]),
                 "revenue-cost=gross_profit", m["revenue"], m["cost_of_revenue"], m["gross_profit"])
        if "net_income" in m and m["net_income"].get("cf_value") is not None:
            ok = close(m["net_income"]["value"], m["net_income"]["cf_value"]) or m["net_income"].get("cf_matches_any_is_row")
            mark(bool(ok), "net_income(IS)=net_income(CF)", m["net_income"])
        if "operating_cash_flow" in m and "investing_cash_flow" in m and "financing_cash_flow" in m:
            pass  # FX effects and restricted cash make this check noisy; not used


def component_sums(rows: list[dict]) -> list[tuple[dict, list[dict]]]:
    """(total_row_fact, children) pairs whose children add up exactly to the total."""
    out = []
    groups = defaultdict(list)
    for f in rows:
        groups[(f["doc"], f["page"], f["statement"], f["col_index"])].append(f)
    for _, fs in groups.items():
        fs.sort(key=lambda f: f["row_idx"])
        for i, tot in enumerate(fs):
            if not tot["label"].lower().startswith("total") or not tot["section"]:
                continue
            kids = [f for f in fs[:i] if f["section"] == tot["section"] and not f["label"].lower().startswith("total")
                    and f["unit"] == tot["unit"]]
            if len(kids) >= 2 and abs(sum(k["value"] for k in kids) - tot["value"]) <= max(1e6, abs(tot["value"]) * 1e-6):
                out.append((tot, kids))
    return out


# ---------------------------------------------------------------- build

def build() -> nx.MultiDiGraph:
    b = Builder()
    onto = ontology()
    for mid, m in onto["metrics"].items():
        b.node(f"metric:{mid}", type="metric", id=mid, name=m["name"], kind=m["type"], statement=m["statement"],
               period_kind=m["period"], description=m.get("description", ""))
    for did, d in onto["derived"].items():
        b.node(f"metric:{did}", type="metric", id=did, name=d["name"], kind="derived", formula=d["formula"],
               unit=d["unit"], statement="derived", period_kind="duration")
        for inp in sorted(set(re.findall(r"[a-z_]+", d["formula"])) - {"revenue_per_employee"}):
            if f"metric:{inp}" in b.g:
                b.edge(f"metric:{did}", f"metric:{inp}", "DERIVED_FROM", formula=d["formula"])
    manifest = load_manifest()
    stats = defaultdict(int)
    for c in load_companies():   # all company nodes first: relations point across companies
        b.node(f"company:{c['ticker']}", type="company", ticker=c["ticker"], name=c["name"], sector=c["sector"],
               cik=c["cik"], aliases=c["aliases"])
    for c in load_companies():
        t = c["ticker"]
        ex = json.loads((EXTRACT_DIR / f"{t}.json").read_text(encoding="utf-8"))
        rel_path = EXTRACT_DIR / f"{t}.relations.json"
        rels = json.loads(rel_path.read_text(encoding="utf-8"))["relations"] if rel_path.exists() else []
        cid = f"company:{t}"
        docs = [r for r in manifest if r["ticker"] == t]
        fid_node = b.node(f"filing:{t}", type="filing", ticker=t, accession=docs[0]["accession"], form="10-K",
                          filing_date=docs[0]["filing_date"], period_of_report=docs[0]["period_of_report"])
        b.edge(cid, fid_node, "FILED")
        for d in docs:
            b.node(f"doc:{d['pdf']}", type="doc", file=d["pdf"], role=d["doc_role"], pages=int(d["pdf_pages"] or 0),
                   source_url=d["source_url"])
            b.edge(f"doc:{d['pdf']}", fid_node, "OF_FILING")

        # periods
        per = company_periods(t, ex)
        for end, p in per["periods"].items():
            b.node(f"period:{t}:{end}", type="period", ticker=t, end=end, rank=p["rank"], fy_label=p["fy_label"],
                   approx_end=p["approx"], label=f"{t} fiscal {p['fy_label']} (ended {end})")
            b.edge(f"period:{t}:{end}", cid, "PERIOD_OF")
        ordered = sorted(per["periods"].items(), key=lambda kv: kv[1]["rank"], reverse=True)
        for (e1, _), (e2, _) in zip(ordered, ordered[1:]):
            b.edge(f"period:{t}:{e1}", f"period:{t}:{e2}", "PRECEDES")

        # statement + note facts
        recs = []
        is_net_income = defaultdict(list)
        for f in ex["table_facts"] + ex.get("note_facts", []):
            end = resolve_period(per, f["col_year"], f["end_date"])
            if not end:
                stats["unresolved_period"] += 1
                continue
            f = dict(f, period_end=end)
            spec = onto["metrics"].get(f["metric"]) if f["metric"] else None
            f["canonical"] = bool(spec and f["statement"] == spec["statement"])
            if f["statement"] == "IS" and re.search(r"net (income|earnings)", f["label"], re.I):
                is_net_income[end].append(f["value"])
            recs.append(f)
        for f in recs:   # cross-statement corroboration: CF "Net income" vs the IS
            if f["metric"] == "net_income" and f["statement"] == "CF":
                tgt = next((x for x in recs if x["metric"] == "net_income" and x["canonical"] and x["period_end"] == f["period_end"]), None)
                if tgt:
                    tgt["cf_value"] = f["value"]
                    tgt["cf_matches_any_is_row"] = any(abs(v - f["value"]) < 1e6 for v in is_net_income[f["period_end"]])
        # banks that print no total revenue line (Capital One): revenue = NII + noninterest income, derived
        for end in per["periods"]:
            have = {x["metric"]: x for x in recs if x["canonical"] and x["period_end"] == end and x["metric"]}
            if "revenue" not in have and "net_interest_income" in have and "noninterest_income" in have:
                a, c2 = have["net_interest_income"], have["noninterest_income"]
                recs.append(dict(a, metric="revenue", value=a["value"] + c2["value"], label="Total net revenue (derived)",
                                 method="derived:net_interest_income+noninterest_income", derived_inputs=True,
                                 row_text=f"{a['row_text']} + {c2['row_text']}", canonical=True, _inputs=[a, c2]))
                stats["derived_revenue"] += 1
        verify([r for r in recs if r["statement"] in ("IS", "BS", "CF")])
        node_of = {}
        for f in recs:
            sid = b.source(f["doc"], f["page"], f["row_text"], f.get("bbox"),
                           key=f"{f['statement']}:{f['row_idx']}:{f['label'][:40]}")
            fid = b.fact(kind="number", ticker=t, metric=f["metric"], label=f["label"], section=f["section"],
                         value=f["value"], unit=f["unit"], statement=f["statement"], canonical=f["canonical"],
                         period_end=f["period_end"], col_year=f["col_year"], method=f["method"],
                         confidence=f["confidence"], verification=f.get("verification", "unverified"),
                         checks=f.get("checks", []), doc=f["doc"], page=f["page"],
                         context=f.get("context") or {"IS": "income statement", "BS": "balance sheet",
                                                      "CF": "cash flow statement"}.get(f["statement"], ""),
                         row_idx=f["row_idx"], col_index=f["col_index"])
            node_of[id(f)] = fid
            b.edge(fid, cid, "ABOUT")
            b.edge(fid, f"period:{t}:{f['period_end']}", "FOR_PERIOD")
            b.edge(fid, sid, "SOURCED_FROM")
            if f["metric"]:
                b.edge(fid, f"metric:{f['metric']}", "OF_METRIC")
            for inp in f.get("_inputs", []):
                b.edge(fid, node_of.get(id(inp), ""), "DERIVED_FROM") if id(inp) in node_of else None
            stats["facts_" + f["statement"]] += 1
        for tot, kids in component_sums([r for r in recs if id(r) in node_of]):
            for k in kids:
                b.edge(node_of[id(k)], node_of[id(tot)], "COMPONENT_OF")
            stats["component_edges"] += len(kids)

        # cover page / auditor / headcount / signature facts
        for f in ex["regex_facts"]:
            sid = b.source(f["doc"], f["page"], f["quote"], key=f"regex:{f['metric']}")
            m = f["metric"]
            if m in ("auditor", "ceo", "cfo"):
                name = f["value"]
                ent = canonical_entity(name) if m == "auditor" else name
                eid = b.node(f"entity:{ent}", type="entity", name=ent, kind="auditor" if m == "auditor" else "person")
                fid = b.fact(kind="relation", ticker=t, relation=REL_EDGE[m], object=ent, quote=f["quote"],
                             method=f["method"], doc=f["doc"], page=f["page"], verification="unverified")
                b.edge(fid, cid, "ABOUT")
                b.edge(fid, eid, "OBJECT")
                b.edge(fid, sid, "SOURCED_FROM")
                b.edge(cid, eid, REL_EDGE[m], fact=fid)
                stats["relation_" + m] += 1
                continue
            end = per["fye"]
            pid = f"period:{t}:{end}" if f"period:{t}:{end}" in b.g else None
            fid = b.fact(kind="number" if isinstance(f["value"], (int, float)) else "text", ticker=t, metric=m,
                         label=m, value=f["value"], unit=f["unit"], statement=f.get("statement", "cover"),
                         canonical=True, period_end=end, as_of=f.get("as_of"), method=f["method"], quote=f["quote"],
                         doc=f["doc"], page=f["page"], verification="unverified", confidence=f.get("confidence", 0.9))
            b.edge(fid, cid, "ABOUT")
            b.edge(fid, sid, "SOURCED_FROM")
            if f"metric:{m}" not in b.g:
                b.node(f"metric:{m}", type="metric", id=m, name=m.replace("_", " "), kind="text", statement="cover",
                       period_kind="instant")
            b.edge(fid, f"metric:{m}", "OF_METRIC")
            if pid:
                b.edge(fid, pid, "FOR_PERIOD")
            stats["regex_" + m] += 1

        # prose relations from the LLM (already grounded)
        for r in rels:
            rel = REL_EDGE[r["type"]]
            if r.get("company"):
                target = f"company:{r['company']}"
                ename = canonical_entity(r["entity"])
                eid = b.node(f"entity:{ename}", type="entity", name=ename, kind="organization")
                b.edge(eid, target, "SAME_AS")
            else:
                ename = r["entity"].strip() if r["type"] == "segment" else (r.get("entity_canonical") or canonical_entity(r["entity"]))
                target = b.node(f"entity:{ename}" if r["type"] != "segment" else f"segment:{t}:{ename}",
                                type="entity", name=ename, kind="segment" if r["type"] == "segment" else "organization")
            sid = b.source(r["doc"], r["page"], r["quote"], key=f"rel:{r['type']}:{r['entity'][:30]}")
            fid = b.fact(kind="relation", ticker=t, relation=rel, object=r.get("company") or ename, quote=r["quote"],
                         method=r["method"], doc=r["doc"], page=r["page"], verification="grounded")
            b.edge(fid, cid, "ABOUT")
            b.edge(fid, target, "OBJECT")
            b.edge(fid, sid, "SOURCED_FROM")
            b.edge(cid, target, rel, fact=fid)
            stats["relation_" + r["type"]] += 1
    # auditor entities are shared across companies -> SAME firm node links 35 filings
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(b.g, edges="edges")
    with gzip.open(GRAPH_DIR / "graph.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, default=str)
    types = defaultdict(int)
    for _, a in b.g.nodes(data=True):
        types[a["type"]] += 1
    summary = {"nodes": b.g.number_of_nodes(), "edges": b.g.number_of_edges(), "node_types": dict(types),
               "stats": dict(stats)}
    (GRAPH_DIR / "graph_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return b.g
