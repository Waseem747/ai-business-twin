# Architecture

## 1. Design principles

1. **The LLM interprets; Python calculates.** Every financial and operational figure comes from validated observations and deterministic logic. Narrative providers are optional and cannot invent figures, select actions or approve anything.
2. **Category separation.** Observed actuals, calculated metrics, AI interpretation, proposed decisions, simulations and executed actions live in separate tables and carry explicit classification.
3. **Evidence over narrative.** Findings, decisions and reports embed references to source observations, rule executions and snapshots.
4. **Independent control.** The auditor has read-only evidence access, its own recalculation path and no action tools. Approval is a workflow interrupt, not a chat message.
5. **Isolation by default.** Custom code runs in a separate process with an AST allow-list. Simulation reads snapshots and writes only simulation records.
6. **Extensibility without editing agents.** Data sources, rules, KPIs, policies and schedules are configuration/data; agents invoke capabilities through typed services.

## 2. Runtime components

```text
React + TypeScript (Vite) ── /api ──► FastAPI (JWT, RBAC, tenant resolver)
                                      │
                        ┌─────────────┼────────────────────────────┐
                        ▼             ▼                            ▼
                 LangGraph runner   Service layer              APScheduler
                 + checkpointer     (deterministic)           (daily + freshness)
                        │             │
                        ▼             ▼
                 Workflow A-D      SQLAlchemy async ORM ── SQLite (local) / PostgreSQL
                        │
         ┌──────────────┼──────────────────────────────┐
         ▼              ▼                              ▼
   Agent executions  Rule executions              Reports / artifacts
```

- **API:** `backend/app/api/routes/*`
- **Workflows:** `backend/app/workflows/graphs.py` defines all nodes and conditional edges.
- **Runner:** `backend/app/workflows/runner.py` starts background tasks, persists state on every streamed update, detects `__interrupt__`, and resumes with `Command(resume=...)`.
- **Checkpointing:** `backend/app/workflows/checkpointer.py` uses `AsyncSqliteSaver`; a PostgreSQL checkpointer can replace it without changing graph code.
- **Agents:** `backend/app/agents/` contains ten narrow agents plus the model gateway. Each has declared permissions, tools, telemetry and structured outputs.
- **Connectors:** REST, GraphQL, read-only SQL (PostgreSQL/MySQL/SQLite), Google Sheets, CSV/Excel and simulated demo sources. All feed the same validation, deduplication, raw-lineage and transformation pipeline.
- **Determinism:** `logic/kpis.py`, `logic/expressions.py`, `logic/registry.py`, `simulation/model.py` contain no LLM calls.

## 3. Data model

Core tables (see `domain/models.py`):

- Organisation: `tenants`, `users`, `businesses`, `business_units`, `departments`, `employees`, `customers`, `suppliers`, `products`, `inventory_items`, `projects`, `budgets`.
- Acquisition: `data_sources`, `credentials`, `ingestion_runs`, `observations`, `transformations`, `transformation_runs`.
- Logic: `business_rules`, `rule_versions`, `rule_executions`.
- Twin: `metric_snapshots`, `business_metrics`.
- Agents/workflows: `agents`, `agent_executions`, `workflow_runs`, `workflow_steps`.
- Decisions: `decisions`, `decision_reviews`, `approvals`, `business_actions`, `action_verifications`, `mock_external_records`.
- Simulation: `scenarios`, `simulations`.
- Operations: `alerts`, `alert_events`, `notifications`, `reports`, `business_events`, `audit_logs`.
- Conversion: `excel_conversions`, `knowledge_documents`.

### Observation lineage

1. Connector fetches source data.
2. Raw payload is written to `storage/raw/<source_id>/<run_id>.json` **before** validation.
3. `IngestionRun` records connector version, cursor, schema, counts, rejection reasons, duplicate count, freshness and raw path.
4. Valid facts become immutable `observations` with a deterministic `dedup_key`.
5. Transformations update only the normalized layer; original values are preserved under `quality.original_*`.
6. The twin builder aggregates monthly actuals and computes KPIs. Each snapshot stores `lineage.input_refs` with observation IDs and sources.

Missing values are `null`. They are never converted to zero in KPI calculations. Validation rejects non-finite values, negative amounts/counts and future periods.

## 4. Deterministic business logic

The KPI library calculates gross profit/margin, opex, net profit, runway, inventory turnover/days, DSO, marketing ratio and a transparent weighted health score.

Custom rules execute through `RuleRegistry`:

- Source types: `PYTHON` and `FORMULA`; Excel-converted rules are `EXCEL`.
- Python rules must expose `calculate(inputs: dict) -> dict`.
- AST validation blocks imports, file access, dunder access and dangerous builtins.
- Execution happens in a separate isolated Python process with a timeout, JSON-only I/O and output size limit; POSIX resource limits are applied where available.
- Tests run before version activation. Activation requires an ADMIN/APPROVER and stores an immutable `RuleVersion`.
- Rule executions record inputs, outputs, duration, sandbox flag and trace.

**Formula engine:** `logic/expressions.py` supports arithmetic, comparisons, booleans, ternaries and whitelisted functions. It rejects unknown variables and division by zero.

**Simulation arithmetic:** `simulation/model.py` is a transparent monthly retail model with explicit assumptions. It never calls an LLM. Marketing uses a diminishing-returns elasticity; price uses a retail-share weighted volume elasticity; discounts adjust realised price and volume; supplier costs adjust COGS. Best/worst cases adjust elasticities and cost realisation explicitly. Monte Carlo samples documented distributions and records the seed. Backtesting validates the baseline growth assumption only and says so.

## 5. Agent responsibilities and permissions

| Agent | Key | Permissions | Cannot do |
|---|---|---|---|
| Data Acquisition | `data_acquisition` | source.read, data.ingest, credential.use | Approve or execute business actions |
| Transformation | `transformation` | observation.read/transform, transformation.registry | Alter raw payloads |
| Business Logic Engine | `business_logic` | rule.execute, snapshot.write | Call an LLM for math |
| Business Intelligence | `business_intelligence` | metrics.read, evidence.read, findings.write | Modify metrics |
| Decision-Making | `decision` | metrics.read, simulation.read/decision.write | Invent figures; execute |
| Independent Auditor | `auditor` | evidence.read, decision.read, review.write | Execute actions; edit decision evidence |
| Business Simulation | `simulation` | snapshot.read, simulation.write | Write production observations/metrics |
| Action Execution | `action_execution` | action.execute_approved, integration.write | Act without approval; bypass idempotency |
| Execution Verification | `execution_verification` | external.read, verification.write | Modify the action result |
| Reporting | `reporting` | report.read/write, notification.send | Alter source data |

Agent executions store input/output summaries, evidence references, duration, error, and the actual model provider (including fallback reason).

## 6. Decision lifecycle (Workflow B)

```text
intake
  └─► decision (6 deterministic alternatives, each simulated)
        └─► audit (recompute baseline, verify impact, policy, cash, data quality, MC)
              ├─ REJECTED ──► revise (max 2) ──► audit … ──► human escalation
              ├─ REQUIRES_HUMAN_REVIEW ──► interrupt
              └─ APPROVED / APPROVED_WITH_CONDITIONS
                    ├─ approval required ──► interrupt
                    └─ auto authorised ──► action
approval resume ──► action (approval + idempotency required)
  └─► verification (operational state vs expected)
        └─► business state update (projected vs measured recorded)
              └─► decision report + refreshed daily report
                    └─► notification
```

An approval is a database row plus a LangGraph interrupt. The UI records the approver, comment and timestamp; the graph resumes from the same checkpoint. A rejected recommendation never reaches the Action Agent.

## 7. Reliability

- **RetryPolicy** on ingestion, transformation and simulation nodes.
- **Timeouts** in sandbox, REST connector, approval expiry and scheduler task constraints.
- **Idempotency** at action level (unique key) and ingestion level (unique dedup key).
- **Workflow checkpoints** after every update; run state persisted for the control center.
- **Incident dedup** by fingerprint; occurrences, acknowledgement, escalation and resolution are tracked.
- **Failure surfacing:** errors are stored on the workflow, step and agent execution; failed actions mark the decision failed; no fake success path.

## 8. Extension points

- Add a connector by implementing `Connector.fetch` and registering it in `CONNECTORS`.
- Add an agent by declaring an `AgentProfile` and wrapping a deterministic service; add it to a graph node.
- Add a KPI/rule through Logic Studio or seed it in `logic/seed_rules.py`.
- Add a scenario driver by extending `DEFAULT_PARAMETERS`, validation ranges and the model’s explicit transfer functions.
- Swap SQLite for PostgreSQL by changing `DATABASE_URL`; tables are portable.
- Swap the checkpointer for `langgraph-checkpoint-postgres` in `workflows/checkpointer.py`.
- Add an integration target in `services/actions.py` with idempotency, verification and permissions.

## 9. Known architectural limitations

- The MVP uses a single FastAPI process for API + scheduler; horizontal scaling requires a distributed scheduler lock and shared rate limiter.
- Checkpoints default to SQLite. Production multi-instance deployments should use PostgreSQL.
- The local ERP target is a simulator; adapters must be written for real systems.
- Rule source type `SQL` is intentionally disabled; no read-only analytics replica is configured.
- Historical reconstruction is snapshot-based, not event-sourced.
