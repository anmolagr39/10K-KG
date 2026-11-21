# Benchmark review sheet

Generated from `benchmark/gold_source.yaml` by `python -m kg.eval.make_benchmark`.
Every gold fact was checked by `python -m kg.eval.gold_check` (value printed on the cited page; numbers equal to SEC XBRL). Pages are 1-based physical pages of the PDF in `data/pdfs/`.

## test set (30 questions)

### T01 · single_fact · income statement

**Q:** What was Costco's total revenue for its fiscal year ended August 30, 2026?

**Gold answer:** $303,154 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | COST | revenue | 303,154 | 2026-08-30 | COST_10K_2026-08-30.pdf | 52 |

### T02 · single_fact · income statement

**Q:** How much did Merck spend on research and development in 2025?

**Gold answer:** $15,789 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | MRK | rd_expense | 15,789 | 2025-12-31 | MRK_10K_2025-12-31.pdf | 136 |

### T03 · single_fact · balance sheet (bank)

**Q:** What were JPMorgan Chase's total deposits at December 31, 2025?

**Gold answer:** $2,559,320 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | JPM | deposits | 2,559,320 | 2025-12-31 | JPM_10K_2025-12-31.pdf | 272 |

### T04 · single_fact · income statement (per share)

**Q:** What was NVIDIA's diluted earnings per share for fiscal year 2026?

**Gold answer:** $4.90 per share

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | NVDA | eps_diluted | 4.90 | 2026-01-25 | NVDA_10K_2026-01-25.pdf | 83 |

### T05 · single_fact · auditor's report

**Q:** Which accounting firm audits Adobe's financial statements?

**Gold answer:** KPMG LLP

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | ADBE | audited_by → KPMG LLP | "/s/ KPMG LLP" |  | ADBE_10K_2025-11-28.pdf | 142 |

### T06 · single_fact · Item 1 (human capital, prose)

**Q:** How many associates did Home Depot employ at the end of fiscal 2025?

**Gold answer:** 472,400

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | HD | employees | 472,400 | 2026-02-01 | HD_10K_2026-02-01.pdf | 18 |

### T07 · single_fact · cover page

**Q:** In which U.S. state is Visa incorporated?

**Gold answer:** Delaware

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | V | state_of_incorporation | Delaware |  | V_10K_2026-09-30.pdf | 1 |

### T08 · single_fact · cash flow statement

**Q:** How much did Eli Lilly spend on purchases of property and equipment in 2025?

**Gold answer:** $7,841 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | LLY | capex | 7,841 | 2025-12-31 | LLY_10K_2025-12-31.pdf | 88 |

### T09 · single_fact · income statement (lender)

**Q:** What provision for credit losses did Capital One record in 2025?

**Gold answer:** $20,655 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | COF | provision_credit_losses | 20,655 | 2025-12-31 | COF_10K_2025-12-31.pdf | 146 |

### T10 · single_fact · segment note (notes table)

**Q:** What were net sales of Amazon's AWS segment in 2025?

**Gold answer:** $128,725 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | AMZN | segment_net_sales:AWS | 128,725 | 2025-12-31 | AMZN_10K_2025-12-31.pdf | 107 |

### T11 · multi_hop · income statement + formula

**Q:** What was Alphabet's operating margin in 2025 (income from operations as a percentage of revenues)?

**Gold answer:** 32.03%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | GOOGL | operating_income | 129,039 | 2025-12-31 | GOOGL_10K_2025-12-31.pdf | 87 |
| f2 | GOOGL | revenue | 402,836 | 2025-12-31 | GOOGL_10K_2025-12-31.pdf | 87 |

### T12 · multi_hop · cash flow statement + formula

**Q:** What was Amazon's free cash flow in 2025, defined as net cash provided by operating activities minus purchases of property and equipment?

**Gold answer:** $7,695 million  (= f1 - f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | AMZN | operating_cash_flow | 139,514 | 2025-12-31 | AMZN_10K_2025-12-31.pdf | 60 |
| f2 | AMZN | capex | 131,819 | 2025-12-31 | AMZN_10K_2025-12-31.pdf | 60 |

### T13 · multi_hop · income statement, two periods (YoY)

**Q:** By what percentage did Walmart's total revenues grow in fiscal 2026 compared with fiscal 2025?

**Gold answer:** 4.73%  (= (f1 - f2) / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | WMT | revenue | 713,163 | 2026-01-31 | WMT_10K_2026-01-31.pdf | 84 |
| f2 | WMT | revenue | 680,985 | 2025-01-31 | WMT_10K_2026-01-31.pdf | 84 |

### T14 · multi_hop · income statement + formula

**Q:** What was Oracle's effective tax rate for fiscal 2026, i.e. provision for income taxes divided by income before income taxes?

**Gold answer:** 12.62%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | ORCL | income_tax | 2,467 | 2026-05-31 | ORCL_10K_2026-05-31.pdf | 119 |
| f2 | ORCL | pretax_income | 19,554 | 2026-05-31 | ORCL_10K_2026-05-31.pdf | 119 |

### T15 · multi_hop · auditor's reports across filings (relation chain NVIDIA -> firm -> other clients)

**Q:** Which other companies in the corpus are audited by the same accounting firm as NVIDIA?

**Gold answer:** IBM, CSCO, QCOM, AVGO, JPM, BAC, GS, MA, AXP, PYPL, JNJ, MRK

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f0 | NVDA | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | NVDA_10K_2026-01-25.pdf | 82 |
| f1 | IBM | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | IBM_10K_2025-12-31_EX13.pdf | 43 |
| f2 | CSCO | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | CSCO_10K_2026-07-25.pdf | 95 |
| f3 | QCOM | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | QCOM_10K_2026-09-27.pdf | 86 |
| f4 | AVGO | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | AVGO_10K_2025-11-02.pdf | 81 |
| f5 | JPM | audited_by → PricewaterhouseCoopers LLP | "audited by PricewaterhouseCoopers LLP" |  | JPM_10K_2025-12-31.pdf | 263 |
| f6 | BAC | audited_by → PricewaterhouseCoopers LLP | "audited by PricewaterhouseCoopers" |  | BAC_10K_2025-12-31.pdf | 147 |
| f7 | GS | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | GS_10K_2025-12-31.pdf | 296 |
| f8 | MA | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | MA_10K_2025-12-31.pdf | 97 |
| f9 | AXP | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | AXP_10K_2025-12-31.pdf | 134 |
| f10 | PYPL | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | PYPL_10K_2025-12-31.pdf | 103 |
| f11 | JNJ | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | JNJ_10K_2025-12-28.pdf | 118 |
| f12 | MRK | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | MRK_10K_2025-12-31.pdf | 230 |

### T16 · multi_hop · income statement + formula

**Q:** What percentage of its 2025 revenue did Meta spend on research and development?

**Gold answer:** 28.55%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | META | rd_expense | 57,372 | 2025-12-31 | META_10K_2025-12-31.pdf | 148 |
| f2 | META | revenue | 200,966 | 2025-12-31 | META_10K_2025-12-31.pdf | 148 |

### T17 · multi_hop · income statement sub-line (share of total)

**Q:** What percentage of Apple's total net sales in fiscal 2026 came from Services?

**Gold answer:** 25.75%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | AAPL | line_item:Services net sales | 123,301 | 2026-09-26 | AAPL_10K_2026-09-26.pdf | 51 |
| f2 | AAPL | revenue | 478,834 | 2026-09-26 | AAPL_10K_2026-09-26.pdf | 51 |

### T18 · multi_hop · bank income statement + formula

**Q:** What was Bank of America's efficiency ratio in 2025, i.e. total noninterest expense divided by total revenue net of interest expense?

**Gold answer:** 61.65%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | BAC | noninterest_expense | 69,727 | 2025-12-31 | BAC_10K_2025-12-31.pdf | 151 |
| f2 | BAC | revenue | 113,097 | 2025-12-31 | BAC_10K_2025-12-31.pdf | 151 |

### T19 · multi_hop · income statement + Item 1 prose (two different parts of the filing)

**Q:** What was Costco's total revenue per employee in fiscal 2026?

**Gold answer:** $1 million  (= f1 / f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | COST | revenue | 303,154 | 2026-08-30 | COST_10K_2026-08-30.pdf | 52 |
| f2 | COST | employees | 355,000 | 2026-08-30 | COST_10K_2026-08-30.pdf | 8 |

### T20 · multi_hop · income statement, two periods (YoY)

**Q:** By what percentage did Microsoft's net income grow in fiscal year 2026 versus fiscal year 2025?

**Gold answer:** 31.34%  (= (f1 - f2) / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | MSFT | net_income | 133,749 | 2026-06-30 | MSFT_10K_2026-06-30.pdf | 78 |
| f2 | MSFT | net_income | 101,832 | 2025-06-30 | MSFT_10K_2026-06-30.pdf | 78 |

### T21 · cross_filing · five bank income statements (one in an Exhibit 13)

**Q:** Rank JPMorgan Chase, Bank of America, Citigroup, Wells Fargo and Goldman Sachs by net income in 2025, highest first.

**Gold answer:** JPM > BAC > WFC > GS > C

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | JPM | net_income | 57,048 | 2025-12-31 | JPM_10K_2025-12-31.pdf | 270 |
| f2 | BAC | net_income | 30,509 | 2025-12-31 | BAC_10K_2025-12-31.pdf | 151 |
| f3 | C | net_income | 14,306 | 2025-12-31 | C_10K_2025-12-31.pdf | 177 |
| f4 | WFC | net_income | 21,338 | 2025-12-31 | WFC_10K_2025-12-31_EX13.pdf | 135 |
| f5 | GS | net_income | 17,176 | 2025-12-31 | GS_10K_2025-12-31.pdf | 297 |

### T22 · cross_filing · Item 1 prose relation (NVIDIA) + four other filings' income statements

**Q:** Among the semiconductor companies that NVIDIA names as competitors in its 10-K, which one spent the most on research and development in its latest fiscal year?

**Gold answer:** INTC

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| r1 | NVDA | competes_with → AMD | "Advanced Micro Devices, Inc., or AMD" |  | NVDA_10K_2026-01-25.pdf | 14 |
| r2 | NVDA | competes_with → INTC | "Intel Corporation, or Intel" |  | NVDA_10K_2026-01-25.pdf | 14 |
| r3 | NVDA | competes_with → AVGO | "Broadcom" |  | NVDA_10K_2026-01-25.pdf | 14 |
| r4 | NVDA | competes_with → QCOM | "Qualcomm Incorporated" |  | NVDA_10K_2026-01-25.pdf | 14 |
| f1 | AMD | rd_expense | 8,091 | 2025-12-27 | AMD_10K_2025-12-27.pdf | 86 |
| f2 | INTC | rd_expense | 13,774 | 2025-12-27 | INTC_10K_2025-12-27.pdf | 101 |
| f3 | AVGO | rd_expense | 10,977 | 2025-11-02 | AVGO_10K_2025-11-02.pdf | 84 |
| f4 | QCOM | rd_expense | 10,207 | 2026-09-27 | QCOM_10K_2026-09-27.pdf | 88 |

### T23 · cross_filing · five income statements + formula, different fiscal calendars

**Q:** Which of the five retailers (Walmart, Costco, Target, Home Depot, Lowe's) had the highest operating margin in its latest fiscal year?

**Gold answer:** HD

_Note: margins: WMT 4.18%, COST 3.85%, TGT 4.88%, HD 12.69%, LOW 11.77%_

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | WMT | operating_income | 29,825 | 2026-01-31 | WMT_10K_2026-01-31.pdf | 84 |
| f2 | WMT | revenue | 713,163 | 2026-01-31 | WMT_10K_2026-01-31.pdf | 84 |
| f3 | COST | operating_income | 11,685 | 2026-08-30 | COST_10K_2026-08-30.pdf | 52 |
| f4 | COST | revenue | 303,154 | 2026-08-30 | COST_10K_2026-08-30.pdf | 52 |
| f5 | TGT | operating_income | 5,117 | 2026-01-31 | TGT_10K_2026-01-31.pdf | 47 |
| f6 | TGT | revenue | 104,780 | 2026-01-31 | TGT_10K_2026-01-31.pdf | 47 |
| f7 | HD | operating_income | 20,890 | 2026-02-01 | HD_10K_2026-02-01.pdf | 73 |
| f8 | HD | revenue | 164,683 | 2026-02-01 | HD_10K_2026-02-01.pdf | 73 |
| f9 | LOW | operating_income | 10,153 | 2026-01-30 | LOW_10K_2026-01-30.pdf | 69 |
| f10 | LOW | revenue | 86,286 | 2026-01-30 | LOW_10K_2026-01-30.pdf | 69 |

### T24 · cross_filing · five income statements, aggregate

**Q:** What was the combined revenue of Apple, Microsoft, Alphabet, Amazon and Meta in their latest fiscal years?

**Gold answer:** $2,131,399 million  (= f1 + f2 + f3 + f4 + f5)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | AAPL | revenue | 478,834 | 2026-09-26 | AAPL_10K_2026-09-26.pdf | 51 |
| f2 | MSFT | revenue | 331,839 | 2026-06-30 | MSFT_10K_2026-06-30.pdf | 78 |
| f3 | GOOGL | revenue | 402,836 | 2025-12-31 | GOOGL_10K_2025-12-31.pdf | 87 |
| f4 | AMZN | revenue | 716,924 | 2025-12-31 | AMZN_10K_2025-12-31.pdf | 61 |
| f5 | META | revenue | 200,966 | 2025-12-31 | META_10K_2025-12-31.pdf | 148 |

### T25 · cross_filing · five income statements, compare

**Q:** Which of the five pharma companies (Johnson & Johnson, Pfizer, Merck, AbbVie, Eli Lilly) reported the highest research and development expense in 2025? Use the research and development line, excluding acquired in-process R&D.

**Gold answer:** MRK

_Note: if acquired IPR&D were added, Lilly (16,247) would lead - the question pins the R&D line_

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | JNJ | rd_expense | 14,665 | 2025-12-28 | JNJ_10K_2025-12-28.pdf | 52 |
| f2 | PFE | rd_expense | 10,437 | 2025-12-31 | PFE_10K_2025-12-31.pdf | 109 |
| f3 | MRK | rd_expense | 15,789 | 2025-12-31 | MRK_10K_2025-12-31.pdf | 136 |
| f4 | ABBV | rd_expense | 9,096 | 2025-12-31 | ABBV_10K_2025-12-31.pdf | 92 |
| f5 | LLY | rd_expense | 13,337 | 2025-12-31 | LLY_10K_2025-12-31.pdf | 83 |

### T26 · cross_filing · two income statements with different fiscal year ends

**Q:** Which reported higher net revenue in its latest fiscal year, Visa or Mastercard, and by how much?

**Gold answer:** V, by $13,112 million  (= f1 - f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | V | revenue | 45,903 | 2026-09-30 | V_10K_2026-09-30.pdf | 100 |
| f2 | MA | revenue | 32,791 | 2025-12-31 | MA_10K_2025-12-31.pdf | 98 |

### T27 · cross_filing · five income statements, compare

**Q:** Which of the payments companies (Visa, Mastercard, American Express, PayPal, Capital One) had the highest net income in its latest fiscal year?

**Gold answer:** V

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | V | net_income | 23,504 | 2026-09-30 | V_10K_2026-09-30.pdf | 100 |
| f2 | MA | net_income | 14,968 | 2025-12-31 | MA_10K_2025-12-31.pdf | 98 |
| f3 | AXP | net_income | 10,833 | 2025-12-31 | AXP_10K_2025-12-31.pdf | 136 |
| f4 | PYPL | net_income | 5,233 | 2025-12-31 | PYPL_10K_2025-12-31.pdf | 105 |
| f5 | COF | net_income | 2,453 | 2025-12-31 | COF_10K_2025-12-31.pdf | 146 |

### T28 · cross_filing · five balance sheets, compare (close call, Intel vs NVIDIA)

**Q:** Which of the five chip companies (NVIDIA, AMD, Intel, Qualcomm, Broadcom) had the largest total assets at its latest balance sheet date?

**Gold answer:** INTC

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | NVDA | total_assets | 206,803 | 2026-01-25 | NVDA_10K_2026-01-25.pdf | 85 |
| f2 | AMD | total_assets | 76,926 | 2025-12-27 | AMD_10K_2025-12-27.pdf | 88 |
| f3 | INTC | total_assets | 211,429 | 2025-12-27 | INTC_10K_2025-12-27.pdf | 103 |
| f4 | QCOM | total_assets | 60,829 | 2026-09-27 | QCOM_10K_2026-09-27.pdf | 87 |
| f5 | AVGO | total_assets | 171,092 | 2025-11-02 | AVGO_10K_2025-11-02.pdf | 83 |

### T29 · cross_filing · two income statements, difference

**Q:** How much larger were Home Depot's net sales than Lowe's net sales in their latest fiscal years?

**Gold answer:** $78,397 million  (= f1 - f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | HD | revenue | 164,683 | 2026-02-01 | HD_10K_2026-02-01.pdf | 73 |
| f2 | LOW | revenue | 86,286 | 2026-01-30 | LOW_10K_2026-01-30.pdf | 69 |

### T30 · cross_filing · Item 1 prose across five filings (inverse relation lookup)

**Q:** Which companies in the corpus name TSMC as a foundry or manufacturing partner in their 10-K?

**Gold answer:** NVDA, AMD, INTC, QCOM, AVGO

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| r1 | NVDA | supplied_by → TSMC | "Taiwan Semiconductor Manufacturing Company Limited, or TSMC" |  | NVDA_10K_2026-01-25.pdf | 12 |
| r2 | AMD | supplied_by → TSMC | "Taiwan Semiconductor Manufacturing Company Limited (TSMC)" |  | AMD_10K_2025-12-27.pdf | 18 |
| r3 | INTC | supplied_by → TSMC | "third-party foundries, particularly TSMC" |  | INTC_10K_2025-12-27.pdf | 10 |
| r4 | QCOM | supplied_by → TSMC | "Taiwan Semiconductor Manufacturing Company (TSMC)" |  | QCOM_10K_2026-09-27.pdf | 12 |
| r5 | AVGO | supplied_by → TSMC | "Taiwan Semiconductor Manufacturing Company Limited" |  | AVGO_10K_2025-11-02.pdf | 15 |

## dev set (14 questions)

### D01 · single_fact · 

**Q:** What was IBM's total revenue in 2025?

**Gold answer:** $67,535 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | IBM | revenue | 67,535 | 2025-12-31 | IBM_10K_2025-12-31_EX13.pdf | 44 |

### D02 · single_fact · 

**Q:** Who is Cisco's independent auditor?

**Gold answer:** PricewaterhouseCoopers LLP

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | CSCO | audited_by → PricewaterhouseCoopers LLP | "PricewaterhouseCoopers LLP" |  | CSCO_10K_2026-07-25.pdf | 95 |

### D03 · multi_hop · 

**Q:** What was Intel's operating margin in 2025?

**Gold answer:** -4.19%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | INTC | operating_income | (2,214) | 2025-12-27 | INTC_10K_2025-12-27.pdf | 101 |
| f2 | INTC | revenue | 52,853 | 2025-12-27 | INTC_10K_2025-12-27.pdf | 101 |

### D04 · multi_hop · 

**Q:** What was Target's free cash flow in fiscal 2025 (cash provided by operating activities minus expenditures for property and equipment)?

**Gold answer:** $2,835 million  (= f1 - f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | TGT | operating_cash_flow | 6,562 | 2026-01-31 | TGT_10K_2026-01-31.pdf | 50 |
| f2 | TGT | capex | 3,727 | 2026-01-31 | TGT_10K_2026-01-31.pdf | 50 |

### D05 · cross_filing · 

**Q:** Rank Johnson & Johnson, Pfizer, Merck, AbbVie and Eli Lilly by revenue in 2025, highest first.

**Gold answer:** JNJ > LLY > MRK > PFE > ABBV

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | JNJ | revenue | 94,193 | 2025-12-28 | JNJ_10K_2025-12-28.pdf | 52 |
| f2 | PFE | revenue | 62,579 | 2025-12-31 | PFE_10K_2025-12-31.pdf | 109 |
| f3 | MRK | revenue | 65,011 | 2025-12-31 | MRK_10K_2025-12-31.pdf | 136 |
| f4 | ABBV | revenue | 61,160 | 2025-12-31 | ABBV_10K_2025-12-31.pdf | 92 |
| f5 | LLY | revenue | 65,179 | 2025-12-31 | LLY_10K_2025-12-31.pdf | 83 |

### D06 · single_fact · 

**Q:** Which companies in the corpus does AMD name as competitors?

**Gold answer:** INTC, NVDA, AVGO, QCOM

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| r1 | AMD | competes_with → INTC | "Intel Corporation (Intel)" |  | AMD_10K_2025-12-27.pdf | 17 |
| r2 | AMD | competes_with → NVDA | "Nvidia Corporation" |  | AMD_10K_2025-12-27.pdf | 17 |
| r3 | AMD | competes_with → AVGO | "Broadcom Corporation" |  | AMD_10K_2025-12-27.pdf | 18 |
| r4 | AMD | competes_with → QCOM | "Qualcomm Incorporated" |  | AMD_10K_2025-12-27.pdf | 18 |

### D07 · multi_hop · 

**Q:** What was Salesforce's revenue per employee in fiscal 2026?

**Gold answer:** $0 million  (= f1 / f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | CRM | revenue | 41,525 | 2026-01-31 | CRM_10K_2026-01-31.pdf | 97 |
| f2 | CRM | employees | 83,334 | 2026-01-31 | CRM_10K_2026-01-31.pdf | 18 |

### D08 · cross_filing · 

**Q:** Of the companies in the corpus that AMD names as competitors, which had the highest revenue in its latest fiscal year?

**Gold answer:** NVDA

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| r1 | AMD | competes_with → INTC | "Intel Corporation (Intel)" |  | AMD_10K_2025-12-27.pdf | 17 |
| r2 | AMD | competes_with → NVDA | "Nvidia Corporation" |  | AMD_10K_2025-12-27.pdf | 17 |
| r3 | AMD | competes_with → AVGO | "Broadcom Corporation" |  | AMD_10K_2025-12-27.pdf | 18 |
| r4 | AMD | competes_with → QCOM | "Qualcomm Incorporated" |  | AMD_10K_2025-12-27.pdf | 18 |
| f1 | INTC | revenue | 52,853 | 2025-12-27 | INTC_10K_2025-12-27.pdf | 101 |
| f2 | NVDA | revenue | 215,938 | 2026-01-25 | NVDA_10K_2026-01-25.pdf | 83 |
| f3 | AVGO | revenue | 63,887 | 2025-11-02 | AVGO_10K_2025-11-02.pdf | 84 |
| f4 | QCOM | revenue | 43,120 | 2026-09-27 | QCOM_10K_2026-09-27.pdf | 88 |

### D09 · single_fact · 

**Q:** What was Wells Fargo's net interest income in 2025?

**Gold answer:** $47,484 million

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | WFC | net_interest_income | 47,484 | 2025-12-31 | WFC_10K_2025-12-31_EX13.pdf | 135 |

### D10 · multi_hop · 

**Q:** What percentage of Microsoft's total revenue in fiscal 2026 came from "Service and other" revenue?

**Gold answer:** 80.50%  (= f1 / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | MSFT | line_item:Service and other revenue | 267,143 | 2026-06-30 | MSFT_10K_2026-06-30.pdf | 78 |
| f2 | MSFT | revenue | 331,839 | 2026-06-30 | MSFT_10K_2026-06-30.pdf | 78 |

### D11 · multi_hop · 

**Q:** By what percentage did NVIDIA's revenue grow in fiscal 2026 compared with fiscal 2025?

**Gold answer:** 65.47%  (= (f1 - f2) / f2 * 100)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | NVDA | revenue | 215,938 | 2026-01-25 | NVDA_10K_2026-01-25.pdf | 83 |
| f2 | NVDA | revenue | 130,497 | 2025-01-26 | NVDA_10K_2026-01-25.pdf | 83 |

### D12 · cross_filing · 

**Q:** Which companies in the corpus are audited by Deloitte & Touche LLP?

**Gold answer:** MSFT, LOW

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | MSFT | audited_by → Deloitte & Touche LLP | "DELOITTE & TOUCHE LLP" |  | MSFT_10K_2026-06-30.pdf | 134 |
| f2 | LOW | audited_by → Deloitte & Touche LLP | "Deloitte & Touche LLP" |  | LOW_10K_2026-01-30.pdf | 65 |

### D13 · cross_filing · 

**Q:** What was the average research and development expense of NVIDIA, AMD, Intel, Qualcomm and Broadcom in their latest fiscal years?

**Gold answer:** $12,309 million  (= (f1 + f2 + f3 + f4 + f5) / 5)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | NVDA | rd_expense | 18,497 | 2026-01-25 | NVDA_10K_2026-01-25.pdf | 83 |
| f2 | AMD | rd_expense | 8,091 | 2025-12-27 | AMD_10K_2025-12-27.pdf | 86 |
| f3 | INTC | rd_expense | 13,774 | 2025-12-27 | INTC_10K_2025-12-27.pdf | 101 |
| f4 | QCOM | rd_expense | 10,207 | 2026-09-27 | QCOM_10K_2026-09-27.pdf | 88 |
| f5 | AVGO | rd_expense | 10,977 | 2025-11-02 | AVGO_10K_2025-11-02.pdf | 84 |

### D14 · cross_filing · 

**Q:** Which had more total assets at its latest balance sheet date, Costco or Target, and by how much?

**Gold answer:** COST, by $29,555 million  (= f1 - f2)

| fact | company | what | value as printed | period end | doc | page |
|---|---|---|---|---|---|---|
| f1 | COST | total_assets | 89,045 | 2026-08-30 | COST_10K_2026-08-30.pdf | 54 |
| f2 | TGT | total_assets | 59,490 | 2026-01-31 | TGT_10K_2026-01-31.pdf | 49 |
