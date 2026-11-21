"""Position-based table parser for 10-K PDFs.

Turns one PDF page into tables of rows. A row is a label plus one value per column,
and each column is tied to a period taken from the header (a year and, when printed, a date).

How it works (see the walkthrough on Apple's income statement in the README):
  1. words -> lines by y position (pdftext.group_lines)
  2. header lines = lines holding >= 2 year tokens ("2026 2025 2024" or "September 26, 2026 ...")
  3. columns = clusters of the RIGHT edges of numbers below a header (numbers are right-aligned)
  4. each column is matched to a header year (and month/day if printed)
  5. each line: numbers aligned with a column are values; the rest of the line is the label
     "(1,234)" -> -1234, "-" / "—" -> 0, "$" ignored, footnote markers stay in the label
  6. lines without numbers are section headers ("Operating expenses:") or the first half of a
     label that wraps onto the next line.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from kg.build.pdftext import Line, Word, group_lines, page_words

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
NUM_RE = re.compile(r"^\(?-?\$?\(?((?:\d{1,3}(?:,\d{3})+)|\d+)(\.\d+)?\)?%?\)?$")
DASH_RE = re.compile(r"^[—–\-]{1,3}\)?$")
YEAR_RE = re.compile(r"^\(?(?:FY|Fiscal|fiscal)?'?((?:19|20)\d{2})[,)*]?$")


def parse_number(tok: str) -> float | None:
    t = tok.strip()
    if DASH_RE.match(t):
        return 0.0
    m = NUM_RE.match(t)
    if not m:
        return None
    v = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
    if t.startswith("(") or t.startswith("-") or t.startswith("$(") or t.endswith(")") and "(" in t:
        v = -v
    return v


def is_year(tok: str) -> int | None:
    m = YEAR_RE.match(tok)
    if m:
        y = int(m.group(1))
        if 1990 <= y <= 2035:
            return y
    return None


@dataclass
class Column:
    x1: float                 # right edge of the numbers in this column
    year: int | None = None
    end_date: str | None = None   # ISO date if month/day printed in the header
    header: str = ""


@dataclass
class Row:
    label: str
    indent: float
    y0: float
    y1: float
    values: dict[int, float] = field(default_factory=dict)   # column index -> value
    pct: set = field(default_factory=set)                    # column indexes holding a % value
    text: str = ""            # full printed line
    section: str = ""         # nearest section header above ("Operating expenses:")
    is_header: bool = False
    bbox: tuple = ()


@dataclass
class Table:
    page: int                 # 1-based PDF page
    columns: list[Column]
    rows: list[Row]
    header_text: str = ""
    y0: float = 0.0
    y1: float = 0.0


def _year_tokens(line: Line) -> list[tuple[int, Word]]:
    out = []
    for w in line.words:
        y = is_year(w.text)
        if y:
            out.append((y, w))
    return out


HEADER_WORDS = re.compile(r"^(fiscal|years?|ended|ending|weeks?|months?|as|of|at|and|for|the|in|millions?|"
                          r"thousands?|dollars|except|per|share|amounts?|data|\(|\)|-|–|—|\$|%|change|"
                          r"january|february|march|april|may|june|july|august|september|october|november|december)[,.:)]*$", re.I)


def _is_header_line(line: Line) -> bool:
    """A column header: >= 2 years and little else (not a sentence that mentions years)."""
    yrs = _year_tokens(line)
    if len(yrs) < 2:
        return False
    other_nums = [w for w in line.words if parse_number(w.text) is not None and not is_year(w.text)
                  and not re.match(r"^\d{1,2},?$", w.text)]
    if other_nums:
        return False
    prose = [w for w in line.words if not is_year(w.text) and not re.match(r"^\d{1,2},?$", w.text)
             and not HEADER_WORDS.match(w.text)]
    return len(prose) <= 6


def _month_days(lines: list[Line]) -> list[tuple[int, int, float, int | None]]:
    """(month, day, x_center, year_or_None) phrases found in header lines."""
    out = []
    for ln in lines:
        ws = ln.words
        for i, w in enumerate(ws):
            mo = MONTHS.get(w.text.lower().strip(",."))
            if not mo or i + 1 >= len(ws):
                continue
            dm = re.match(r"^(\d{1,2}),?$", ws[i + 1].text)
            if not dm:
                continue
            yr, x_end = None, ws[i + 1].x1
            if i + 2 < len(ws) and is_year(ws[i + 2].text) and ws[i + 2].x0 - ws[i + 1].x1 < 8:
                yr, x_end = is_year(ws[i + 2].text), ws[i + 2].x1
            out.append((mo, int(dm.group(1)), (w.x0 + x_end) / 2, yr))
    return out


def _cluster(xs: list[float], tol: float = 7.0) -> list[list[float]]:
    groups: list[list[float]] = []
    for x in sorted(xs):
        if groups and x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return groups


def _safe_date(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _value_tokens(line: Line) -> list[tuple[Word, float, bool]]:
    """Numeric tokens of a line with their value and a percent flag."""
    out = []
    ws = line.words
    for i, w in enumerate(ws):
        v = parse_number(w.text)
        if v is None:
            continue
        pct = w.text.endswith("%") or (i + 1 < len(ws) and ws[i + 1].text.startswith("%")
                                       and ws[i + 1].x0 - w.x1 < 6)
        # "(1,234" followed by ")" in its own cell is still negative (handled by leading "(")
        out.append((w, v, pct))
    return out


def parse_page(page, page_no: int) -> list[Table]:
    """Find all year-column tables on a page."""
    lines = group_lines(page_words(page))
    if not lines:
        return []
    header_idx = [i for i, ln in enumerate(lines) if _is_header_line(ln)]
    tables: list[Table] = []
    for k, hi in enumerate(header_idx):
        # header lines can be consecutive ("2026 2025 2024" repeated as "Fiscal 2026 ..."): merge
        if k > 0 and hi == header_idx[k - 1] + 1:
            continue
        end = header_idx[k + 1] if k + 1 < len(header_idx) else len(lines)
        # skip a following header line that is directly attached (multi-line headers)
        j = k + 1
        while j < len(header_idx) and header_idx[j] == header_idx[j - 1] + 1:
            j += 1
        end = header_idx[j] if j < len(header_idx) else len(lines)
        head_last = header_idx[j - 1]
        body = lines[head_last + 1:end]
        # header context: up to 6 lines above the year line(s), not crossing the previous table
        prev_end = tables[-1].rows[-1].y1 if tables and tables[-1].rows else 0
        ctx = [ln for ln in lines[max(0, hi - 6):head_last + 1] if ln.y0 >= prev_end - 1]
        t = _build_table(page_no, lines[hi:head_last + 1], ctx, body)
        if t:
            tables.append(t)
    return tables


def _build_table(page_no: int, year_lines: list[Line], ctx: list[Line], body: list[Line]) -> Table | None:
    years = [yw for ln in year_lines for yw in _year_tokens(ln)]
    # keep the first header line that has the most year tokens
    best = max(year_lines, key=lambda ln: len(_year_tokens(ln)))
    anchors = sorted(_year_tokens(best), key=lambda t: t[1].x0)
    # numeric right edges in the body (ignore % columns and tokens in the left 30% of the page)
    xs = []
    for ln in body:
        for w, v, pct in _value_tokens(ln):
            if not pct and w.x0 > 180:
                xs.append(w.x1 if not w.text.endswith(")") or w.text.startswith("(") else w.x1)
    groups = [g for g in _cluster(xs) if len(g) >= 2]
    if not groups or not anchors:
        return None
    if len(groups) > len(anchors):
        # drop "% of sales" columns (Lowe's): every token a small number with decimals
        def small_decimals(g):
            toks = [w for ln in body for w, v, pct in _value_tokens(ln)
                    if any(abs(w.x1 - x) < 0.01 for x in g)]
            return toks and all("." in w.text and abs(parse_number(w.text) or 0) <= 100 for w in toks)
        groups = [g for g in groups if not small_decimals(g)]
    cols = [Column(x1=max(g)) for g in groups]
    # tie columns to header years
    if len(cols) == len(anchors):
        for c, (y, w) in zip(cols, anchors):
            c.year, c.header = y, w.text
    else:
        for c in cols:
            y, w = min(anchors, key=lambda a: abs(a[1].xc - (c.x1 - 22)))
            if abs(w.xc - (c.x1 - 22)) < 60:
                c.year, c.header = y, w.text
    cols = [c for c in cols if c.year]
    if not cols:
        return None
    # month/day from header context
    md = _month_days(ctx)
    for i, c in enumerate(cols):
        hit = None
        dated = [m for m in md if m[3] == c.year]
        if dated:
            hit = min(dated, key=lambda m: abs(m[2] - (c.x1 - 22)))
        elif len(md) == len(cols):
            hit = md[i]
        elif md:
            hit = min(md, key=lambda m: abs(m[2] - (c.x1 - 22)))
        if hit:
            c.end_date = _safe_date(c.year, hit[0], hit[1])
    header_text = " | ".join(ln.text for ln in ctx)
    rows = _rows(body, cols)
    if not any(r.values for r in rows):
        return None
    return Table(page=page_no, columns=cols, rows=rows, header_text=header_text,
                 y0=min(ln.y0 for ln in ctx + body), y1=max(ln.y1 for ln in ctx + body))


def _rows(body: list[Line], cols: list[Column]) -> list[Row]:
    first_col_left = min(c.x1 for c in cols) - 75
    rows: list[Row] = []
    for ln in body:
        values, pct, label_words = {}, set(), []
        for w in ln.words:
            v = parse_number(w.text)
            is_pct = w.text.endswith("%")
            ci = None
            if v is not None or DASH_RE.match(w.text):
                best = min(range(len(cols)), key=lambda i: abs(cols[i].x1 - w.x1))
                tol = 10 if v is not None and not DASH_RE.match(w.text) else 40
                if abs(cols[best].x1 - w.x1) <= tol or (w.text.endswith(")") and abs(cols[best].x1 - w.x1) <= 14):
                    ci = best
            if ci is not None and w.x0 > first_col_left - 40:
                if ci not in values:
                    values[ci] = parse_number(w.text) if v is not None else 0.0
                    if is_pct:
                        pct.add(ci)
                continue
            if w.text in ("$", ")", "%", "(", "$(") or (w.x0 > first_col_left and w.text in ("%)",)):
                continue
            if w.x0 > first_col_left and v is not None:
                continue   # stray number between columns (e.g. a % change column)
            label_words.append(w)
        label = " ".join(w.text for w in label_words).strip()
        indent = label_words[0].x0 if label_words else ln.x0
        rows.append(Row(label=label, indent=indent, y0=ln.y0, y1=ln.y1, values=values, pct=pct,
                        text=ln.text, is_header=not values,
                        bbox=(round(ln.x0, 1), round(ln.y0, 1), round(max(w.x1 for w in ln.words), 1),
                              round(ln.y1, 1))))
    return _merge_wrapped(rows)


def _merge_wrapped(rows: list[Row]) -> list[Row]:
    """Join labels that wrap onto a second line and assign section headers."""
    out: list[Row] = []
    for r in rows:
        prev = out[-1] if out else None
        if (prev and prev.is_header and not r.is_header and not r.label and prev.label
                and r.y0 - prev.y1 < 6):
            # label top-aligned, numbers bottom-aligned on their own line (NVIDIA cash flows)
            out.pop()
            r.label, r.indent, r.text, r.y0 = prev.label, prev.indent, prev.text + " " + r.text, prev.y0
        elif (prev and prev.is_header and not r.is_header and r.label and prev.label
                and not prev.label.rstrip().endswith(":")
                and r.y0 - prev.y1 < 4
                and (r.label[0].islower() or prev.label.rstrip().endswith(
                    (",", " and", " of", "-", " for", " to", " from", " in", " on", " the", " by", " or", " net")))):
            # a label that wraps onto a second line ("...noncontrolling interests and" / "redeemable ...")
            out.pop()
            r.label = prev.label + " " + r.label
            r.indent = prev.indent
            r.text = prev.text + " " + r.text
            r.y0 = prev.y0
        out.append(r)
    # section headers: a header applies to the rows below it. When its children are indented,
    # the first later row back at (or left of) the header's indent closes the section; with a
    # flat layout the section closes after its "Total ..." row.
    stack: list[list] = []   # [header_row, saw_deeper_child]
    for r in out:
        if r.is_header and r.label:
            while stack and stack[-1][0].indent >= r.indent - 1:
                stack.pop()
            stack.append([r, False])
            continue
        while stack:
            h, deeper = stack[-1]
            if r.indent > h.indent + 1.5:
                stack[-1][1] = True
                break
            if deeper and not r.label.lower().startswith("total"):
                stack.pop()
                continue
            break
        r.section = " > ".join(h.label for h, _ in stack)
        if stack and r.label.lower().startswith("total") and r.indent <= stack[-1][0].indent + 1.5 + 40:
            # "Total net sales" closes "Net sales:" (its total row may be indented deeper)
            hl = stack[-1][0].label.lower().rstrip(":").strip()
            if hl and (hl in r.label.lower() or not stack[-1][1]):
                stack.pop()
    return out
