"""Helpers used to WRITE and VERIFY the benchmark (not part of the question-answering system).

* grep(ticker, regex)        -> matching lines with document + page, to read a fact in place
* find_number(ticker, "478,834") -> pages where a printed number appears
* xbrl(ticker, concept)      -> the value SEC's XBRL data has for this filing (cross-check only)

Gold answers are taken from the PDF pages (read by a person); XBRL only confirms the numbers.
"""
import json
import re

from kg.build.pdftext import page_texts
from kg.config import XBRL_DIR, load_manifest


def docs(ticker: str) -> list[str]:
    return [r["pdf"] for r in load_manifest() if r["ticker"] == ticker]


def grep(ticker: str, pattern: str, flags=re.I, limit: int = 30, context: int = 0) -> list[tuple[str, int, str]]:
    out = []
    for pdf in docs(ticker):
        for i, t in enumerate(page_texts(pdf)):
            lines = t.split("\n")
            for j, ln in enumerate(lines):
                if re.search(pattern, ln, flags):
                    snippet = " / ".join(lines[max(0, j - context):j + context + 1])
                    out.append((pdf, i + 1, snippet))
                    if len(out) >= limit:
                        return out
    return out


def find_number(ticker: str, printed: str, limit: int = 20) -> list[tuple[str, int, str]]:
    pat = r"(?<![\d,.])" + re.escape(printed) + r"(?![\d,]|\.\d)"
    return grep(ticker, pat, flags=0, limit=limit)


def page_has(pdf: str, page: int, printed: str) -> bool:
    t = page_texts(pdf)[page - 1]
    flat = re.sub(r"\s+", " ", t)
    pat = r"(?<![\d,.])" + re.escape(printed) + r"(?![\d,]|\.\d)"
    return re.search(pat, flat) is not None or printed.lower() in flat.lower()


def xbrl(ticker: str, concept: str) -> list[dict]:
    d = json.loads((XBRL_DIR / f"{ticker}.json").read_text(encoding="utf-8"))
    out = []
    for key, units in d["facts"].items():
        if key.split(":")[1] != concept and key != concept:
            continue
        for unit, rows in units.items():
            for r in rows:
                out.append({"concept": key, "unit": unit, "val": r["val"], "start": r.get("start"),
                            "end": r["end"], "fy": r.get("fy"), "fp": r.get("fp"), "frame": r.get("frame")})
    return out
