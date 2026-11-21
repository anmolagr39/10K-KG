"""Prose-only relations (competitors, suppliers/foundries, major customers, segments, acquisitions).

These facts exist only as sentences in Item 1 (Business), so they need an LLM to read them.
To keep the LLM honest:
  1. it only sees keyword-selected sentences of Item 1, each tagged with its PDF page;
  2. it must return the exact supporting quote and the page for every relation;
  3. code checks the quote really is on that page (whitespace/quote-normalised, then fuzzy >= 92)
     and that the entity name occurs in the quote. Anything that fails is dropped and counted.
Output: data/extracted/<T>.relations.json
"""
import json
import re

from rapidfuzz import fuzz

from kg.build.entity_resolution import canonical_entity, resolve_company
from kg.build.pdftext import page_texts
from kg.config import EXTRACT_DIR, load_companies, load_manifest
from kg.llm import EXTRACT_MODEL, LLMError, chat_json

KEYWORDS = re.compile(r"compet|rival|foundr|supplier|suppl(y|ies) |manufactur|contract manufacturer|"
                      r"customer[s]? (accounted|represented)|accounted for (approximately )?\d+%|% of (our )?(total |net )?revenue|"
                      r"largest customer|significant customer|acquired|acquisition of|reportable segment|operating segment",
                      re.I)
MAX_CHARS = 14000

PROMPT = """You extract business relations from excerpts of {company}'s annual report (10-K, Item 1 Business).
Each excerpt starts with [p.N] = its PDF page.

Return JSON: {{"relations": [{{"type": ..., "entity": ..., "quote": ..., "page": N}}]}}
type is one of:
  "competitor"  - a company {company} names as a competitor
  "supplier"    - a company that manufactures for / supplies {company} (foundry, contract manufacturer, key supplier)
  "customer"    - a named customer that is significant to {company} (e.g. accounts for a % of revenue)
  "segment"     - a reportable/operating segment of {company} (entity = segment name)
  "acquisition" - a company {company} acquired or agreed to acquire
Rules:
- entity must be a specific organization (or segment) NAMED in the text, never a category like "cloud providers".
- quote must be copied EXACTLY from the excerpt (8-30 words) and must contain the entity name.
- page is the [p.N] of the excerpt the quote comes from.
- list each (type, entity) once. If nothing qualifies, return {{"relations": []}}.

EXCERPTS:
{text}"""


def item1_pages(pdf: str) -> list[int]:
    """0-based page indexes of Item 1 (Business), skipping the table of contents."""
    texts = page_texts(pdf)
    start = end = None
    for i, t in enumerate(texts):
        if i < 2 or t.count("Item") + t.count("ITEM") > 8:
            continue
        if start is None and re.search(r"(^|\n)\s*item\s*1\.?\s*(\n\s*)?business\b", t, re.I):
            start = i
        elif start is not None and re.search(r"(^|\n)\s*item\s*1a\.?\s*(\n\s*)?risk\s+factors", t, re.I):
            end = i
            break
    if start is None:
        return list(range(2, min(len(texts), 25)))
    return list(range(start, (end if end else min(len(texts), start + 25)) + 1))


def excerpts(pdf: str) -> str:
    texts = page_texts(pdf)
    chunks, used = [], 0
    for i in item1_pages(pdf):
        flat = re.sub(r"\s+", " ", texts[i])
        raw = re.split(r"(?<=[.;:])\s+(?=[A-Z•(])", flat)
        sents: list[str] = []
        for piece in raw:   # do not split after abbreviations: "Huawei Technologies Co. Ltd."
            if sents and re.search(r"\b(Co|Inc|Corp|Ltd|No|U\.S|e\.g|i\.e|Jr|St)\.$", sents[-1]):
                sents[-1] += " " + piece
            else:
                sents.append(piece)
        keep = set()
        for k, s in enumerate(sents):
            if KEYWORDS.search(s) and s.rstrip().endswith(":"):
                # "Our current competitors include:" -> keep the whole list, up to the item ending in "."
                keep.add(k)
                j = k + 1
                while j < len(sents) and j < k + 15:
                    keep.add(j)
                    if sents[j].rstrip().endswith(".") and not sents[j].rstrip().endswith(("Inc.", "Co.", "Corp.")):
                        break
                    j += 1
            elif KEYWORDS.search(s) and re.search(r"\b[A-Z][a-zA-Z&]+(?:\s[A-Z][a-zA-Z&.]+)*", s[1:]):
                keep.add(k)
        if not keep:
            continue
        text = " ".join(sents[k] for k in sorted(keep) if k < len(sents))
        piece = f"[p.{i + 1}] {text}"
        if used + len(piece) > MAX_CHARS:
            piece = piece[:max(0, MAX_CHARS - used)]
        chunks.append(piece)
        used += len(piece)
        if used >= MAX_CHARS:
            break
    return "\n".join(chunks)


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip().lower()


def grounded(rel: dict, texts: list[str]) -> tuple[bool, int | None]:
    """Is the quote on the cited page (or the page next to it), and does it contain the entity?"""
    quote, ent = _norm(rel.get("quote", "")), rel.get("entity", "")
    if len(quote) < 10:
        return False, None
    ent_ok = any(tok and tok in quote for tok in {_norm(ent), _norm(canonical_entity(ent))}) or \
        any(_norm(w) in quote for w in re.findall(r"[A-Z][A-Za-z&]{2,}", ent))
    if not ent_ok:
        return False, None
    try:
        page = int(rel.get("page"))
    except (TypeError, ValueError):
        return False, None
    # an elided quote ("such as ... Qualcomm with its Snapdragon products") is accepted only if
    # every fragment is verbatim on the page and the entity is inside one of the fragments
    frags = [f.strip(" ,;") for f in re.split(r"\s*(?:\.\.\.|…)\s*", quote) if len(f.strip(" ,;").split()) >= 3]
    for p in (page, page - 1, page + 1):
        if 1 <= p <= len(texts):
            hay = _norm(texts[p - 1])
            if quote in hay or fuzz.partial_ratio(quote, hay) >= 92:
                return True, p
            if len(frags) > 1 and all(f in hay for f in frags) and \
                    any(_norm(w) in f for f in frags for w in re.findall(r"[A-Z][A-Za-z&]{2,}", ent)):
                return True, p
            # a sentence can run across a page break: cited page + next page
            if p < len(texts):
                both = hay + " " + _norm(texts[p])
                if quote in both or fuzz.partial_ratio(quote, both) >= 92:
                    return True, p
    return False, None


def extract_company(ticker: str, name: str, pdf: str) -> dict:
    text = excerpts(pdf)
    texts = page_texts(pdf)
    if not text:
        return {"ticker": ticker, "relations": [], "dropped": [], "chars": 0}
    raw = chat_json([{"role": "user", "content": PROMPT.format(company=name, text=text)}],
                    model=EXTRACT_MODEL, max_tokens=2500, tag=f"relations:{ticker}")
    keep, dropped, seen = [], [], set()
    for rel in raw.get("relations", []) or []:
        if not isinstance(rel, dict) or rel.get("type") not in ("competitor", "supplier", "customer", "segment", "acquisition"):
            continue
        ok, page = grounded(rel, texts)
        if not ok:
            dropped.append(rel)
            continue
        target = resolve_company(rel["entity"]) if rel["type"] != "segment" else None
        if target == ticker:
            continue
        key = (rel["type"], target or canonical_entity(rel["entity"]).lower())
        if key in seen:
            continue
        seen.add(key)
        keep.append({"ticker": ticker, "type": rel["type"], "entity": rel["entity"].strip(),
                     "entity_canonical": canonical_entity(rel["entity"]) if not target else None,
                     "company": target, "quote": rel["quote"].strip(), "page": page, "doc": pdf,
                     "method": "llm+grounding"})
    return {"ticker": ticker, "relations": keep, "dropped": dropped, "chars": len(text)}


def run(tickers: list[str]) -> None:
    names = {c["ticker"]: c["name"] for c in load_companies()}
    main = {r["ticker"]: r["pdf"] for r in load_manifest() if r["doc_role"] == "main"}
    for t in tickers:
        try:
            out = extract_company(t, names[t], main[t])
        except LLMError as e:
            print(f"{t:5s} LLM error: {e}")
            continue
        (EXTRACT_DIR / f"{t}.relations.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        kinds = {}
        for r in out["relations"]:
            kinds[r["type"]] = kinds.get(r["type"], 0) + 1
        print(f"{t:5s} chars={out['chars']:5d} kept={len(out['relations']):2d} dropped={len(out['dropped'])} {kinds}", flush=True)
