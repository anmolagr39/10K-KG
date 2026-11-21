"""Line items from every other year-column table (MD&A, notes): the long tail.

Rows here are not mapped to ontology metrics; they keep their printed label plus context
(section header, table header, page heading) and are found at query time with a scoped
label search over ONE company's line items (`find_line_item`), e.g. Amazon "AWS > Net sales".
"""
import re

from kg.build.normalize import norm_label, row_kind
from kg.build.pdftext import open_pdf, page_texts
from kg.build.statements import detect_scales
from kg.build.tables import parse_page


def note_facts(ticker: str, pdf: str, skip_pages: set[int]) -> list[dict]:
    doc = open_pdf(pdf)
    texts = page_texts(pdf)
    out = []
    for pno in range(1, len(texts) + 1):
        if pno in skip_pages or pno <= 2:
            continue
        t = texts[pno - 1]
        if len(re.findall(r"\d{1,3}(?:,\d{3})+|\d+\.\d+", t)) < 6:
            continue
        money, share_scale, scale_text = detect_scales(t)
        heading = " / ".join(ln for ln in t.split("\n")[:3] if not re.match(r"table of contents", ln, re.I))[:160]
        for table in parse_page(doc[pno - 1], pno):
            local_money = money
            m = re.search(r"\b(?:in|\$ in|dollars in)\s+(millions|thousands|billions)\b", table.header_text, re.I)
            if m:
                local_money = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}[m.group(1).lower()]
            for k, r in enumerate(table.rows):
                if not r.values or not r.label or len(r.label) > 140:
                    continue
                kind = row_kind(norm_label(r.label), norm_label(r.section))
                if any(abs(v - round(v)) > 1e-9 for v in r.values.values()) and kind == "monetary":
                    kind = "decimal"
                if re.search(r"percent|%|growth|mix\b|margin|ratio|\brate\b|basis points|bps", r.label + " " + r.section, re.I) \
                        and all(abs(v) < 1000 for v in r.values.values()):
                    kind = "decimal"   # "Year-over-year Percentage Growth: 20" is 20%, not $20 million
                for ci, raw in r.values.items():
                    col = table.columns[ci]
                    if ci in r.pct or kind == "decimal":
                        value, unit, scale = raw, ("pct" if ci in r.pct else "number"), 1.0
                    elif kind == "per_share":
                        value, unit, scale = raw, "USD/share", 1.0
                    elif kind == "shares":
                        value, unit, scale = raw * (share_scale or 1), "shares", share_scale or 1.0
                    elif local_money:
                        value, unit, scale = raw * local_money, "USD", local_money
                    else:
                        value, unit, scale = raw, "number", 1.0
                    out.append({
                        "ticker": ticker, "doc": pdf, "page": pno, "statement": "note",
                        "label": r.label, "section": r.section, "row_idx": k, "metric": None,
                        "value": value, "raw_value": raw, "scale": scale, "unit": unit,
                        "col_year": col.year, "end_date": col.end_date, "col_index": ci,
                        "period_type": "unknown", "row_text": r.text, "bbox": list(r.bbox),
                        "context": (heading + " | " + table.header_text[:200]).strip(),
                        "method": "table", "confidence": 0.7 if local_money or unit != "USD" else 0.4,
                    })
    return out
