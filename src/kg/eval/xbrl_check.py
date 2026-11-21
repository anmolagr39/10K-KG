"""Extraction accuracy: compare facts extracted from the PDFs with SEC XBRL (verification only).

For every company and every core metric that has us-gaap tags in config/ontology.yaml:
  match         extracted value equals an XBRL value of one of the metric's tags (same period end)
  mismatch      we extracted a value, XBRL has values, none equal ours
  not_extracted XBRL has a value but the parser produced no fact for the metric
  no_reference  XBRL has no value under the listed tags (excluded from accuracy)
XBRL is the reference here only. The knowledge graph never reads it.

    python -m kg.eval.xbrl_check
"""
import csv
import json
from datetime import date

from kg.build.normalize import ontology
from kg.config import EXTRACT_DIR, RESULTS_DIR, XBRL_DIR, load_companies, load_manifest

CORE = ["revenue", "cost_of_revenue", "gross_profit", "rd_expense", "sga_expense", "operating_income",
        "pretax_income", "income_tax", "net_income", "eps_basic", "eps_diluted", "total_assets",
        "total_liabilities", "total_equity", "cash_and_equivalents", "long_term_debt", "operating_cash_flow",
        "capex", "dividends_paid", "share_repurchases", "net_interest_income", "provision_credit_losses",
        "noninterest_expense", "deposits"]
BANK_ONLY = {"net_interest_income", "provision_credit_losses", "noninterest_expense", "deposits"}


def xbrl_values(ticker: str, tags: list[str], end: str, instant: bool) -> list[float]:
    d = json.loads((XBRL_DIR / f"{ticker}.json").read_text(encoding="utf-8"))
    vals = []
    for tag in tags:
        key = tag if ":" in tag else f"us-gaap:{tag}"
        for unit, rows in d["facts"].get(key, {}).items():
            for r in rows:
                if r["end"] != end:
                    continue
                if instant != (r.get("start") is None):
                    continue
                if not instant:
                    days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
                    if not 330 <= days <= 400:
                        continue
                vals.append(float(r["val"]))
    return sorted(set(vals))


def latest_value(facts: list[dict], metric: str, end: str) -> dict | None:
    cands = [f for f in facts if f["metric"] == metric and f["statement"] in ("IS", "BS", "CF")]
    if not cands:
        return None
    canonical = [f for f in cands if f["statement"] == ontology()["metrics"][metric]["statement"]] or cands
    exact = [f for f in canonical if f.get("end_date") == end]
    if exact:
        return exact[0]
    top_year = max(f["col_year"] or 0 for f in canonical)
    return next(f for f in canonical if f["col_year"] == top_year)


def main() -> None:
    period = {r["ticker"]: r["period_of_report"] for r in load_manifest()}
    rows = []
    for c in load_companies():
        t = c["ticker"]
        ex = json.loads((EXTRACT_DIR / f"{t}.json").read_text(encoding="utf-8"))
        lender = c["sector"] == "Banks" or t in ("COF", "AXP")
        for m in CORE:
            if m in BANK_ONLY and not lender:
                continue   # e.g. AMD tags InterestIncomeExpenseNet, but that is not a bank metric for a chip maker
            spec = ontology()["metrics"][m]
            ref = xbrl_values(t, spec.get("us_gaap", []), period[t], spec["period"] == "instant")
            f = latest_value(ex["table_facts"], m, period[t])
            got = f["value"] if f else None
            tol = 0.006 if spec["type"] == "per_share" else 0.6e6
            if not ref:
                status = "no_reference" if got is None else "extracted_no_reference"
            elif got is None:
                status = "not_extracted"
            elif any(abs(abs(got) - abs(v)) <= tol for v in ref):
                status = "match"
            else:
                status = "mismatch"
            rows.append({"ticker": t, "metric": m, "status": status, "extracted": got,
                         "xbrl": ";".join(f"{v:.0f}" if abs(v) > 100 else f"{v}" for v in ref),
                         "label": f["label"] if f else "", "page": f["page"] if f else "",
                         "end_date": f.get("end_date") if f else ""})
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(RESULTS_DIR / "xbrl_extraction_check.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    scored = [r for r in rows if r["status"] in ("match", "mismatch", "not_extracted")]
    n_match = sum(r["status"] == "match" for r in scored)
    print(f"extraction accuracy vs XBRL: {n_match}/{len(scored)} = {n_match / max(1, len(scored)):.1%} "
          f"(mismatch {sum(r['status'] == 'mismatch' for r in scored)}, "
          f"not extracted {sum(r['status'] == 'not_extracted' for r in scored)})")
    print("by metric:")
    for m in CORE:
        s = [r for r in scored if r["metric"] == m]
        if s:
            print(f"  {m:24s} {sum(r['status'] == 'match' for r in s):2d}/{len(s):2d}  "
                  + " ".join(f"{r['ticker']}:{r['status'][:3]}" for r in s if r["status"] != "match"))
    summary = {"accuracy": n_match / max(1, len(scored)), "matched": n_match, "scored": len(scored),
               "by_metric": {m: [sum(r['status'] == 'match' for r in scored if r['metric'] == m),
                                 sum(1 for r in scored if r['metric'] == m)] for m in CORE}}
    (RESULTS_DIR / "xbrl_extraction_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
