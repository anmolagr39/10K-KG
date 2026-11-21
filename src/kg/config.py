"""Paths and settings shared by every module."""
import csv
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"            # downloaded EDGAR HTML (gitignored, deleted after rendering)
PDF_DIR = DATA_DIR / "pdfs"           # rendered 10-K PDFs: the ONLY input of the KG pipeline
XBRL_DIR = DATA_DIR / "xbrl"          # XBRL facts per filing: used ONLY for verification/evaluation
PARSED_DIR = DATA_DIR / "parsed"      # per-page text cache (gitignored, regenerable)
EXTRACT_DIR = DATA_DIR / "extracted"  # extracted fact records (jsonl), input to the graph build
GRAPH_DIR = DATA_DIR / "graph"
CACHE_DIR = DATA_DIR / "cache"
BENCH_DIR = ROOT / "benchmark"
RESULTS_DIR = ROOT / "results"
MANIFEST = DATA_DIR / "manifest.csv"


def load_companies() -> list[dict]:
    with open(CONFIG_DIR / "companies.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["cik"] = int(r["cik"])
        r["aliases"] = [a for a in r["aliases"].split("|") if a]
    return rows


def load_manifest() -> list[dict]:
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def sec_user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        raise SystemExit(
            "Set SEC_USER_AGENT in .env (SEC requires a contact email in the User-Agent), e.g.\n"
            "SEC_USER_AGENT=Your Name project-name you@example.com")
    return ua
