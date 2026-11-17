# MVP Acceptance Evidence

This document maps the original MVP acceptance criteria to working evidence. All demo values are fictional and all simulated sources are labelled.

## Acceptance checklist

| # | Criterion | Evidence |
|---|---|---|
| 1 | One business with predefined operational data | `Northwind Retail Co.` tenant seeded with units, departments, customers, suppliers, products, inventory, projects, budgets |
| 2 | At least two external or simulated data sources | Northwind POS (simulated), Northwind ERP (simulated) and a real read-only SQL query against a demo marketing warehouse, ~292 facts on bootstrap; CSV/XLSX, Google Sheets and REST/GraphQL connectors implemented |
| 3 | One Excel workbook with actual formulas | `backend/data/demo/Northwind_Margin_Model.xlsx`, 24 formulas, named ranges, cross-sheet refs, SUMIFS/VLOOKUP/INDEX-MATCH |
| 4 | Successful conversion of supported Excel logic | 21 outputs converted; 84/84 comparisons against independent Excel calculation engine across 4 datasets |
| 5 | Working custom business rule registry | 11 seeded rules + activated Excel rule; sandbox, tests, versions, approval, execution console |
| 6 | Data acquisition agent | `data_acquisition` with source sync, pagination-capable REST, retries, lineage, dedup, freshness |
| 7 | Transformation agent | Currency normalization, channel standardization, zero-revenue flagging; raw data untouched |
| 8 | Business intelligence agent | Margin decline, cost pressure, z-score anomaly, discount risk, cash runway, customer/inventory findings with classified evidence |
| 9 | Decision-making agent | Six simulated alternatives, deterministic ranking, chosen supplier/discount/price intervention with evidence |
| 10 | Independent decision auditor | Recomputes baseline from raw values, compares impact to simulation, checks cash, affordability, assumptions, data quality and Monte Carlo; verdict + conditions |
| 11 | Action execution agent | Approval gate, parameter validation, idempotency key, simulated-ERP request, immutable audit event |
| 12 | Execution verification agent | Retrieves simulated external record, diffs expected/actual, verifies operational state; business impact remains pending measurement |
| 13 | Reporting agent | Daily executive summary, exception report, decision report, simulation report record; PDF/XLSX/CSV |
| 14 | Business simulation agent | Snapshot-isolated deterministic model, best/base/worst, sensitivity, Monte Carlo, backtest, saved scenarios |
| 15 | Scheduled daily executive report | APScheduler cron (default 07:00 UTC) and manual daily cycle; reports generated in Workflow A |
| 16 | Critical business anomaly alert | Gross margin fell 3.1pp; CRITICAL alert with dedup fingerprint, evidence, acknowledgement/escalation |
| 17 | Dashboard displaying agent activity and decisions | Enterprise UI with Business Overview, Agent Control Center, Decision Center, Reports/Alerts, Simulation, Logic Studio, Integrations |
| 18 | Complete audit trail | `audit_logs`, business events, workflow steps, agent/rule executions, decision reviews, action/verification records |

## Demonstrated scenario

**Trigger:** October gross margin fell to 31.05% from 34.20% in September; COGS rose to 69.0% of revenue; supplier cost index reached 120.3; discount depth 11.8%.

1. **Retrieve** — POS/ERP connectors sync; raw payload files and ingestion lineage are written.
2. **Validate** — finite values, non-negative amounts, no future periods; duplicates blocked; rejected counts recorded.
3. **Transform** — deterministic currency/channel normalization; originals retained.
4. **Calculate** — gross margin, net margin, runway, DSO, inventory days executed by the rule registry in a sandbox; twin snapshot persisted.
5. **Identify** — BI agent records confirmed facts, statistical anomaly, potential risks, hypotheses and data-quality state.
6. **Investigate** — evidence attributes include COGS ratio, supplier index, discount depth, channel mix and cash.
7. **Recommend** — six alternatives are simulated and ranked deterministically. The chosen discount-discipline intervention projects +$243,159 12-month net profit (example bootstrap; values vary with the current model version).
8. **Simulate** — monthly baseline/scenario, P10/P50/P90 Monte Carlo, cash floor, best/base/worst and sensitivity are persisted.
9. **Audit** — auditor recomputes baseline margin from revenue/COGS; verifies impact ties to simulation; checks policy, cash, affordability, data quality and uncertainty; returns `APPROVED_WITH_CONDITIONS` with legal review + human approval conditions.
10. **Authorise** — LangGraph interrupts. The CFO reviews evidence and conditions, writes a comment and approves. The checkpoint resumes.
11. **Execute** — Action Agent confirms approval, applies idempotency and creates a simulated ERP operations request. No external system is called.
12. **Verify** — Verification Agent retrieves the simulated record, checks expected vs actual, and records `business_impact.status = PENDING_OBSERVATION`.
13. **Report** — a decision report and refreshed daily executive report include the event, execution and verification state, with projected vs measured separated.

## Test command

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
# 31 passed
```

The integration test `tests/test_workflows.py::test_full_decision_and_excel_acceptance_scenario` executes the full path, including human approval, action verification and Excel rule activation.
