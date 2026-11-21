"""Find the primary financial statements in a 10-K PDF and turn their rows into fact records.

A page counts as, e.g., the income statement only if
  * a statement title appears near the top ("CONSOLIDATED STATEMENTS OF OPERATIONS"), and
  * the page has year columns and many numbers, and
  * key rows are present ("per share" + "net income" for the income statement).
That skips the table of contents and MD&A pages that merely mention the statement.
"""
import re

from kg.build.normalize import candidate_metric, choose_rows, norm_label, row_kind
from kg.build.pdftext import open_pdf, page_texts
from kg.build.tables import parse_page

TITLE = {
    "IS": re.compile(r"(consolidated\s+)?(statements?\s+of\s+(consolidated\s+)?(operations|income|earnings)(?!\s+data)"
                     r"(\s*\(loss\))?(\s+and\s+comprehensive\s+(income|loss))?|(income|earnings)\s+statements?)\b(?!\s*data)", re.I),
    "BS": re.compile(r"(balance\s+sheets?|statements?\s+of\s+(financial\s+(position|condition)|condition))\b", re.I),
    "CF": re.compile(r"(statements?\s+of\s+cash\s+flows?|cash\s+flows?\s+statements?)", re.I),
}
MUST = {
    "IS": [re.compile(r"per (common )?share|per diluted share|per share", re.I), re.compile(r"net (income|earnings|loss)", re.I)],
    "BS": [re.compile(r"total (current )?assets", re.I), re.compile(r"liabilities", re.I)],
    "CF": [re.compile(r"operat", re.I), re.compile(r"investing", re.I)],
}
EXCLUDE = re.compile(r"parent company|condensed|registrant|guarantor|\(parent|parent only|quarterly|"
                     r"unaudited|segment|comprehensive income\s*$|changes in (stockholders|shareholders|equity)", re.I)
# MD&A summary tables that carry a statement-like title
SUMMARY = re.compile(r"\btable \d+|selected|summary|overview|highlights|percentage relationship|results of operations", re.I)
ANY_TITLE = re.compile("|".join(p.pattern for p in TITLE.values()) + r"|statements? of (changes in )?(stockholders|shareholders)|comprehensive income", re.I)
MONEY_SCALE = re.compile(r"\b(?:in|\$ in|dollars in|amounts in)\s+(millions|thousands|billions)\b|"
                         r"\((millions|thousands|billions)\b|\b(millions|thousands|billions) of dollars|"
                         r"\b(millions|thousands|billions),?\s+except", re.I)
SHARE_SCALE = re.compile(r"shares?[^.;)]{0,70}?\b(?:in|reflected in|are in)\s+(thousands|millions)|"
                         r"(thousands|millions) of shares", re.I)
SCALES = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}


def _nums(t: str) -> int:
    return len(re.findall(r"\d{1,3}(?:,\d{3})+", t))


def _top(t: str, n: int) -> str:
    return "\n".join(t.split("\n")[:n])


def find_statement_pages(pdf: str, with_scores: bool = False) -> dict:
    """Score every page that could hold each primary statement and keep the best one.

    Handles three real layouts: title and table on one page; title alone on a page with the
    table on the next page (Chrome page breaks: Meta, Visa, IBM, Goldman); and MD&A summary
    tables that reuse a statement title (penalised: "Table 6 Selected...", % columns).
    """
    texts = page_texts(pdf)
    found: dict[str, list[int]] = {}
    for st in ("IS", "BS", "CF"):
        cands = []   # (score, page)
        for i, t in enumerate(texts):
            lines = t.split("\n")
            top = "\n".join(lines[:12])
            # the title must look like a heading: a short line, or the title near the line start
            heading = [ln for ln in lines[:12]
                       if (mm := TITLE[st].search(ln)) and (len(ln.split()) <= 12 or mm.start() < 15)]
            if not heading:
                continue
            if st == "IS" and re.search(r"comprehensive income", top, re.I) and not re.search(
                    r"(operations|earnings|income)\s+and\s+comprehensive", top, re.I) and \
                    not re.search(r"statements?\s+of\s+(consolidated\s+)?(operations|income|earnings)\b(?!\s+and)|income statements?\b", top, re.I):
                continue
            if EXCLUDE.search(top):
                continue
            page_i, body = i, t
            if _nums(t) < 10 and i + 1 < len(texts):
                # title-only page: the table is on the next page (unless that page has its own title)
                nxt = texts[i + 1]
                if ANY_TITLE.search("\n".join(nxt.split("\n")[:4])):
                    continue
                page_i, body = i + 1, nxt
            two_pages = False
            if st == "BS" and not all(p.search(body) for p in MUST[st]) and page_i + 1 < len(texts):
                # balance sheet split over two pages (Citi: assets, then "(Continued)" liabilities)
                nxt = texts[page_i + 1]
                if TITLE[st].search("\n".join(nxt.split("\n")[:4])) or "continued" in nxt[:300].lower():
                    two_pages = all(p.search(body + nxt) for p in MUST[st])
            if not (two_pages or all(p.search(body) for p in MUST[st])) or _nums(body) < 15:
                continue
            score = 0.0
            title_line = next((k for k, ln in enumerate(lines[:12]) if TITLE[st].search(ln)), 12)
            score += 2 if title_line <= 4 else 0
            score += 2 if re.search(r"consolidated", lines[title_line] if title_line < len(lines) else "", re.I) else 0
            score += 3 if re.search(r"accompanying notes|integral part", body + (texts[page_i + 1] if page_i + 1 < len(texts) else "")[:400], re.I) else 0
            score -= 4 if SUMMARY.search(top) else 0
            score -= min(body.count("%"), 30) / 5
            score += page_i / 1000   # tie-break: audited statements come after MD&A
            cands.append((score, page_i + 1, two_pages))
        if cands:
            _, best, two = max(cands)
            pages = [best] + ([best + 1] if two else [])
            # "(Continued)" pages: the statement started on the page before, or goes on after
            if "continued" in texts[best - 1][:300].lower() and best >= 2 and \
                    TITLE[st].search(_top(texts[best - 2], 8)) and _nums(texts[best - 2]) >= 15:
                pages = [best - 1] + pages
            last = pages[-1]
            if last < len(texts):
                t2 = texts[last]
                cont = "continued" in t2[:300].lower() and TITLE[st].search(_top(t2, 6))
                # same title again and the statement so far is incomplete (Capital One, Citi)
                so_far = "\n".join(texts[p - 1] for p in pages)
                incomplete = (st == "IS" and not re.search(r"dilut", so_far, re.I)
                              or st == "CF" and not re.search(r"net cash.{0,40}financing|financing activities.{0,40}\d", so_far, re.I)
                              or st == "BS" and not re.search(r"total liabilities", so_far, re.I))
                cont = cont or (incomplete and TITLE[st].search(_top(t2, 6)) and _nums(t2) >= 10)
                tail = not ANY_TITLE.search(_top(t2, 6)) and _nums(t2) >= 15 and (
                    st == "CF" and re.search(r"financing", t2, re.I) and not re.search(r"financing", texts[last - 1], re.I)
                    or st == "BS" and re.search(r"total liabilities", t2, re.I) and not re.search(r"total liabilities", texts[last - 1], re.I))
                if cont or tail:
                    pages.append(last + 1)
            found[st] = (pages, max(cands)[0]) if with_scores else pages
    return found


def detect_scales(text: str) -> tuple[float | None, float | None, str]:
    top = "\n".join(text.split("\n")[:25])
    m = MONEY_SCALE.search(top)
    money = SCALES[next(g for g in m.groups() if g).lower()] if m else None
    s = SHARE_SCALE.search(top)
    shares = SCALES[next(g for g in s.groups() if g).lower()] if s else money
    return money, shares, (m.group(0) if m else "")


def statement_facts(ticker: str, pdf: str, st: str, pages: list[int]) -> list[dict]:
    """All rows of all tables on the statement's pages -> fact records (one per row x column)."""
    doc = open_pdf(pdf)
    texts = page_texts(pdf)
    items = []   # (page, table, row, scales)
    for pno in pages:
        money, share_scale, scale_text = detect_scales(texts[pno - 1])
        if money is None and pno > 1:
            money, share_scale, scale_text = detect_scales(texts[pno - 2])
        for table in parse_page(doc[pno - 1], pno):
            valued = [k for k, r in enumerate(table.rows) if r.values]
            first_liab = next((k for k, r in enumerate(table.rows) if "liabilit" in r.label.lower()), None)
            for idx, r in enumerate(table.rows):
                if not r.values:
                    continue
                if not r.label and st == "BS":
                    # unlabeled total rows (Merck): the last valued row before the liabilities block is
                    # total assets; the last row of the statement is total liabilities and equity
                    before = [k for k in valued if first_liab is not None and k < first_liab]
                    if before and idx == before[-1]:
                        r.label = "Total assets"
                    elif idx == valued[-1]:
                        r.label = "Total liabilities and equity"
                    if r.label:
                        r.section = (r.section + " [unlabeled row; label inferred]").strip()
                if not r.label:
                    continue
                items.append((pno, table, r, (money, share_scale, scale_text)))
    rows = []
    for k, (pno, table, r, (money, _, _)) in enumerate(items):
        kind = row_kind(norm_label(r.label), norm_label(r.section))
        # a decimal value on a "$ in millions" statement is a per-share amount (Citi "Net income $ 7.11")
        if kind == "monetary" and (money or 1) >= 1e3 and any(abs(v - round(v)) > 1e-9 for v in r.values.values()):
            kind = "per_share"
        rows.append({"idx": k, "label": r.label, "section": r.section, "kind": kind,
                     "metric": candidate_metric(st, r.label, r.section, kind)})
    chosen = choose_rows(st, rows)
    chosen_idx = {v: m for m, v in chosen.items()}
    out: list[dict] = []
    for rr in rows:
        pno, table, r, (money, share_scale, scale_text) = items[rr["idx"]]
        kind, mid = rr["kind"], chosen_idx.get(rr["idx"])
        for ci, raw in r.values.items():
            if ci in r.pct:
                continue
            col = table.columns[ci]
            if kind == "per_share":
                scale, unit = 1.0, "USD/share"
            elif kind == "shares":
                scale, unit = share_scale or 1.0, "shares"
            else:
                scale, unit = money or 1.0, "USD"
            value = raw * scale
            if mid in ("capex", "dividends_paid", "share_repurchases"):
                value = abs(value)
            out.append({
                "ticker": ticker, "doc": pdf, "page": pno, "statement": st,
                "label": r.label, "section": r.section, "row_idx": rr["idx"],
                "metric": mid, "candidate_metric": rr["metric"],
                "value": value, "raw_value": raw, "scale": scale, "unit": unit,
                "col_year": col.year, "end_date": col.end_date, "col_index": ci,
                "period_type": "instant" if st == "BS" else "duration",
                "row_text": r.text, "bbox": list(r.bbox), "scale_text": scale_text,
                "method": "table", "confidence": 0.95 if money else 0.6,
            })
    return out
