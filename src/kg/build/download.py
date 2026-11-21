"""Step 1: fetch each company's latest 10-K from SEC EDGAR and render it to PDF.

For every company in config/companies.csv:
  1. read its filing history from the SEC submissions API and pick the most recent 10-K;
  2. download the primary 10-K document (HTML) and, if the filing has one, Exhibit 13
     (the annual report some companies use for their financial statements), plus the
     images those documents reference;
  3. print each document to a Letter-size PDF with headless Chrome (render_pdf.py);
  4. download XBRL companyfacts and keep only the facts tagged with this filing's accession.
     XBRL is used ONLY to verify gold answers and to measure extraction accuracy.
     The knowledge-graph pipeline never reads it.

After this step the pipeline reads only data/pdfs/*.pdf. Raw HTML lives in data/raw/
(gitignored) and is deleted after rendering unless --keep-raw is given.
"""
import csv
import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin

import fitz  # PyMuPDF
import requests

from kg.config import MANIFEST, PDF_DIR, RAW_DIR, XBRL_DIR, load_companies, sec_user_agent
from kg.build.render_pdf import render_many

ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


class SEC:
    """Polite EDGAR client: descriptive User-Agent, < 10 requests/second, retries on 429/503."""

    def __init__(self, min_interval: float = 0.15):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"})
        self.min_interval = min_interval
        self._last = 0.0

    def get(self, url: str) -> requests.Response:
        for attempt in range(5):
            wait = self._last + self.min_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            r = self.s.get(url, timeout=120)
            self._last = time.time()
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503):
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
        r.raise_for_status()
        return r


def latest_10k(sec: SEC, cik: int) -> dict:
    sub = sec.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()

    def scan(block: dict):
        for i, form in enumerate(block["form"]):
            if form == "10-K":  # original filing, not an amendment (10-K/A)
                return {k: block[k][i] for k in
                        ("accessionNumber", "filingDate", "reportDate", "primaryDocument", "form")}
        return None

    hit = scan(sub["filings"]["recent"])
    for older in sub["filings"].get("files", []):
        if hit:
            break
        hit = scan(sec.get(f"https://data.sec.gov/submissions/{older['name']}").json())
    if not hit:
        raise RuntimeError(f"no 10-K found for CIK {cik}")
    hit["fiscalYearEnd"] = sub.get("fiscalYearEnd")
    hit["entityName"] = sub.get("name")
    return hit


def filing_documents(sec: SEC, cik: int, acc: str) -> list[dict]:
    """Parse the filing index page into (type, description, url) rows."""
    url = f"{ARCHIVES}/{cik}/{acc.replace('-', '')}/{acc}-index.htm"
    html = sec.get(url).text
    docs = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)
        if len(cells) < 4:
            continue
        m = re.search(r'href="([^"]+)"', cells[2])
        if not m:
            continue
        href = m.group(1).replace("/ix?doc=", "")
        docs.append({
            "type": re.sub(r"<[^>]+>", "", cells[3]).strip(),
            "description": re.sub(r"<[^>]+>", "", cells[1]).strip(),
            "url": urljoin("https://www.sec.gov", href),
            "name": href.rsplit("/", 1)[-1],
        })
    return docs


def download_images(sec: SEC, html: str, base_url: str, folder: Path) -> int:
    n = 0
    for src in set(re.findall(r'<img[^>]+src="([^"]+)"', html, flags=re.I)):
        if src.startswith(("http:", "https:", "data:")) or "/" in src:
            continue
        dest = folder / src
        if not dest.exists():
            dest.write_bytes(sec.get(base_url + src).content)
            n += 1
    return n


def xbrl_for_filing(sec: SEC, cik: int, acc: str, ticker: str) -> int:
    """Keep only the XBRL facts that were reported in this filing (verification only)."""
    out = XBRL_DIR / f"{ticker}.json"
    if out.exists():
        return -1
    cf = sec.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()
    keep: dict = {}
    for taxonomy, concepts in cf.get("facts", {}).items():
        for concept, body in concepts.items():
            for unit, rows in body.get("units", {}).items():
                sel = [r for r in rows if r.get("accn") == acc]
                if sel:
                    keep.setdefault(f"{taxonomy}:{concept}", {})[unit] = sel
    XBRL_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"cik": cik, "accession": acc, "entityName": cf.get("entityName"),
                               "facts": keep}, indent=0), encoding="utf-8")
    return sum(len(r) for u in keep.values() for r in u.values())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(tickers: list[str] | None = None, keep_raw: bool = False) -> None:
    sec = SEC()
    companies = [c for c in load_companies() if not tickers or c["ticker"] in tickers]
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    old = {}
    if MANIFEST.exists():
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                old[(r["ticker"], r["doc_role"])] = r
    rows, jobs = [], []
    for c in companies:
        t, cik = c["ticker"], c["cik"]
        f = latest_10k(sec, cik)
        acc = f["accessionNumber"]
        base = f"{ARCHIVES}/{cik}/{acc.replace('-', '')}/"
        docs = filing_documents(sec, cik, acc)
        wanted = [("main", {"name": f["primaryDocument"], "url": base + f["primaryDocument"],
                            "type": "10-K", "description": "primary 10-K document"})]
        for d in docs:
            if d["type"].upper().startswith("EX-13") and d["name"].lower().endswith((".htm", ".html")):
                wanted.append(("ex13", d))
        for role, d in wanted:
            pdf_name = f"{t}_10K_{f['reportDate']}{'' if role == 'main' else '_EX13'}.pdf"
            pdf_path = PDF_DIR / pdf_name
            raw_dir = RAW_DIR / t
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / d["name"]
            html_sha = old.get((t, role), {}).get("html_sha256", "")
            if not pdf_path.exists():
                if not raw_path.exists():
                    raw_path.write_bytes(sec.get(d["url"]).content)
                html_sha = sha256(raw_path)
                n_img = download_images(sec, raw_path.read_text(encoding="utf-8", errors="ignore"), base, raw_dir)
                print(f"{t:5s} {role:4s} {acc} {d['name']} ({raw_path.stat().st_size/1e6:.1f} MB, {n_img} images)")
                jobs.append((raw_path, pdf_path))
            rows.append({
                "ticker": t, "cik": cik, "company": c["name"], "sector": c["sector"],
                "doc_role": role, "form": f["form"], "accession": acc,
                "filing_date": f["filingDate"], "period_of_report": f["reportDate"],
                "fiscal_year_end_mmdd": f["fiscalYearEnd"], "source_url": d["url"],
                "pdf": pdf_name, "html_sha256": html_sha,
            })
        n = xbrl_for_filing(sec, cik, acc, t)
        if n >= 0:
            print(f"{t:5s} xbrl facts kept: {n}")
    render_many(jobs)
    for r in rows:
        p = PDF_DIR / r["pdf"]
        r["pdf_sha256"] = sha256(p) if p.exists() else ""
        r["pdf_pages"] = fitz.open(p).page_count if p.exists() else 0
    # keep rows of companies not processed in this run
    done = {(r["ticker"], r["doc_role"]) for r in rows}
    rows += [r for k, r in old.items() if k not in done]
    rows.sort(key=lambda r: ([c["ticker"] for c in load_companies()].index(r["ticker"]), r["doc_role"] != "main"))
    with open(MANIFEST, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    if not keep_raw:
        shutil.rmtree(RAW_DIR, ignore_errors=True)
    print(f"manifest: {len(rows)} documents -> {MANIFEST}")
