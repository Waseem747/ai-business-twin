# AI Business Twin

**Autonomous multi-agent business intelligence, decision and simulation platform.**

A production-oriented reference implementation of a digital business twin: it continuously ingests operational data, calculates business performance with deterministic logic, investigates anomalies, audits recommended interventions, simulates alternatives, executes only authorised actions, verifies the operational result and reports to management.

> **Demo data notice.** The bundled Northwind Retail Co. company is fictional. Its POS and ERP feeds are deterministic simulated connectors and are labelled `SIMULATED` end-to-end. A third source reads demo marketing data through the **real read-only SQL connector** from a local SQLite warehouse. The local "ERP" action target is an integration simulator. No external business system is presented as live.

![Business Overview](docs/screenshots/overview.png)

| Decision Center | Simulation |
|---|---|
| ![Decision Center](docs/screenshots/decisions.png) | ![Simulation](docs/screenshots/simulation.png) |

---

## 1. What is implemented

### Working MVP scope

| Capability | Status | Evidence |
|---|---|---|
| Multi-tenant business model and digital twin entities | Implemented | `backend/app/domain/models.py` |
| Simulated POS + ERP, real SQL query against a demo marketing warehouse, CSV/Excel ingestion \| Implemented | 292 validated facts on first seed |
| REST / GraphQL / SQL database / Google Sheets / CSV / Excel connectors | Implemented | `backend/app/connectors/` |
| Raw payload lineage, schema snapshots, deduplication, validation | Implemented | `IngestionRun.lineage`, unique observation dedup keys |
| Transformation registry with original-value retention | Implemented | `services/transformation.py` |
| Deterministic KPI engine + persistent snapshots | Implemented | `services/twin_state.py`, `logic/kpis.py` |
| Business rule registry with sandbox, tests, versions, approval | Implemented | `logic/registry.py`, Logic Studio |
| Excel-to-Python conversion | Implemented | 24 formulas inspected; 21 outputs translated; **84 / 84 comparisons passed across 4 datasets** |
| Unsupported formula and circular-reference detection | Implemented | HLOOKUP flagged; circular pair detected and excluded |
| Business Intelligence Agent | Implemented | Z-score, trend, ratio and policy anomaly detection |
| Decision Agent with ranked alternatives | Implemented | Six deterministic playbooks evaluated by simulation |
| Independent Decision Auditor | Implemented | Independent baseline recomputation, policy, cash, quality and uncertainty checks |
| Human approval interruption + checkpoint resume | Implemented | LangGraph `interrupt()` + SQLite checkpointer |
| Action Agent with idempotency and approval gate | Implemented | Simulated ERP request; immutable audit trail |
| Execution Verification Agent | Implemented | Operational verification; projected vs measured separation |
| Business Simulation Agent | Implemented | Deterministic, best/base/worst, sensitivity, Monte Carlo, baseline backtest |
| Alerts with deduplication / acknowledgement / escalation | Implemented | Incident fingerprint + occurrence tracking |
| Reporting Agent | Implemented | Daily executive, exception, decision and simulation records; PDF / Excel / CSV |
| LangGraph workflows A–D | Implemented | `backend/app/workflows/graphs.py` |
| JWT authentication and RBAC (ADMIN, APPROVER, ANALYST, VIEWER) | Implemented | `core/security.py` |
| Agent control center, logic studio, decision center, simulation, reports, integrations | Implemented | React + TypeScript + Plotly enterprise UI |
| Automated tests | Implemented | `31 passed` |
| Docker + PostgreSQL/pgvector deployment | Implemented | `docker-compose.yml` |
| Encrypted credential vault | Implemented | AES-256-GCM metadata API (`/api/integrations/credentials`) |

### Live demo screenshot gallery

- [Login](docs/screenshots/login.png)
- [Agent Control Center](docs/screenshots/agents.png)
- [Business Logic Studio](docs/screenshots/logic.png)
- [Alert Register](docs/screenshots/alerts.png)
- [Data Integrations](docs/screenshots/integrations.png)

---

## 2. Architecture

```text
                       ┌───────────────────────────────┐
Human approval  ◄──────│  LangGraph Workflows A / B / C / D │──────► Checkpoints
                       └───────────────┬───────────────┘
                                       │
   External / simulated sources        │
 ┌─────────────┐   ┌─────────────┐     ▼
 │ POS / REST  │   │ ERP / CSV   │  Acquisition → Validation → Transformation
 │ Excel upload│   │ GraphQL     │     │
 └─────────────┘   └─────────────┘     ▼
                              Business Logic Engine (sandboxed rules + formula engine)
                                       │
                                       ▼
                              Digital Twin Snapshot (actual / calculated)
                                       │
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
          Business Intelligence                    Simulation Engine
       (facts / anomalies / hypotheses)       (scenario, sensitivity, Monte Carlo)
                     │                                   │
                     ▼                                   │
             Decision Agent ──► Independent Auditor ──► Human approval
                     ▲                  │                   │
                     └──── revise ──────┘                   ▼
                                                     Action Agent / idempotency
                                                             │
                                                             ▼
                                                  Execution Verification Agent
                                                             │
                                                             ▼
                                              Reporting / daily executive report
```

### Category separation

The platform never mixes these categories:

| Category | Storage |
|---|---|
| Actual observed data | `observations` (raw payload retained on disk) |
| Calculated metrics | `metric_snapshots`, `business_metrics`, `rule_executions` |
| AI interpretation | findings/narratives attached to intelligence and agent executions |
| Proposed decisions | `decisions`, `decision_reviews`, `approvals` |
| Simulated projections | `simulations`, `scenarios` (`simulated=true`) |
| Executed actions | `business_actions`, `action_verifications` |
| Audit trail | `audit_logs` (insert-only convention), `business_events` |

### LangGraph workflows

| Workflow | Nodes | Key characteristics |
|---|---|---|
| A · Daily BI | Acquisition → Validation → Transformation → Business Logic → BI → Anomaly/Alerts → Reporting → Notification | Retries on ingestion/transform; deduplicated incidents; PDF/XLSX/CSV output |
| B · Decision & Execution | Intake → Decision → Auditor → *(revise loop)* → Human interrupt → Action → Verification → State update → Reports | Max audit rounds, escalation to human, checkpoint resume, idempotent execution |
| C · Simulation | Baseline → Simulate → Compare → Report | Isolated snapshot; no production writes; persisted scenario |
| D · Excel Conversion | Inspect → Translate → Validate → Human interrupt → Registry | Unsupported formulas/cycles flagged; Excel-engine comparison; approval required |

Every run is a `WorkflowRun` with a `thread_id` and durable checkpoint. Workflow steps, agent executions and outputs are queryable from the UI and API.

---

## 3. Quick start (local, no external credentials)

Prerequisites: **Python 3.12+**, **Node 20+**.

```powershell
# from the repository root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

copy .env.example .env
# edit .env and set a long random JWT_SECRET (and optionally CREDENTIAL_ENCRYPTION_KEY)

# Terminal 1 — API
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — UI
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. API docs: **http://localhost:8000/api/docs**.

On the first start with an empty database the platform:
1. creates the Northwind Retail demo tenant, users, business entities, sources, rules, agents and policies;
2. ingests deterministic POS/ERP data through the real ingestion pipeline;
3. builds the digital twin snapshot;
4. starts the **daily intelligence workflow**, then a **decision workflow** that lands in human approval, and an **Excel conversion workflow** that lands in approval.

This bootstrap takes roughly 20–40 seconds and runs in the background. The UI progressively fills in. Deleted/reset local state lives in `backend/data/runtime/`.

### Demo personas

| Persona | Email | Password | Role |
|---|---|---|---|
| CFO | `cfo@northwind.demo` | `TwinDemo!2026` | APPROVER |
| Analyst | `analyst@northwind.demo` | `TwinDemo!2026` | ANALYST |
| Administrator | `admin@northwind.demo` | `TwinDemo!2026` | ADMIN |
| Viewer | `viewer@northwind.demo` | `TwinDemo!2026` | VIEWER |

> The UI pre-fills the administrator credentials. Switch to the CFO to approve decisions and Excel conversions.

### 5-minute accepted demo flow

1. **Overview** — margin has fallen from 34.2% to 31.1%; a CRITICAL incident and 5 findings are visible. Every KPI links to a validated observation snapshot.
2. **Decision Center** — open the pending recommendation, inspect alternatives, evidence, and the independent audit. The auditor returns `APPROVED_WITH_CONDITIONS` and requires human approval.
3. Add an approval note and click **Approve & execute**. The workflow resumes from its checkpoint, the Action Agent writes an idempotent simulated-ERP request, and the Verification Agent confirms the operational state.
4. Open **Execution** to see the separation between the **projected** 12-month impact and **measured** business impact (`PENDING_OBSERVATION`).
5. **Reports & Alerts** — inspect the refreshed daily executive report and decision report. Download PDF/XLSX/CSV.
6. **Logic Studio → Excel conversion** — see 84/84 cell comparisons, the unsupported HLOOKUP, circular-reference exclusion, generated Python and the business-logic document. Approve to activate the rule.
7. **Simulation** — run the *Margin recovery* preset. Review baseline vs scenario, best/base/worst, Monte Carlo P10/P50/P90, sensitivity and the backtest disclaimer. Production state is never modified.
8. **Agent Control** — inspect all ten agents, permissions, executions and workflow checkpoints.

---

## 4. Docker deployment

Prerequisites: Docker Desktop / Docker Engine with Compose.

```powershell
copy .env.example .env
# set JWT_SECRET, CREDENTIAL_ENCRYPTION_KEY, POSTGRES_PASSWORD
docker compose up --build
```

- UI: **http://localhost:3000**
- API + Swagger: **http://localhost:8000/api/docs**
- PostgreSQL with **pgvector** is provisioned at `localhost:5432`.
- Durable LangGraph checkpoints are stored on the `twin_data` volume (SQLite checkpointer). The checkpoint backend is isolated behind one factory and can be swapped for `langgraph-checkpoint-postgres` without changing graph code.
- The backend container seeds the demo and starts workflows automatically (`DEMO_AUTO_BOOTSTRAP=true`). Set to `false` for a clean production tenant.

### Backup / restore

```bash
# database
docker compose exec postgres pg_dump -U twin business_twin > backup.sql
cat backup.sql | docker compose exec -T postgres psql -U twin business_twin

# uploaded workbooks, reports and raw payloads (the /data volume is mounted in the backend)
docker compose exec backend tar czf - /data > twin_data.tgz
# restore (stop writes first)
docker compose exec -T backend tar xzf - -C / < twin_data.tgz
```

Retention and restore drills are operational procedures; see [Security & governance](docs/SECURITY.md).

---

## 5. Configuration

All configuration is environment-driven. See `.env.example`. Key values:

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | SQLite file | `postgresql+asyncpg://...` in Docker |
| `JWT_SECRET` | dev placeholder | **must be changed** |
| `CREDENTIAL_ENCRYPTION_KEY` | falls back to JWT secret | credential vault key |
| `LLM_PROVIDER` | `deterministic` | `deterministic`, `openai`, `ollama` |
| `LLM_MODEL` / `OLLAMA_MODEL` | `gpt-4.1-mini` / `llama3.1:8b` | narrative model only |
| `HUMAN_APPROVAL_THRESHOLD_USD` | `5000` | approval policy threshold |
| `MAX_AUDIT_ROUNDS` | `2` | revision limit before human escalation |
| `SANDBOX_TIMEOUT_SECONDS` | `8` | rule execution timeout |
| `DATA_STALE_AFTER_HOURS` | `48` | freshness threshold |
| `SCHEDULER_ENABLED` | `true` | APScheduler in API process |
| `DAILY_REPORT_CRON_HOUR` / `MINUTE` | `7` / `0` | daily workflow time (UTC by default) |
| `DEMO_MODE` / `DEMO_AUTO_BOOTSTRAP` | `true` | demo data and one-time workflow bootstrap |

The model gateway only produces narrative text. **Business figures never come from an LLM.** With no provider credentials the platform uses a deterministic narrative template and clearly labels it.

---

## 6. Project structure

```text
backend/
  app/
    agents/          ten agent implementations, registry, permissions, model gateway
    api/             FastAPI routers, schemas and serializers
    connectors/      REST, GraphQL, SQL database, Google Sheets, tabular and simulated connectors
    core/            security, sandbox, credentials encryption, audit helper
    domain/          SQLAlchemy business-twin models and enums
    excel/           inspector, formula translator, codegen, Excel comparator, registry bridge
    logic/           KPI library, formula evaluator, rule registry and seed rules
    services/        ingestion, transformation, twin state, decisions, audit, actions,
                     verification, alerts, reporting, scheduler, approvals, seed
    simulation/      deterministic model, sensitivity, Monte Carlo, backtest, persistence
    workflows/       typed state, checkpointer, graphs A–D, runner
  data/demo/         Northwind_Margin_Model.xlsx
  scripts/           deterministic demo workbook builder
  tests/             31 unit + integration tests
frontend/
  src/pages/         overview, agents, decision center, simulation, logic studio, reports, integrations
  src/components/    enterprise design system, Plotly chart wrapper, layout, toasts
docs/                architecture, Excel conversion reference, security & governance
infra/               pgvector bootstrap SQL
docker-compose.yml
```

---

## 7. Extending to a real business

No core agent code needs to change.

1. **Business and entities** — create `Business`, units, departments and reference data (tenant-scoped).
2. **Data sources**
   - **SQL databases:** use **Data Integrations → Connect source → SQL database**. The connector supports PostgreSQL (`asyncpg`), MySQL (`asyncmy`) and SQLite (`aiosqlite`) through an async SQLAlchemy URL held in an environment variable. It enforces a single `SELECT`/`WITH` statement and opens a read-only transaction. Use a read-only database role. Example:
     ```env
     ANALYTICS_DATABASE_URL=postgresql+asyncpg://readonly_user:password@db-host:5432/analytics
     ```
     The UI sends only the environment-variable name, never the secret.
   - **Google Sheets:** paste a spreadsheet URL/ID and a sheet or A1 range. Link-shared sheets work through a read-only CSV export; private sheets use `GOOGLE_SHEETS_API_KEY` or a service-account JSON in `GOOGLE_SERVICE_ACCOUNT_JSON`. Only the read-only Sheets scope is requested.
   - **REST / GraphQL:** configure a base URL, path, field mapping and an `auth_env` secret reference. The REST connector supports page/offset/cursor pagination, rate-limit backoff, retries and raw-payload lineage.
   - **CSV / Excel:** upload with an explicit column mapping, or select a workbook in Logic Studio.
   - Configure real POS/ERP credentials through environment secret references or the encrypted credential vault. The simulated demo sources must not be enabled for a real tenant.
   - After creating a source, the UI can **Test connection** (returns schema and sample mapped facts) before creating and syncing it.
3. **Business logic** — create and test rules in Logic Studio, or convert an Excel workbook and approve activation. Inputs/outputs are typed JSON schemas; rules are versioned and sandboxed.
4. **KPI targets** — adapt the twin builder/policy thresholds to the business; the platform’s health score and KPI library are explicit and testable.
5. **Agent workflows** — schedule Workflow A, trigger Workflow B from an alert or API, and expose workflow state in any UI.
6. **Approvals** — thresholds and conditions are policy data, not prompt text.

See [Architecture](docs/ARCHITECTURE.md) for extension points and [Excel conversion](docs/EXCEL_CONVERSION.md) for function coverage.

---

## 8. Testing

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Current result: **31 passed**, covering:

- sandbox allow-list, blocked imports/file access/dunder access, timeout, null-vs-zero guards;
- deterministic KPI and formula semantics;
- SQL read-only transaction enforcement, write-query rejection, Google Sheets URL parsing and row mapping;
- API connector test, source creation/sync, and rejection of plain-text secret configuration;
- workbook inspection, unsupported functions, cycles, generated Python, **real Excel-engine comparison** (not unchecked equality);
- simulation non-proportionality, best/base/worst ordering, determinism, cash constraints, input immutability, backtest;
- full acceptance workflow: daily BI → critical alert → decision → simulation → audit → human approval → action → verification → reports → Excel validation → human approval → rule activation;
- JWT authentication, tenant-scoped API access and RBAC denial.

---

## 9. Production readiness and known limitations

This is an **MVP reference implementation**, not a claim of turnkey production certification. Known limitations and the intended hardening path:

| Area | Current MVP | Production hardening |
|---|---|---|
| Demo sources | POS/ERP are deterministic simulated connectors; the marketing warehouse is demo data queried through the real SQL connector | Configure real connectors; disable demo seeding |
| Action target | Local simulated ERP; no external write is claimed | Implement per-system adapters with real credentials, circuit breakers and confirmations |
| Sandbox | Separate process, AST allow-list, timeout, POSIX resource limits, scrubbed env | gVisor / Firecracker / dedicated sandbox service with no network, read-only FS |
| SQL data connector | PostgreSQL / MySQL / SQLite read-only, one statement, `SELECT`/`WITH` only; no SQL Server driver yet | Add drivers as required, query allow-lists, statement timeouts, egress allow-list |
| Google Sheets | Public CSV, API key or service-account read; no write access | Domain allow-list, OAuth consent per tenant, quota monitoring |
| SQL rules | Rule source type reserved but execution disabled for safety | Read-only analytics replica + statement budget/allow-list |
| Vector store | pgvector provisioned; policy documents seeded; retrieval is lexical in MVP | Add embeddings + pgvector HNSW index and retrieval evaluation |
| Background processing | APScheduler inside a single API process | Dedicated scheduler/worker, distributed lock, Celery/Redis or equivalent |
| Migrations | SQLAlchemy `create_all` bootstrap | Alembic migrations + zero-downtime rollout |
| Checkpoint storage | SQLite checkpointer volume | PostgreSQL checkpointer for multi-instance durability |
| Rate limiting | In-memory per-process | Redis / gateway rate limiting |
| Credentials | AES-256-GCM vault API + env secret references | External secret manager, KMS, rotation automation |
| Excel conversion | Deterministic supported subset + Excel-engine tests | Broader function coverage, ambiguities escalated to human review |
| LLM | Deterministic template default; optional OpenAI/Ollama narrative | Evaluation harness, red-team prompt-injection tests, provider failover |
| Reports | PDF/XLSX/CSV artifacts on local volume | Object storage, signed URLs, retention policy |

Additional explicit limitations:

- Financial projections are **simulated**, never measured outcomes. The UI and reports enforce this distinction.
- The demo “approval” write path uses the local simulator. No payment, invoice or contract is sent anywhere.
- The auditor is independent in tools/permissions, but it is still software: it checks evidence, calculations and policy and escalates uncertainty; it is not a licensed audit opinion.
- Excel conversion supports arithmetic, comparisons, IF/IFERROR/IFS, AND/OR/NOT, SUM/SUMIF(S), AVERAGEIF(S), COUNT/COUNTIF(S), MIN/MAX, ROUND*, ABS, INT/MOD/SQRT/EXP/LN/LOG/POWER, VLOOKUP/XLOOKUP, INDEX/MATCH, text concatenation and common text functions. Anything else is flagged.
- Pivot tables are reported and not executed; their source formulas must be modelled explicitly.
- Cross-workbook/external references are detected and excluded.
- Historical reconstruction uses metric snapshots; it is not a full event-sourced replay of every source mutation.
- The platform is a single-tenant deployment per business in the demo, though all data access is tenant-scoped and designed for multi-tenant hosting.

---

## 10. Security & governance

- JWT authentication, Argon2 password hashing, role-based access.
- Tenant-scoped business resolution for every business endpoint.
- Human approval is enforced before actions with impact above the policy threshold, pricing changes and procurement/contract actions.
- The independent auditor cannot execute actions; the action agent refuses unapproved decisions.
- Per-action idempotency keys prevent duplicate execution.
- Immutable-style audit logging (`audit_logs` insert-only by convention) and business event history.
- Raw uploaded files and external payloads are treated as untrusted input; formulas are not executed by Excel itself; generated code is sandboxed.
- Prompt injection boundaries: LLM prompts contain computed facts only; LLM output is narrative and never parsed into financial values or action parameters.
- Credentials are encrypted at rest with AES-256-GCM; the API returns only masked hints.

Read [Security & governance](docs/SECURITY.md) for the threat model, permission matrix and hardening backlog.

---

## 11. Roadmap mapping

| Phase | Delivered in this repository |
|---|---|
| 1 Core Architecture | FastAPI, typed domain/state, agent registry, LangGraph, SQLite/Postgres |
| 2 Data Acquisition | Simulated connectors, real SQL query and Google Sheets connectors, REST/GraphQL/tabular frameworks, lineage, dedup, transformations |
| 3 Business Logic | KPI engine, rule registry, sandbox, tests, versions, Excel conversion + validation |
| 4 Decision Intelligence | BI agent, decision agent, independent auditor, approval schemas/workflow |
| 5 Action Execution | Approval gate, idempotency, simulated ERP adapter, verification, audit trail |
| 6 Business Twin Simulation | Snapshots, deterministic scenarios, best/base/worst, sensitivity, Monte Carlo, backtest |
| 7 Reporting & Monitoring | Scheduled daily run, anomalies, alert dedup/escalation, PDF/Excel/CSV, agent dashboard |
| 8 Production Deployment | Docker Compose, PostgreSQL/pgvector, health checks, encrypted credentials, operational docs |

**Ultimate objective:** a reusable AI Business Twin platform that can monitor, understand, simulate, recommend and execute authorised business operations continuously — with deterministic calculations and independent verification at every step.
