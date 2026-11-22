"""Baseline for comparison: BM25 over text chunks + LLM answer (the "encode-and-match" pipeline).

Every PDF page is split into ~250-word chunks tagged with company and page. For a question the top-8
chunks by BM25 go to the same LLM, which answers in the same typed JSON and lists the facts it used
(company, value, period end, page). Scored with the same scorer as the graph system.
    python -m kg eval --split test --system bm25
"""
import re
from functools import lru_cache

from rank_bm25 import BM25Okapi

from kg.build.pdftext import page_texts
from kg.config import load_companies, load_manifest
from kg.llm import PLANNER_MODEL, LLMError, chat_json

TOP_K = 8
WORDS = 250


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


@lru_cache(maxsize=1)
def index():
    chunks = []
    names = {c["ticker"]: c["name"] for c in load_companies()}
    for r in load_manifest():
        for i, t in enumerate(page_texts(r["pdf"])):
            w = t.split()
            for s in range(0, max(1, len(w)), WORDS - 50):
                piece = " ".join(w[s:s + WORDS])
                if len(piece) > 80:
                    chunks.append({"ticker": r["ticker"], "doc": r["pdf"], "page": i + 1,
                                   "text": f"[{names[r['ticker']]} ({r['ticker']}) 10-K, {r['pdf']} p.{i + 1}] {piece}"})
    return chunks, BM25Okapi([_tok(c["text"]) for c in chunks])


PROMPT = """Answer the question using ONLY the excerpts from 10-K filings below. Each excerpt starts with its
company, file and page. Values in tables are usually in millions of dollars (check the excerpt).
Return JSON:
{{"kind": "number"|"percent"|"entity"|"list"|"ranking"|"compare"|"none",
  "value": <number in full units (e.g. 303154000000 for $303,154 million), percent as e.g. 32.5,
            a ticker/name for entity, a list of tickers for list/ranking>,
  "unit": "USD"|"USD/share"|"count"|"pct"|null,
  "winner": <ticker, compare only>, "difference": <number in full units, compare only>,
  "facts": [{{"ticker": ..., "value": <number in full units or name>, "period_end": "YYYY-MM-DD" or null, "page": N}}]}}
Use tickers: {tickers}. If the excerpts do not contain the answer, return {{"kind": "none", "facts": []}}.

QUESTION: {q}

EXCERPTS:
{ctx}"""


def bm25_system(q: dict) -> dict:
    chunks, bm = index()
    scores = bm.get_scores(_tok(q["question"]))
    top = sorted(range(len(chunks)), key=lambda i: -scores[i])[:TOP_K]
    ctx = "\n\n".join(chunks[i]["text"][:1700] for i in top)
    tickers = ", ".join(f"{c['ticker']}={c['name']}" for c in load_companies())
    try:
        raw = chat_json([{"role": "user", "content": PROMPT.format(q=q["question"], ctx=ctx, tickers=tickers)}],
                        model=PLANNER_MODEL, max_tokens=1500, tag="bm25", reasoning_effort="medium",
                        allow_fallback=False)   # same model as the graph planner, never a substitute
    except LLMError as e:
        if "quota" in str(e) or "all models failed" in str(e):
            raise   # stop the run; finished questions are cached and resume later
        return {"pred": {"kind": "none"}, "rendered": f"LLM error: {e}", "retrieved": [], "error": str(e)}
    kind = raw.get("kind") or "none"
    pred = {"kind": kind, "value": raw.get("value"), "unit": raw.get("unit"), "winner": raw.get("winner"),
            "difference": raw.get("difference")}
    if kind == "percent":
        pred["unit"] = "pct"
    for k in ("value", "difference"):
        if isinstance(pred.get(k), str):
            try:
                pred[k] = float(pred[k].replace(",", "").replace("$", "").replace("%", ""))
            except ValueError:
                pass
    retrieved = []
    for f in raw.get("facts", []) or []:
        if not isinstance(f, dict):
            continue
        v = f.get("value")
        if isinstance(v, str):
            try:
                v = float(v.replace(",", "").replace("$", ""))
            except ValueError:
                pass
        retrieved.append({"ticker": f.get("ticker"), "value": v, "period_end": f.get("period_end"),
                          "page": f.get("page"), "kind": "value" if isinstance(v, (int, float)) else "relation",
                          "relation": None, "object": v})
    rendered = f"{kind}: {pred.get('winner') or pred.get('value')}" + (f" (diff {pred['difference']})" if pred.get("difference") else "")
    return {"pred": pred, "rendered": rendered, "retrieved": retrieved, "error": None,
            "chunks": [(chunks[i]["ticker"], chunks[i]["page"]) for i in top]}
