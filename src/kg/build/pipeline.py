"""`python -m kg build`: PDFs -> extracted fact records -> knowledge graph.

Stages
  extract    statements (tables) + cover/auditor/headcount/signatures (regex) -> data/extracted/<T>.json
  relations  prose relations via LLM with a grounding check            -> data/extracted/<T>.relations.json
  graph      normalise periods, verify identities, build the graph      -> data/graph/graph.json
"""
import json
import time

from kg.config import EXTRACT_DIR, load_companies, load_manifest


def docs_of(ticker: str) -> list[dict]:
    return [r for r in load_manifest() if r["ticker"] == ticker]


def extract_company(ticker: str) -> dict:
    from kg.build.regex_facts import auditor_facts, cover_facts, employee_facts, signature_facts
    from kg.build.statements import find_statement_pages, statement_facts

    docs = docs_of(ticker)
    main = next(d["pdf"] for d in docs if d["doc_role"] == "main")
    facts, pages_found = [], {}
    # primary statements: look in every document of the filing (Exhibit 13 holds them for IBM/WFC)
    best: dict = {}
    for d in docs:
        for st, (pages, score) in find_statement_pages(d["pdf"], with_scores=True).items():
            if st not in best or score > best[st][2]:
                best[st] = (d["pdf"], pages, score)
    for st in ("IS", "BS", "CF"):
        if st in best:
            pdf, pages, _ = best[st]
            pages_found[st] = (pdf, pages)
            facts += statement_facts(ticker, pdf, st, pages)
    # long tail: every other year-column table (MD&A, notes) as labelled line items
    from kg.build.notes import note_facts
    notes = []
    for d in docs:
        skip = {p for st, (pdf, pages) in pages_found.items() if pdf == d["pdf"] for p in pages}
        notes += note_facts(ticker, d["pdf"], skip)
    all_t = {c["ticker"] for c in load_companies()}
    other = cover_facts(ticker, main, all_t)
    for d in docs:
        a = auditor_facts(ticker, d["pdf"])
        if a:
            other += a
            break
    other += employee_facts(ticker, main) or []
    other += signature_facts(ticker, main)
    return {"ticker": ticker, "statement_pages": {k: {"doc": v[0], "pages": v[1]} for k, v in pages_found.items()},
            "table_facts": facts, "note_facts": notes, "regex_facts": other}


def run(tickers: list[str] | None = None, stage: str = "all") -> None:
    companies = [c["ticker"] for c in load_companies() if not tickers or c["ticker"] in tickers]
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    if stage in ("extract", "all"):
        for t in companies:
            t0 = time.time()
            out = extract_company(t)
            (EXTRACT_DIR / f"{t}.json").write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
            mapped = sorted({f["metric"] for f in out["table_facts"] if f["metric"]})
            print(f"{t:5s} notes={len(out['note_facts'])} pages={ {k: v['pages'] for k, v in out['statement_pages'].items()} } "
                  f"rows={len(out['table_facts'])} metrics={len(mapped)} regex={len(out['regex_facts'])} "
                  f"({time.time() - t0:.1f}s)", flush=True)
    if stage in ("relations", "all"):
        from kg.build.text_relations import run as run_relations
        run_relations(companies)
    if stage in ("graph", "all"):
        from kg.build.build_graph import build
        build()
