"""Regex/position extraction for facts that live in fixed-format parts of a 10-K.

* cover page (fixed SEC form): legal name, state of incorporation, HQ address, ticker/exchange,
  fiscal year end, shares outstanding (+ as-of date), public float
* auditor's report (required wording): firm, city, "served as auditor since YYYY"
* human capital: "approximately N employees"
* signatures page: CEO (Principal Executive Officer) and CFO (Principal Financial Officer)

Every record carries the page and the exact text it came from.
"""
import re
from datetime import datetime

from kg.build.pdftext import group_lines, open_pdf, page_texts, page_words

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE = rf"{MONTH}\s+\d{{1,2}},?\s+\d{{4}}"
STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
          "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
          "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
          "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico",
          "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
          "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
          "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia"]
STATE_ABBR = {"CA": "California", "NY": "New York", "WA": "Washington", "TX": "Texas", "NJ": "New Jersey",
              "IL": "Illinois", "MN": "Minnesota", "GA": "Georgia", "NC": "North Carolina", "VA": "Virginia",
              "IN": "Indiana", "DE": "Delaware", "MA": "Massachusetts", "PA": "Pennsylvania", "AR": "Arkansas",
              "MD": "Maryland", "OH": "Ohio", "FL": "Florida", "CT": "Connecticut", "MO": "Missouri"}
EXCHANGES = [("Nasdaq", r"nasdaq"), ("New York Stock Exchange", r"new york stock exchange|\bnyse\b")]
NUMWORD = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}


def iso(d: str) -> str | None:
    d = re.sub(r"\s+", " ", d.replace(",", ", ")).replace(" ,", ",").replace(",,", ",")
    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(re.sub(r",\s*", ", ", d).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _rec(ticker, pdf, page, metric, value, unit, quote, **kw):
    r = {"ticker": ticker, "doc": pdf, "page": page, "metric": metric, "value": value, "unit": unit,
         "quote": re.sub(r"\s+", " ", quote).strip()[:400], "method": "regex", "statement": kw.pop("statement", "cover")}
    r.update(kw)
    return r


def _value_above(lines, label_regex, stop_regex=None):
    """Text on the line just above a form label, restricted to the label's x-range."""
    for i, ln in enumerate(lines):
        txt = ln.text
        m = re.search(label_regex, txt, re.I)
        if not m:
            continue
        # x-range of the label = from the first word of the match to the next "(" label on the line
        start_word = next((w for w in ln.words if label_regex.split("\\")[0][:3].lower() in w.text.lower()
                           or w.text.startswith("(")), ln.words[0])
        lab_words = [w for w in ln.words]
        # locate words belonging to the matched label
        pos, acc = 0, []
        for w in lab_words:
            s = txt.find(w.text, pos)
            if m.start() <= s < m.end() + 1:
                acc.append(w)
            pos = s + len(w.text)
        if not acc:
            continue
        x0 = acc[0].x0 - 25
        nxt = [w for w in ln.words if w.x0 > acc[-1].x1 + 5 and w.text.startswith("(")]
        x1 = (nxt[0].x0 - 5) if nxt else acc[-1].x1 + 60
        for j in range(i - 1, max(-1, i - 4), -1):
            ws = [w for w in lines[j].words if w.xc >= x0 and w.xc <= x1]
            if ws and lines[j].y1 < ln.y0 + 1:
                return " ".join(w.text for w in ws), lines[j]
    return None, None


def cover_facts(ticker: str, pdf: str, tickers_all: set[str]) -> list[dict]:
    texts = page_texts(pdf)
    doc = open_pdf(pdf)
    out = []
    # the cover page is page 1 (sometimes spilling onto page 2)
    for pno in (1, 2):
        lines = group_lines(page_words(doc[pno - 1]))
        text = texts[pno - 1]
        flat = re.sub(r"\s+", " ", text)
        if pno == 1:
            m = re.search(rf"fiscal year ended:?\s*({DATE})", flat, re.I)
            if m:
                out.append(_rec(ticker, pdf, pno, "fiscal_year_end", iso(m.group(1)), "date", m.group(0)))
            name, _ = _value_above(lines, r"\(Exact name of registrant")
            if name:
                out.append(_rec(ticker, pdf, pno, "legal_name", name, "text", name + " (Exact name of registrant as specified in its charter)"))
            st, _ = _value_above(lines, r"\(State or other jurisdiction|\(State of incorporation|\(State or Other Jurisdiction")
            if st:
                state = next((s for s in STATES if s.lower() in st.lower()), None)
                if state:
                    out.append(_rec(ticker, pdf, pno, "state_of_incorporation", state, "text",
                                    st + " (State or other jurisdiction of incorporation or organization)"))
            addr, _ = _value_above(lines, r"\(Address of principal executive offices|\(Address of Principal Executive Offices|\(Address, including zip code")
            if addr:
                state = next((s for s in sorted(STATES, key=len, reverse=True) if s.lower() in addr.lower()), None)
                if not state:
                    ab = re.search(r"\b([A-Z]{2})\s+\d{5}", addr)
                    state = STATE_ABBR.get(ab.group(1)) if ab else None
                city = None
                if state:
                    cm = re.search(r"([A-Z][A-Za-z.' ]+?),?\s+" + (re.escape(state) if state.lower() in addr.lower() else r"[A-Z]{2}\b"), addr)
                    if cm:
                        city = re.sub(r"^(?:\d+\s+)?(?:[A-Z][a-z]+\s+)*(Way|Drive|Street|Avenue|Road|Parkway|Plaza|Boulevard|Square|Place|Lane|Center|Park)\s+", "", cm.group(1)).strip(" ,")
                        city = city.split(",")[-1].strip()
                out.append(_rec(ticker, pdf, pno, "hq_location", f"{city}, {state}" if city and state else addr,
                                "text", addr + " (Address of principal executive offices)", address=addr,
                                hq_city=city, hq_state=state))
            # ticker / exchange row: the line that holds this company's ticker symbol
            for ln in lines:
                toks = [w.text.strip(",") for w in ln.words]
                if ticker in toks or (ticker == "GOOGL" and "GOOG" in toks):
                    exch = next((nm for nm, pat in EXCHANGES if re.search(pat, ln.text, re.I)), None)
                    if exch:
                        out.append(_rec(ticker, pdf, pno, "exchange", exch, "text", ln.text))
                        break
        # shares outstanding (may be on page 1 or 2)
        if not any(r["metric"] == "shares_outstanding" for r in out):
            out += _shares_outstanding(ticker, pdf, pno, flat)
        if not any(r["metric"] == "public_float" for r in out):
            m = re.search(r"aggregate market value[^.]{0,400}?(?:was|of|approximately)\s+(?:approximately\s+)?\$\s?([\d,.]+)\s*(trillion|billion|million)?", flat, re.I)
            if m:
                v = float(m.group(1).replace(",", "").rstrip("."))
                v *= NUMWORD.get((m.group(2) or "").lower(), 1)
                dm = re.search(rf"({DATE})", m.group(0))
                out.append(_rec(ticker, pdf, pno, "public_float", v, "USD", m.group(0),
                                as_of=iso(dm.group(1)) if dm else None))
    return out


def _shares_outstanding(ticker, pdf, pno, flat) -> list[dict]:
    out = []
    # e.g. "14,840,390,000 shares of common stock were issued and outstanding as of October 17, 2025"
    #      "As of July 24, 2025, there were 7,433,166,379 shares of common stock outstanding"
    pats = [
        rf"([\d,]{{7,}})\s+shares\s+of\s+(?:the\s+registrant'?s?\s+)?(?:its\s+)?(class\s+\w+\s+)?common stock[^.]{{0,80}}?outstanding[^.]{{0,40}}?(?:as of|at)\s+({DATE})",
        rf"(?:as of|at)\s+({DATE})[^.]{{0,120}}?([\d,]{{7,}})\s+shares",
        rf"outstanding[^.]{{0,120}}?(?:as of|at)\s+({DATE})[^.]{{0,40}}?(?:was|were|:)\s*([\d,]{{7,}})",
        rf"([\d,]{{7,}})\s+shares[^.]{{0,160}}?outstanding[^.]{{0,40}}?(?:as of|at)\s+({DATE})",
    ]
    for k, pat in enumerate(pats):
        for m in re.finditer(pat, flat, re.I):
            g = m.groups()
            if k == 0:
                n, d = g[0], g[2]
            elif k in (1, 2):
                d, n = g[0], g[1]
            else:
                n, d = g[0], g[1]
            v = float(n.replace(",", ""))
            if v < 1e6:
                continue
            out.append(_rec(ticker, pdf, pno, "shares_outstanding", v, "shares", m.group(0), as_of=iso(d)))
        if out:
            break
    # multi-class companies list several classes: keep each, flag the class in the quote
    return out


FIRM = r"([A-Z][A-Za-z.']+(?:\s(?:&\s)?[A-Z][A-Za-z.']+){0,3}\s?LLP)"
REPORT_TITLE = re.compile(r"report of independent registered public accounting firm", re.I)


def _flat(t: str) -> str:
    return re.sub(r"\s+", " ", t)


def auditor_facts(ticker: str, pdf: str) -> list[dict]:
    """Auditor firm, city and tenure from the audit report, with fallbacks for image signatures.

    1. "/s/ Ernst & Young LLP" on the report pages (title page + 4 pages; reports span pages)
    2. a line naming the firm on those pages (letterhead "PricewaterhouseCoopers LLP • 300 Madison ...")
    3. anywhere in the filing: "audited by X LLP", "X LLP, an independent registered public
       accounting firm", Item 14 "Our independent registered public accounting firm is X LLP"
    """
    texts = page_texts(pdf)
    flats = [_flat(t) for t in texts]
    out: list[dict] = []
    report_pages = [i for i, f in enumerate(flats) if REPORT_TITLE.search(f)
                    and not (re.search(r"table of contents|^\s*index", f[:300], re.I) and f.count("Item") > 5)]
    firm = None
    for i in report_pages:
        for j in range(i, min(i + 5, len(texts))):
            m = re.search(r"/s/\s*" + FIRM, flats[j])
            if m:
                firm = (re.sub(r"\s+", " ", m.group(1)).strip(), j, m.group(0))
                break
        if firm:
            break
    if not firm:
        for i in report_pages:
            for j in range(i, min(i + 5, len(texts))):
                for ln in texts[j].split("\n"):
                    m = re.match(r"^\s*" + FIRM + r"(?:\s*$|\s*[•|,]\s*\d)", ln)
                    if m and not re.search(r"report|consent", ln, re.I):
                        firm = (m.group(1).strip(), j, ln.strip())
                        break
                if firm:
                    break
            if firm:
                break
    if not firm:
        pats = [r"audited by " + FIRM, FIRM + r",? (?:an |our )?independent registered public accounting firm",
                r"independent registered public accounting firm,? (?:is |was )?" + FIRM]
        for j, f in enumerate(flats):
            for pat in pats:
                m = re.search(pat, f)
                if m:
                    firm = (m.group(1).strip(), j, m.group(0))
                    break
            if firm:
                break
    if not firm:
        return out
    name, j, quote = firm
    out.append(_rec(ticker, pdf, j + 1, "auditor", name, "text", quote, statement="auditor"))
    m = re.search(re.escape(name) + r"\s*(?:We have served as[^.]*\.\s*)?([A-Z][A-Za-z. ]+,\s*(?:[A-Z][a-z]+(?: [A-Z][a-z]+)?|[A-Z]{2}))\s+(" + DATE + ")", flats[j])
    if m:
        out.append(_rec(ticker, pdf, j + 1, "auditor_city", m.group(1).strip(), "text", m.group(0), statement="auditor"))
    for k, f in enumerate(flats):
        tm = re.search(r"served as the [A-Za-z.&'’ ]{0,40}?auditors? (?:continuously )?since (?:at least )?(\d{4})", f, re.I)
        if tm:
            out.append(_rec(ticker, pdf, k + 1, "auditor_since", int(tm.group(1)), "year", tm.group(0), statement="auditor"))
            break
    return out


EMP_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*(?:million|thousand))"
EMP_NOUN = r"(employees|associates|team members|people|persons|colleagues|workers|staff)"
# "N employees" (also "85,100 ¹ people") or Goldman's "headcount of 47,400"
EMP_PAT = re.compile(r"(?:headcount of\s+)?" + EMP_NUM + r"(?:\s+\d)?(?:\s+(?:[a-zA-Z-]+\s+){0,5}?" + EMP_NOUN
                     + r"\b|(?=,? offices))", re.I)

# subset of the workforce, checked only in the words around the number
SUBSET = re.compile(r"\b(in (?:our |the )?(?:pharmaceutical )?(?:research|sales|marketing|manufacturing|engineering|"
                    r"r&d|technology)|research activities|functions|in the united states|in the u\.s\.|contractors?|"
                    r"outside (?:of )?the)\b", re.I)
WHOLE = re.compile(r"\b(worldwide|globally|global workforce|in total|total of|total workforce|employed approximately|"
                   r"we employed|had approximately|we had|employees globally)\b", re.I)


def employee_facts(ticker: str, pdf: str) -> list[dict]:
    """Company headcount from Item 1 (human capital). Every candidate sentence is scored: whole-company
    wording ("worldwide", "As of ..., we employed") wins over subsets ("people in research",
    "sales functions"); "X full-time and Y part-time" is summed."""
    texts = page_texts(pdf)
    cands = []
    for i, t in enumerate(texts[:130]):
        flat = _flat(t)
        if not re.search(r"employ|human capital|workforce|associates|team members|our people|headcount", flat, re.I):
            continue
        for m in EMP_PAT.finditer(flat):
            num = m.group(1)
            mult = 1e6 if "million" in num.lower() else 1e3 if "thousand" in num.lower() else 1
            v = float(re.sub(r"[^\d.]", "", num)) * mult
            if v < 1000:
                continue
            s0 = max(0, flat.rfind(". ", 0, m.start()) + 1)
            s1 = flat.find(". ", m.end())
            sent = flat[s0:s1 + 1 if s1 > 0 else m.end() + 80].strip()
            before = flat[s0:m.start()]
            after = flat[m.start():min(len(flat), m.end() + 45)]
            score = 0
            # the headcount statement itself: "we employed / had approximately N people"
            score += 4 if (re.search(r"\b(had|has|have|employed|employ|employs|workforce of|comprised of|consisted of|"
                                     r"total of|totaled)\b(?:\s+[a-z]+){0,2}\s*$", before, re.I)
                           or m.group(0).lower().startswith("headcount")) else 0
            score += 1 if re.search(r"employ|workforce|headcount", sent, re.I) else 0
            score += 2 if re.search(rf"(?:As of|At)\s+(?:the end of\s+)?(?:{DATE}|{MONTH}\s+\d{{4}}|fiscal \d{{4}}|\d{{4}})", sent, re.I) else 0
            score += 2 if WHOLE.search(sent) else 0
            score += 2 if re.search(r"\b(with|our)\s+(over|approximately|about|nearly)\s*$", before, re.I) else 0
            near = after if "engaged in" not in after else after.split("engaged in")[0]
            score -= 6 if (SUBSET.search(near) or SUBSET.search(before[-70:])
                           or re.search(r"\bin the region\b", near, re.I)) else 0
            window = before[-90:] + " " + after
            score -= 6 if re.search(r"\bshares\b|withheld|participat|trained|volunteer|hours of", window, re.I) else 0
            score -= 4 if re.search(r"partner|customers|users|communities|retire", window, re.I) else 0
            pt = re.search(EMP_NUM + r"\s+full[- ]time\s+\w+\s+and\s+(?:approximately\s+)?" + EMP_NUM + r"\s+part[- ]time", sent, re.I)
            if pt:
                v = sum(float(re.sub(r"[^\d.]", "", g)) for g in pt.groups())
                score += 1
            cands.append((score, -i, v, i, sent))
    if not cands:
        return []
    score, _, v, i, sent = max(cands)
    if score < 2:
        return []
    dm = re.search(rf"({DATE})", sent)
    return [_rec(ticker, pdf, i + 1, "employees", v, "count", sent, statement="text",
                 as_of=iso(dm.group(1)) if dm else None, confidence=0.9 if score >= 3 else 0.6)]


def signature_facts(ticker: str, pdf: str) -> list[dict]:
    """Signatures page: the person signing as (Principal Executive / Financial Officer)."""
    texts = page_texts(pdf)
    out = []
    name_re = re.compile(r"/s/\s*([A-Z][A-Za-z.\-' ]{3,50}?)(?=\s*\(|\s{2,}|\s+(?:Chief|Chairman|Chair|President|"
                         r"Director|Executive|Senior|Vice|Principal|Group|Interim)\b|\s*$)")
    roles = [("ceo", [r"Principal Executive Officer", r"Chief Executive Officer"]),
             ("cfo", [r"Principal Financial Officer", r"Chief Financial Officer"])]
    for i in range(len(texts) - 1, max(-1, len(texts) - 30), -1):
        t = texts[i]
        if "/s/" not in t or not re.search(r"Principal Executive Officer|Principal Financial Officer", t, re.I):
            continue
        lines = t.split("\n")
        for role, pats in roles:
            if any(r["metric"] == role for r in out):
                continue
            for pat in pats:
                hit = None
                for j, ln in enumerate(lines):
                    if not re.search(pat, ln, re.I):
                        continue
                    # same line first, then the line just above / below the title
                    for k in (j, j - 1, j + 1, j - 2):
                        if 0 <= k < len(lines):
                            m = name_re.search(lines[k])
                            if m:
                                hit = (m.group(1).strip(), " ".join(lines[min(j, k):max(j, k) + 1]))
                                break
                    if hit:
                        break
                if hit:
                    out.append(_rec(ticker, pdf, i + 1, role, hit[0], "person", hit[1], statement="signatures"))
                    break
        if len(out) == 2:
            break
    return out
