"""The ONLY LLM use at question time: turn the question into a JSON query plan.

The model sees the operator catalog, the metric ids, the 35 companies and a few worked examples
taken from the DEV set only. It never sees the PDFs and never writes a number into the answer.
"""
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from kg.build.normalize import ontology
from kg.config import load_companies
from kg.llm import PLANNER_MODEL, chat_json

OpName = Literal["companies", "get_fact", "derive", "yoy", "find_line_item", "related", "filter", "rank",
                 "aggregate", "compute", "compare"]


class Step(BaseModel):
    id: str
    op: OpName
    args: dict = Field(default_factory=dict)


class Plan(BaseModel):
    steps: list[Step]
    answer: str


# Worked examples = DEV questions only (benchmark/dev.jsonl). Test questions are never shown.
FEW_SHOT = [
    ("What was IBM's total revenue in 2025?",
     {"steps": [{"id": "s1", "op": "get_fact", "args": {"companies": ["IBM"], "metric": "revenue", "period": "fy:2025"}}], "answer": "s1"}),
    ("Who is Cisco's independent auditor?",
     {"steps": [{"id": "s1", "op": "related", "args": {"subject": "CSCO", "relation": "audited_by"}}], "answer": "s1"}),
    ("What was Target's free cash flow in fiscal 2025 (cash provided by operating activities minus expenditures for property and equipment)?",
     {"steps": [{"id": "s1", "op": "derive", "args": {"companies": ["TGT"], "metric": "free_cash_flow", "period": "fy:2025"}}], "answer": "s1"}),
    ("Rank Johnson & Johnson, Pfizer, Merck, AbbVie and Eli Lilly by revenue in 2025, highest first.",
     {"steps": [{"id": "s1", "op": "get_fact", "args": {"companies": ["JNJ", "PFE", "MRK", "ABBV", "LLY"], "metric": "revenue", "period": "fy:2025"}},
                {"id": "s2", "op": "rank", "args": {"items": "$s1", "order": "desc"}}], "answer": "s2"}),
    ("Of the companies in the corpus that AMD names as competitors, which had the highest revenue in its latest fiscal year?",
     {"steps": [{"id": "s1", "op": "related", "args": {"subject": "AMD", "relation": "competes_with", "direction": "out", "in_corpus": True}},
                {"id": "s2", "op": "get_fact", "args": {"companies": "$s1", "metric": "revenue", "period": "latest_fy"}},
                {"id": "s3", "op": "rank", "args": {"items": "$s2", "order": "desc", "k": 1}}], "answer": "s3"}),
    ("What percentage of Microsoft's total revenue in fiscal 2026 came from \"Service and other\" revenue?",
     {"steps": [{"id": "s1", "op": "find_line_item", "args": {"company": "MSFT", "query": "Revenue: Service and other", "period": "fy:2026"}},
                {"id": "s2", "op": "get_fact", "args": {"companies": ["MSFT"], "metric": "revenue", "period": "fy:2026"}},
                {"id": "s3", "op": "compute", "args": {"op": "ratio_pct", "a": "$s1", "b": "$s2"}}], "answer": "s3"}),
    ("By what percentage did NVIDIA's revenue grow in fiscal 2026 compared with fiscal 2025?",
     {"steps": [{"id": "s1", "op": "yoy", "args": {"companies": ["NVDA"], "metric": "revenue", "period": "fy:2026"}}], "answer": "s1"}),
    ("Which companies in the corpus are audited by Deloitte & Touche LLP?",
     {"steps": [{"id": "s1", "op": "related", "args": {"subject": "Deloitte & Touche LLP", "relation": "audited_by", "direction": "in"}}], "answer": "s1"}),
    ("What was the average research and development expense of NVIDIA, AMD, Intel, Qualcomm and Broadcom in their latest fiscal years?",
     {"steps": [{"id": "s1", "op": "get_fact", "args": {"companies": ["NVDA", "AMD", "INTC", "QCOM", "AVGO"], "metric": "rd_expense", "period": "latest_fy"}},
                {"id": "s2", "op": "aggregate", "args": {"items": "$s1", "fn": "avg"}}], "answer": "s2"}),
    ("Which had more total assets at its latest balance sheet date, Costco or Target, and by how much?",
     {"steps": [{"id": "s1", "op": "get_fact", "args": {"companies": ["COST", "TGT"], "metric": "total_assets", "period": "latest_fy"}},
                {"id": "s2", "op": "compare", "args": {"items": "$s1"}}], "answer": "s2"}),
]

OPERATORS = """Operators ("$sN" = the output of step sN):
- companies(sector?, tickers?): companies of a sector (Big Tech, Enterprise Software, Chips, Banks, Payments, Retail, Pharma)
- get_fact(companies, metric, period): value of a metric from the list below, per company
- derive(companies, metric, period): a derived metric computed from facts (formulas below)
- yoy(companies, metric, period): growth % of a metric vs the prior fiscal year
- find_line_item(company, query, period): a number that is NOT a listed metric (product/segment/sub-line), found by
  searching that company's own table rows; query = section words + row label, e.g. "Net sales: Services"
- related(subject, relation, direction="out"|"in", in_corpus?, exclude?): relation edges. out = what the subject
  company names (its competitors, suppliers, auditor, ceo...); in = companies that name the subject (subject can be
  an entity such as "TSMC" or "$s1"). in_corpus=true keeps corpus companies only. exclude=[tickers] removes some.
- filter(items, sector?, exclude?, min_value?, max_value?)
- rank(items, order="desc"|"asc", k?): k=1 for "which one is highest/lowest"; no k for a full ranking
- aggregate(items, fn="sum"|"avg"|"count"|"min"|"max")
- compute(op="ratio"|"ratio_pct"|"diff"|"sum"|"growth_pct", a, b): arithmetic between two steps (aligned by company)
- compare(items): which of the companies is larger and by how much

Periods: "latest_fy" = most recent fiscal year in the company's latest 10-K (balance sheets: its end date);
"prior_fy"; "fy:YYYY" = the company's OWN fiscal-year label (NVIDIA fiscal 2026 ended Jan 2026 -> fy:2026; Home Depot
fiscal 2025 ended Feb 2026 -> fy:2025; "in 2025" for a December year-end company -> fy:2025);
"end:YYYY-MM-DD" = the period ending on that date. Use latest_fy for "latest/most recent fiscal year".
Relations: competes_with, supplied_by (foundry/manufacturer/supplier), customer, has_segment, acquired, audited_by, has_ceo, has_cfo."""


def catalog() -> str:
    o = ontology()
    mets = []
    for mid, m in o["metrics"].items():
        mets.append(f"{mid} ({m['name']})")
    der = [f"{did} = {d['formula']}" for did, d in o["derived"].items()]
    cos = [f"{c['ticker']}: {c['name']} [{c['sector']}]" for c in load_companies()]
    return ("Companies: " + "; ".join(cos) + "\n\nMetrics for get_fact/yoy: " + ", ".join(mets)
            + "\n\nDerived metrics for derive: " + "; ".join(der))


def build_prompt(question: str) -> list[dict]:
    shots = "\n".join(f"Q: {q}\nPLAN: {json.dumps(p, separators=(',', ':'))}" for q, p in FEW_SHOT)
    system = ("You translate a question about the 10-K filings of 35 US companies into a JSON query plan over a "
              "knowledge graph built from those filings. You do NOT answer the question and never write numbers "
              "from memory; the plan's operators fetch every value from the graph.\n\n" + catalog() + "\n\n" + OPERATORS
              + '\n\nReturn ONLY JSON: {"steps": [{"id": "s1", "op": "...", "args": {...}}, ...], "answer": "sN"}'
              + "\n\nExamples:\n" + shots)
    return [{"role": "system", "content": system}, {"role": "user", "content": f"Q: {question}\nPLAN:"}]


def plan(question: str, repair: dict | None = None) -> Plan:
    msgs = build_prompt(question)
    if repair:
        msgs += [{"role": "assistant", "content": json.dumps(repair["plan"])},
                 {"role": "user", "content": f"That plan failed: {repair['error']}\nReturn a corrected plan (JSON only)."}]
    raw = chat_json(msgs, model=PLANNER_MODEL, max_tokens=1500, tag="plan", reasoning_effort="medium")
    try:
        return Plan.model_validate(raw)
    except ValidationError as e:
        raise PlanError(str(e)[:500], raw)


class PlanError(Exception):
    def __init__(self, msg, raw):
        super().__init__(msg)
        self.raw = raw
