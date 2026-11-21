"""Low-level PDF reading with PyMuPDF: words with exact positions, lines, and page text.

We rebuild words from individual characters (rawdict) instead of using PyMuPDF's "words"
mode, because EDGAR HTML indents labels with non-breaking/em spaces. Those spaces would
otherwise be glued to the word and hide the indentation we need for row hierarchy.
"""
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import fitz

from kg.config import PARSED_DIR, PDF_DIR

SPACE_CHARS = set(" \t\n\r            "
                  "​  　﻿")
CHAR_MAP = {"ﬁ": "fi", "ﬂ": "fl", "’": "'", "‘": "'", "“": '"', "”": '"',
            "−": "-", "­": ""}


def clean_text(s: str) -> str:
    for a, b in CHAR_MAP.items():
        s = s.replace(a, b)
    s = "".join(" " if ch in SPACE_CHARS else ch for ch in s)
    return re.sub(r"[ ]+", " ", s).strip()


@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)

    @property
    def y0(self) -> float:
        return min(w.y0 for w in self.words)

    @property
    def y1(self) -> float:
        return max(w.y1 for w in self.words)

    @property
    def yc(self) -> float:
        return sum(w.yc for w in self.words) / len(self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def page_words(page: fitz.Page) -> list[Word]:
    words: list[Word] = []
    raw = page.get_text("rawdict", flags=fitz.TEXT_MEDIABOX_CLIP)
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            cur, box = [], None
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    c = ch["c"]
                    if c in SPACE_CHARS:
                        if cur:
                            words.append(Word(*box, "".join(cur)))
                        cur, box = [], None
                        continue
                    c = CHAR_MAP.get(c, c)
                    if not c:
                        continue
                    x0, y0, x1, y1 = ch["bbox"]
                    if box is None:
                        box = [x0, y0, x1, y1]
                    else:
                        # a big horizontal jump inside one PDF line means a new table cell
                        if x0 - box[2] > 2.5:
                            words.append(Word(*box, "".join(cur)))
                            cur, box = [], [x0, y0, x1, y1]
                        else:
                            box = [min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)]
                    cur.append(c)
            if cur:
                words.append(Word(*box, "".join(cur)))
    return words


def group_lines(words: list[Word], ytol: float = 2.6) -> list[Line]:
    lines: list[Line] = []
    for w in sorted(words, key=lambda w: (round(w.yc, 1), w.x0)):
        if lines and abs(lines[-1].yc - w.yc) <= ytol:
            lines[-1].words.append(w)
        else:
            lines.append(Line([w]))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
    lines.sort(key=lambda ln: ln.yc)
    return lines


@lru_cache(maxsize=8)
def open_pdf(pdf_name: str) -> fitz.Document:
    return fitz.open(PDF_DIR / pdf_name)


def page_texts(pdf_name: str) -> list[str]:
    """Plain text of every page (index 0 = PDF page 1), cached in data/parsed/."""
    cache = PARSED_DIR / f"{Path(pdf_name).stem}.pages.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    doc = open_pdf(pdf_name)
    texts = []
    for page in doc:
        lines = group_lines(page_words(page))
        texts.append("\n".join(ln.text for ln in lines))
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
    return texts
