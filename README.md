# Knowledge graph over SEC 10-K filings

Genloop take-home: build a knowledge graph from unstructured 10-K PDFs of 35 companies, answer
questions by looking facts up in the graph (not by searching text), and measure it on a benchmark.

**Core idea.** Read every PDF once and turn every fact into a precise record:
company, metric, fiscal period, value, unit, source page. Connect those records in a graph and
answer a question by looking up and following connections. The LLM only writes the lookup plan.
It never reads the PDFs at question time and never writes a number into an answer.

**About the PDFs.** SEC EDGAR publishes modern 10-Ks as HTML, not PDF. The 37 PDFs in `data/pdfs/` are
the official EDGAR filings (the latest 10-K of each company, plus Exhibit 13 for IBM and Wells Fargo)
printed to PDF with headless Chrome; source URLs, accession numbers and hashes are in `data/manifest.csv`.
All page citations are 1-based physical page numbers of these PDFs.

**Quick start** (no API key needed, everything below runs from the committed graph and LLM cache):
```bash
pip install -r requirements.txt
export PYTHONPATH=src                      # Windows PowerShell: $env:PYTHONPATH="src"
python -m kg eval --split test             # reproduces the results table below
python -m kg chat                          # interactive; new questions need GROQ_API_KEY in .env
```

## Results (30 frozen test questions)

| | First frozen run | Final | BM25 chunks + LLM baseline |
|---|---|---|---|
| Overall accuracy | **0.90** (27/30) | **0.97** (29/30) | 0.30 (9/30), abstained on 17 |
| Single-fact (acc / P / R) | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 0.60 / 0.60 / 0.60 |
| Multi-hop (acc / P / R) | 0.80 / 0.97 / 0.99 | 0.90 / 0.97 / 1.00 | 0.20 / 0.00 / 0.00 |
| Cross-filing (acc / P / R) | 0.90 / 0.97 / 0.98 | 1.00 / 0.97 / 1.00 | 0.10 / 0.10 / 0.10 |
| Fact precision / recall (overall) | 0.98 / 0.99 | 0.98 / 1.00 | 0.23 / 0.23 |

- P / R = precision / recall of the fact nodes the system retrieved against the gold supporting facts, macro-averaged.
- The final run reuses the identical cached query plans of the frozen run; only the graph changed
  (two general extraction fixes: auditor names without "LLP"; relation extraction over whole + chunked
  excerpts). The remaining miss is a planner error (T18). Full analysis: `results/results.pdf`,
  per-question results: `results/per_question_test_graph.csv`, first run: `results/first_frozen_run.json`.
- Extraction accuracy of core statement facts vs SEC XBRL (35 companies x ~18 metrics):
  **607/610 = 99.5%, 0 wrong values** (`python -m kg.eval.xbrl_check`; first pass was 80.9%;
  rules were developed on these filings, so this is not a held-out number).

## Data

- 35 companies, 7 sectors x 5: Big Tech (AAPL MSFT GOOGL AMZN META), enterprise software (ORCL CRM ADBE IBM CSCO),
  chips (NVDA AMD INTC QCOM AVGO), banks (JPM BAC C WFC GS), payments (V MA AXP PYPL COF),
  retail (WMT COST TGT HD LOW), pharma (JNJ PFE MRK ABBV LLY).
- The latest 10-K of each company (fiscal years ending Nov 2025 to Sep 2026).
- **The PDFs are rendered from the official EDGAR filings.** EDGAR serves modern 10-Ks as HTML,
  not PDF, so `download.py` finds the latest 10-K with the SEC submissions API, downloads the primary
  document (plus Exhibit 13 when a company keeps its financial statements there: IBM, Wells Fargo)
  and prints it to a Letter-size PDF with headless Chrome. `data/manifest.csv` records accession,
  source URL and hashes. After this step the pipeline reads only the PDFs.
- **XBRL is used only for verification** (checking gold answers and measuring extraction accuracy).
  The graph is never built from XBRL.

## How the graph is built (`python -m kg build`)

| Step | What it does | LLM? |
|---|---|---|
| Statement pages | Score every page: statement title as a heading, year columns, many numbers, key rows ("Total assets", "per share"). Handles titles on a separate page, two-page statements, MD&A look-alikes. | no |
| Table parser | Words with x/y positions -> rows; columns = clusters of the numbers' right edges, tied to header years/dates; `(1,234)` -> -1234, `—` -> 0, scale from "(In millions ...)", section headers give context ("Basic" under "Earnings per share:" vs under "Shares used ..."). | no |
| Label -> metric | ~50 canonical metrics in `config/ontology.yaml` (synonyms + patterns + disambiguation rules: attributable net income, total vs component rows, current vs non-current debt). | no |
| Long tail | Every other year-column table (notes, MD&A) kept as labelled line items (~53K rows). | no |
| Regex facts | Cover page (state, HQ, exchange, fiscal year end, shares, float), auditor + tenure, headcount, CEO/CFO from signatures. | no |
| Prose relations | Competitors, suppliers/foundries, customers, segments, acquisitions from Item 1. The LLM must return an exact quote + page; code checks the quote is on that page and contains the entity, otherwise the item is dropped. | yes (35 calls) |
| Entity resolution | "Advanced Micro Devices, Inc., or AMD" in NVIDIA's filing -> company AMD (aliases + fuzzy). This link joins two PDFs. | no |
| Periods | Per-company fiscal periods with real end dates, the company's own fiscal label and rank (0 = latest), `PRECEDES` links. NVIDIA "fiscal 2026" ended Jan 2026; Home Depot "fiscal 2025" ended Feb 2026. | no |
| Verification | Accounting identities (assets = liabilities + equity, revenue - cost = gross profit, net income IS = CF, parts sum to totals) mark facts verified / unverified / conflicting. | no |

**Graph schema** (NetworkX MultiDiGraph, `data/graph/graph.json.gz`):

```
(fact: 132,175 USD m) -OF_METRIC-> (metric: net_income)
                      -ABOUT->     (company: AAPL)
                      -FOR_PERIOD-> (period: AAPL fiscal 2026, ended 2026-09-26) -PRECEDES- ...
                      -SOURCED_FROM-> (source: AAPL_10K_2026-09-26.pdf p.51, row text)
(fact: Services) -COMPONENT_OF-> (fact: Total net sales)
(company: NVDA) -COMPETES_WITH {fact}-> (company: AMD)      [quote on NVDA 10-K p.14]
(company: NVDA) -SUPPLIED_BY {fact}->  (entity: TSMC)
(company: NVDA) -AUDITED_BY {fact}->   (entity: PricewaterhouseCoopers LLP) <-AUDITED_BY- (company: JPM) ...
(metric: operating_margin_pct) -DERIVED_FROM {operating_income / revenue}-> (metric: revenue)
```

Facts are nodes (not edges) because a number needs company + metric + period + unit + source together,
as in XBRL. Every relation edge also points to a fact node holding its quote and page.

## How a question is answered (`python -m kg ask "..." --explain`)

1. **Plan (one LLM call).** The planner sees the operator catalog, metric ids, the 35 companies and
   worked examples taken from the dev set only, and returns a JSON plan.
2. **Execute (no LLM).** Deterministic operators over the graph: `get_fact`, `derive` (follows
   `DERIVED_FROM` formulas), `yoy` (follows `PRECEDES`), `related` (relation edges, both directions),
   `find_line_item` (scoped label search within one company's own rows), `filter`, `rank`,
   `aggregate`, `compute`, `compare`, `companies`.
3. Every operator logs the fact nodes it touched. That set is the retrieved facts scored by precision/recall.
4. If a step fails, the structured error goes back to the planner once. If the graph lacks the fact the system abstains.
5. The answer is a template with citations (document, page, row text or quote, verification status).

Example: *"Of the companies AMD names as competitors, which had the highest revenue?"*
```
s1 related(AMD, competes_with, in_corpus)   -> INTC, NVDA, AVGO, QCOM   [AMD 10-K p.17-18 quotes]
s2 get_fact($s1, revenue, latest_fy)        -> 4 facts, 4 different fiscal calendars
s3 rank(desc, k=1)                          -> NVDA ($215.94 billion, NVDA 10-K p.83)
```

## Setup and run

Python 3.11+ and Chrome or Edge (only for re-downloading).

```bash
pip install -r requirements.txt
export PYTHONPATH=src                      # Windows PowerShell: $env:PYTHONPATH="src"
python -m kg ask "Which retailer had the highest operating margin?" --explain
python -m kg eval --split test             # uses the committed LLM cache, no API key needed
```

Rebuilding from scratch needs `.env` with `SEC_USER_AGENT` (name + email, SEC policy) and
`GROQ_API_KEY` (free tier), then `python -m kg download` and `python -m kg build`.
Every LLM response is cached in `data/cache/llm/` (keyed by a hash of the request) and committed,
so the evaluation re-runs offline (`LLM_OFFLINE=1`). Any OpenAI-compatible endpoint works
(Gemini, Ollama) via `LLM_BASE_URL` / `LLM_API_KEY`.

## Benchmark (`benchmark/`)

- 30 test questions (10 single-fact, 10 multi-hop, 10 cross-filing) and 14 dev questions; human-readable sheet in `benchmark/REVIEW.md`.
- Written by reading the PDF pages before the graph existed, spread over sectors and parts of the
  filing (cover page, statements, notes, Item 1 prose, auditor's report), with deliberately hard ones.
- Each item stores its gold supporting facts (company, metric or relation, period, value as printed,
  document, page). Derived answers (margins, growth, sums) are computed by script from the gold facts
  with the formula recorded (`kg.eval.make_benchmark`).
- Verification (`kg.eval.gold_check`): every printed value / quote is on its cited page (132/132), and
  every numeric gold fact equals SEC XBRL (78/78).
- Frozen in git (commit `14dcf50`) before the first test run.
- Scoring is deterministic: numbers within 0.5%, percentages within 0.1 pp, entities by alias, lists
  as sets, rankings in order. Precision / recall over fact nodes (same company + same period and value,
  or same relation and object), macro-averaged per question.

## How AI tools were used

- Design, code and benchmark: Claude (claude.ai chat for planning, Claude Code for implementation)
  created the initial version based on the needs I stated, and it was iterated to the final version
  through my review and change suggestions. This covers the solution design, the code, and the
  benchmark questions and gold facts (taken from the PDF pages).
- I chose the company list, approved the benchmark before it was frozen, and reviewed the results;
  gold facts are also machine-checked against the PDF pages and XBRL.
- In the system itself: Groq free tier. `qwen/qwen3.8-27b` for prose relation extraction (35 calls,
  quotes verified in code), `openai/gpt-oss-120b` for query planning (1 call per question). No LLM
  reads or writes a number that ends up in an answer.
