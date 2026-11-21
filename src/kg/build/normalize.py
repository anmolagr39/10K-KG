"""Map company-specific row labels onto canonical ontology metrics (rules first).

Example: Apple "Total net sales", Alphabet "Revenues", AMD "Net revenue" -> `revenue`.
Rules are exact synonym matches on a normalised label plus the regex patterns in
config/ontology.yaml, then statement-specific disambiguation (which "Net income" row, which
"Basic" row, current vs non-current "Term debt", ...). Labels the rules cannot place are
optionally sent to the LLM (label -> metric id only; the LLM never sees a number).
"""
import re
from functools import lru_cache

import yaml

from kg.config import CONFIG_DIR


@lru_cache(maxsize=1)
def ontology() -> dict:
    return yaml.safe_load((CONFIG_DIR / "ontology.yaml").read_text(encoding="utf-8"))


def clean_label(label: str) -> str:
    """Remove note references and descriptive parentheticals, keep the line item name.

    "Deposits (included $20,930 and $33,768 at fair value)" -> "Deposits"
    "Total revenue C" (IBM note-letter column)            -> "Total revenue"
    "Earnings per Common Share — (Note 20) (a) Basic"     -> "Earnings per Common Share Basic"
    """
    s = label.replace("—", " ").replace("–", " ")
    s = re.sub(r"\s+(?:[A-Z](?:\s*&\s*[A-Z])?|[A-Z]{1,2}\s*&\s*[A-Z]{1,2})$", "", s.strip())   # IBM note letters
    s = re.sub(r"\((?=[^)]*(?:\d|\$|includ|note|see |fair value|net of))[^)]*\)", " ", s, flags=re.I)
    s = re.sub(r"\((?:\d{1,2}|[a-z]|[ivx]+)\)", " ", s)          # footnote markers (1) (a)
    s = re.sub(r":\s*\d{4},\s*\$.*$", "", s)                     # "net of sales: 2025, $1; ..."
    return re.sub(r"\s+", " ", s).strip()


def norm_label(label: str) -> str:
    s = clean_label(label).lower().replace("&", " and ")
    s = re.sub(r"\b(note|notes) \d+\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@lru_cache(maxsize=1)
def synonym_index() -> dict[tuple[str, str], str]:
    """(statement, normalised synonym) -> metric id"""
    idx = {}
    for mid, m in ontology()["metrics"].items():
        for syn in m.get("synonyms", []) or []:
            idx[(m["statement"], norm_label(syn))] = mid
    return idx


def metric_type(mid: str) -> str:
    return ontology()["metrics"][mid]["type"]


SHARE_SECTION = re.compile(r"shares|weighted|average number")
PER_SHARE = re.compile(r"per (basic |diluted )?(common )?share|assuming dilution")


def row_kind(label_n: str, section_n: str) -> str:
    """monetary | per_share | shares, from the row label and its section header."""
    if PER_SHARE.search(label_n):
        return "per_share"
    if re.search(r"weighted|shares used|average (common )?shares|number of shares|shares outstanding", label_n):
        return "shares"
    if label_n in ("basic", "diluted", "basic earnings", "diluted earnings") or label_n.startswith(("basic ", "diluted ")):
        if re.search(r"shares used|weighted|average|number of shares|shares outstanding", section_n):
            return "shares"
        if SHARE_SECTION.search(section_n) and not PER_SHARE.search(section_n):
            return "shares"
        if PER_SHARE.search(section_n) or "earnings" in section_n or "net income" in section_n:
            return "per_share"
    if "dividends declared per" in label_n or "dividends per" in label_n:
        return "per_share"
    return "monetary"


def candidate_metric(statement: str, label: str, section: str, kind: str | None = None) -> str | None:
    """Rule-based metric id for one row (before cross-row disambiguation)."""
    ln, sn = norm_label(label), norm_label(section)
    kind = kind or row_kind(ln, sn)
    if statement == "IS":
        if kind == "per_share":
            if re.search(r"dividend|discontinued|book value", ln):
                return None
            if re.search(r"\bdiluted\b|assuming dilution", ln):
                return "eps_diluted"
            if re.search(r"\bbasic\b", ln):
                return "eps_basic"
            # "Net income" / "Total" rows under a "Diluted earnings per share:" section
            last = sn.split(" > ")[-1] if " > " in sn else sn
            if re.search(r"\bdiluted\b|assuming dilution", sn):
                return "eps_diluted"
            if re.search(r"\bbasic\b", sn) or re.search(r"per (common )?share", last):
                return "eps_basic" if not re.search(r"\bdiluted\b", ln) else "eps_diluted"
            return None
        if kind == "shares":
            if "diluted" in ln:
                return "shares_diluted"
            if "basic" in ln:
                return "shares_basic"
            return None
        if re.search(r"noncontrolling|non controlling|minority interest|redeemable", ln):
            return None
        m = re.match(r"^(consolidated )?net (income|earnings)( loss)?( attributable to (.+))?$", ln)
        if m and "per share" not in ln:
            return "net_income"
        # "Citigroup's net income", "Wells Fargo net income"
        if re.match(r"^(?!total |consolidated |comprehensive |other |adjusted )[a-z]+( [a-z]+)?( s)? net (income|earnings)( loss)?$", ln):
            return "net_income"
        if re.match(r"^net (income|earnings) (applicable|available|attributable) to common", ln):
            return "net_income_to_common"
    mid = synonym_index().get((statement, ln))
    if mid:
        return mid
    for mid, m in ontology()["metrics"].items():
        if m["statement"] != statement:
            continue
        for pat in m.get("patterns", []) or []:
            if re.search(pat, ln):
                return mid
    if statement == "CF" and re.match(r"^(consolidated )?net (income|earnings)( loss)?( including noncontrolling interests?)?$", ln):
        return "net_income"
    # Wells Fargo: "Common stock:" section with rows "Repurchased" / "Cash dividends paid"
    if statement == "CF" and ln in ("repurchased", "purchased", "repurchases") and "common stock" in sn:
        return "share_repurchases"
    return None


def choose_rows(statement: str, rows: list[dict]) -> dict[str, int]:
    """Pick one row per metric within a statement. rows: [{idx,label,section,metric}] in order.

    Returns metric id -> row idx.
    """
    by_metric: dict[str, list[dict]] = {}
    for r in rows:
        if r["metric"]:
            by_metric.setdefault(r["metric"], []).append(r)
    chosen = {}
    for mid, cands in by_metric.items():
        if len(cands) == 1:
            chosen[mid] = cands[0]["idx"]
            continue
        ln = lambda r: norm_label(r["label"])
        sn = lambda r: norm_label(r["section"])
        pick = None
        if mid == "net_income":
            attrib = [r for r in cands if " attributable to " in ln(r)
                      or re.match(r"^(?!net |consolidated )[a-z ]+ net (income|earnings)", ln(r))]
            pick = attrib[0] if attrib else cands[0]
        elif mid in ("eps_basic", "eps_diluted"):
            # prefer the total / net income row over "continuing operations"
            tot = [r for r in cands if not re.search(r"continuing|discontinued", ln(r))]
            pick = tot[0] if tot else cands[-1]
        elif mid in ("operating_cash_flow", "investing_cash_flow", "financing_cash_flow"):
            tot = [r for r in cands if not re.search(r"continuing|discontinued", ln(r))]
            pick = tot[0] if tot else cands[0]
        elif mid == "dividends_paid":
            com = [r for r in cands if "common" in sn(r) or "common" in ln(r)]
            pref = [r for r in cands if "preferred" in sn(r) or "preferred" in ln(r)]
            pick = com[0] if com else next((r for r in cands if r not in pref), cands[0])
        elif mid in ("revenue", "cost_of_revenue", "deposits", "loans", "noninterest_income",
                     "noninterest_expense", "rd_expense"):
            tot = [r for r in cands if ln(r).startswith("total")]
            pick = tot[0] if tot else cands[0]
        elif mid == "total_equity":
            sh = [r for r in cands if re.search(r"(shareholders|stockholders|shareowners) equity", ln(r))]
            pick = sh[0] if sh else cands[0]
        elif mid == "long_term_debt":
            nc = [r for r in cands if not re.search(r"(^| )current liabilities", sn(r)) or "non current" in sn(r)]
            pick = nc[0] if nc else None
        elif mid == "cash_and_equivalents":
            pick = cands[0]
        else:
            pick = cands[0]
        if pick:
            chosen[mid] = pick["idx"]
    # banks and card lenders call their noninterest expense "Total operating expenses"/"Total expenses"
    if statement == "IS" and "net_interest_income" in chosen and "noninterest_expense" not in chosen \
            and "operating_expenses" in chosen:
        chosen["noninterest_expense"] = chosen.pop("operating_expenses")
    # a lone "term debt" in current liabilities is the current portion, not long-term debt
    if "long_term_debt" in chosen:
        r = next(r for r in rows if r["idx"] == chosen["long_term_debt"])
        if re.search(r"(^| )current liabilities", norm_label(r["section"])) and "non current" not in norm_label(r["section"]):
            del chosen["long_term_debt"]
    return chosen
