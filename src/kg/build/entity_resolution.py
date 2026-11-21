"""Entity resolution: map a name found in one filing to a corpus company or a canonical entity.

"Advanced Micro Devices, Inc., or AMD" (NVIDIA 10-K) -> company AMD
"Taiwan Semiconductor Manufacturing Company Limited" -> entity "TSMC"
This SAME_AS link is what joins two PDFs in the graph.
"""
import re
from functools import lru_cache

from rapidfuzz import fuzz

from kg.config import load_companies

SUFFIX = re.compile(r"\b(incorporated|inc|corporation|corp|company|co|ltd|limited|llc|plc|holdings|group|"
                    r"s\.?a|n\.?v|ag|se|the)\b\.?", re.I)

# well-known entities outside the corpus that appear under several names
KNOWN = {
    "TSMC": ["taiwan semiconductor manufacturing", "taiwan semiconductor manufacturing company", "tsmc"],
    "Samsung": ["samsung electronics", "samsung"],
    "GlobalFoundries": ["globalfoundries", "global foundries"],
    "Huawei": ["huawei technologies", "huawei"],
    "Foxconn": ["foxconn", "hon hai precision industry", "hon hai"],
    "Arm": ["arm", "arm holdings", "arm limited"],
    "SAP": ["sap"],
    "Hewlett Packard Enterprise": ["hewlett packard enterprise", "hpe"],
    "Marvell": ["marvell technology", "marvell"],
    "Arista Networks": ["arista networks", "arista"],
    "Discover": ["discover financial services", "discover"],
    "Ernst & Young LLP": ["ernst and young llp", "ernst and young", "ey"],
    "PricewaterhouseCoopers LLP": ["pricewaterhousecoopers llp", "pricewaterhousecoopers", "pwc"],
    "KPMG LLP": ["kpmg llp", "kpmg"],
    "Deloitte & Touche LLP": ["deloitte and touche llp", "deloitte and touche", "deloitte"],
}


def norm_name(s: str) -> str:
    s = s.replace("&", " and ").replace("’", "'")
    s = re.sub(r"[,.()\"']", " ", s)
    s = SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


@lru_cache(maxsize=1)
def _alias_table() -> dict[str, str]:
    table = {}
    for c in load_companies():
        for a in [c["name"], c["ticker"]] + c["aliases"]:
            table[norm_name(a)] = c["ticker"]
    return table


def resolve_company(name: str) -> str | None:
    """Ticker of the corpus company a name refers to, or None."""
    n = norm_name(name)
    if not n:
        return None
    table = _alias_table()
    if n in table:
        return table[n]
    # "Amazon, Inc., or Amazon" / "Intel Corporation (Intel)": try each part
    for part in re.split(r"\bor\b|/|;", n):
        part = part.strip()
        if part in table:
            return table[part]
    best = max(table, key=lambda a: fuzz.token_sort_ratio(a, n))
    if fuzz.token_sort_ratio(best, n) >= 93 and len(n) > 3:
        return table[best]
    return None


def canonical_entity(name: str) -> str:
    """Canonical display name for an entity outside the corpus."""
    n = norm_name(name)
    for canon, names in KNOWN.items():
        if n in names or any(n.startswith(x + " ") for x in names if len(x) > 4):
            return canon
    return re.sub(r"\s+", " ", re.sub(r",?\s+(Inc|Corporation|Corp|Ltd|Limited|LLC|plc)\.?$", "", name.strip())).strip()
