"""Verify every gold fact of the benchmark.

  1. the printed value (or quote) appears on the cited PDF page  -> catches wrong page / typo
  2. numeric facts with an `xbrl` concept match SEC's XBRL value for that period end
     (XBRL is used here only, as an independent check; the system never reads it)

    python -m kg.eval.gold_check
"""
import json
import re
from datetime import date

from kg.config import BENCH_DIR, RESULTS_DIR
from kg.eval.gold_tools import page_has, xbrl


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def xbrl_match(g: dict) -> tuple[bool | None, str]:
    if not g.get("xbrl") or g.get("value") is None:
        return None, "no xbrl concept"
    vals_per_concept = []
    for concept in g["xbrl"].split("+"):   # "A+B": the filing tags only the parts of a total
        rows = [r for r in xbrl(g["ticker"], concept) if r["end"] == g["period_end"]]
        rows = [r for r in rows if not r["start"] or 330 <= _days(r["start"], r["end"]) <= 400]
        if not rows:
            return False, f"no XBRL value for {concept} at that period"
        vals_per_concept.append(sorted({r["val"] for r in rows}))
    vals = vals_per_concept[0] if len(vals_per_concept) == 1 else [sum(v[0] for v in vals_per_concept)]
    tol = 0.51e6 if g["unit"] == "USD" else 0.006
    ok = any(abs(v - g["value"]) <= tol for v in vals)
    return ok, f"xbrl={vals}"


def main() -> None:
    report, bad = [], 0
    for split in ("test", "dev"):
        for line in open(BENCH_DIR / f"{split}.jsonl", encoding="utf-8"):
            q = json.loads(line)
            for g in q["gold_facts"]:
                needle = g["quote"] if g["kind"] == "relation" else g["printed"]
                on_page = page_has(g["doc"], g["page"], needle)
                xok, xmsg = xbrl_match(g) if g["kind"] == "value" else (None, "")
                status = "OK" if on_page and xok is not False else "CHECK"
                bad += status != "OK"
                report.append({"id": q["id"], "fact": g["key"], "ticker": g["ticker"], "page": g["page"],
                               "needle": needle, "on_page": on_page, "xbrl_ok": xok, "xbrl": xmsg, "status": status})
                if status != "OK":
                    print(f"{q['id']} {g['key']} {g['ticker']} p{g['page']} '{needle}' on_page={on_page} xbrl={xok} {xmsg}")
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "gold_check.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    n_x = sum(1 for r in report if r["xbrl_ok"] is not None)
    print(f"{len(report)} gold facts checked: {len(report) - bad} OK, {bad} need attention; "
          f"page check passed {sum(r['on_page'] for r in report)}/{len(report)}; "
          f"XBRL agrees {sum(1 for r in report if r['xbrl_ok'])}/{n_x}")


if __name__ == "__main__":
    main()
