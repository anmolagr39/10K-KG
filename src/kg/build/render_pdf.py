"""Print EDGAR HTML documents to PDF with headless Chrome/Edge.

EDGAR serves modern 10-Ks as (inline-XBRL) HTML, not PDF. Printing the official HTML with a
browser gives the same document a company would post as a PDF on its IR site. We inject one
CSS rule so every PDF is US Letter with fixed margins, independent of the machine's locale.
The documents' own page-break styles are kept, so PDF pages follow the filing's pages.
"""
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PAGE_CSS = b"<style>@page { size: 8.5in 11in; margin: 0.45in; }</style>"

CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str:
    for c in CANDIDATES:
        if c and Path(c).exists():
            return c
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    raise SystemExit("No Chrome/Edge found; set CHROME_PATH")


def render(html_path: Path, pdf_path: Path, browser: str | None = None, timeout: int = 900) -> None:
    browser = browser or find_browser()
    src = html_path.read_bytes()
    m = re.search(rb"<head[^>]*>", src, flags=re.I)
    src = src[:m.end()] + PAGE_CSS + src[m.end():] if m else PAGE_CSS + src
    printable = html_path.with_name(html_path.stem + ".print.htm")
    printable.write_bytes(src)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run",
               "--no-default-browser-check", "--disable-extensions", f"--user-data-dir={profile}",
               "--no-pdf-header-footer", "--virtual-time-budget=60000",
               f"--print-to-pdf={pdf_path}", printable.resolve().as_uri()]
        subprocess.run(cmd, timeout=timeout, capture_output=True)
    printable.unlink(missing_ok=True)
    if not pdf_path.exists():
        raise RuntimeError(f"render failed: {html_path}")


def render_many(jobs: list[tuple[Path, Path]], workers: int = 3) -> None:
    if not jobs:
        return
    browser = find_browser()

    def one(job):
        html, pdf = job
        try:
            render(html, pdf, browser)
            return f"rendered {pdf.name} ({pdf.stat().st_size/1e6:.1f} MB)"
        except Exception as e:  # report and continue with the rest
            return f"FAILED {pdf.name}: {e}"

    with ThreadPoolExecutor(workers) as ex:
        for msg in ex.map(one, jobs):
            print(msg, flush=True)
