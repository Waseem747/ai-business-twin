# Security & Governance

## 1. Identity and access

- JWT bearer tokens signed with HMAC-SHA256; password hashes use Argon2id.
- Token claims include user, tenant and role; tokens expire (default 8 hours).
- Roles:

| Role | View | Run workflows / inspect | Edit logic | Approve / activate |
|---|---:|---:|---:|---:|
| VIEWER | ✓ | — | — | — |
| ANALYST | ✓ | ✓ | ✓ | — |
| APPROVER | ✓ | ✓ | — | ✓ |
| ADMIN | ✓ | ✓ | ✓ | ✓ |

- The API resolves the business from the authenticated user's tenant. Business-scoped endpoints verify entity ownership. Credentials management is ADMIN-only.
- The demo login requires a tenant slug; production deployments should resolve tenant by domain/SSO and add MFA.

## 2. Credential handling

- Connector credentials can be stored through `POST /api/integrations/credentials` using AES-256-GCM envelope encryption.
- The key is derived from `CREDENTIAL_ENCRYPTION_KEY` (recommended) or `JWT_SECRET`. Production should use a KMS-backed key and rotation.
- The API returns only masked hints (`••••1234`); ciphertext, nonce and plaintext are never returned.
- Live REST/GraphQL/SQL connectors resolve secrets from environment variables (`auth_env`, `connection_env`). This is deliberate for the MVP; move them into the vault/secret manager and resolve at connector runtime for production.
- SQL data sources accept only one `SELECT`/`WITH` statement and execute in a read-only transaction. Production must use a dedicated read-only database role, statement timeouts and an egress allow-list.
- Google Sheets access is read-only. Link-shared sheets need no credential; private access uses a service-account JSON or API key in the backend environment. Sheets are untrusted tabular input and are validated like any other source.
- REST, SQL and Google connectors can make outbound requests. In a hostile network environment, restrict connector targets to approved domains/hosts and block private-network SSRF targets.
- `.env` is git-ignored. Never commit connector tokens.

## 3. Untrusted input

Treated as untrusted:

- external API responses;
- uploaded CSV/Excel workbooks;
- Excel formulas;
- emails and document text;
- LLM output.

Controls:

- Raw payloads are written before validation and never overwritten.
- Numeric validation rejects non-finite values, negative amounts where invalid, missing values and future periods.
- Excel formulas are parsed and translated; formulas are never executed by Excel or `eval`.
- Unsupported functions and external references are excluded and flagged.
- Generated Python passes an AST allow-list and runs in a separate process with a timeout.
- LLM prompts are constructed from computed facts; model output is treated as text and cannot feed action parameters or financial fields.

## 4. Prompt injection boundary

- LLMs only receive structured facts for narrative tasks.
- Decisions are generated from deterministic playbooks and simulation outputs.
- The auditor verdict is computed from deterministic checks.
- No LLM has tool access. Agents call narrow Python services, not arbitrary tools.
- Model output is displayed as "AI interpretation" or "Deterministic narrative" depending on the actual provider.
- A fallback marks the provider and reason; a failed model never blocks the deterministic workflow.

## 5. Rule sandbox

Current controls:

- AST validation blocks imports, dunder attributes, file access, dangerous builtins and class/async constructs.
- Separate Python process (`-I -S`), scrubbed environment, temporary working directory.
- Wall-clock timeout.
- POSIX `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_NOFILE` where available.
- JSON-only input/output and output size cap.
- Formula rules use a whitelisted AST evaluator, not `eval`.

Limitations:

- This is process isolation, not a hardened VM. On Windows no OS-level memory limit is applied.
- A malicious user with rule-authoring permission could still consume CPU up to the timeout.
- Production multi-tenant rule execution must run in gVisor / Firecracker or a dedicated sandbox service with no network and a read-only filesystem, plus per-tenant concurrency budgets.

Only authorized analysts/admins can author rules; only approvers/admins can activate them. The generated Excel rule follows the same path.

## 6. Action governance

- Decisions with projected impact above `HUMAN_APPROVAL_THRESHOLD_USD`, procurement/pricing changes, or implementation cost require human approval.
- The Action Agent verifies decision status and approval row before touching an integration.
- The auditor has no execution tool or permission.
- Idempotency key = deterministic hash of decision + action type; a unique constraint prevents duplicate external operations.
- The current only wired target is a **local simulated ERP**. The action record and UI explicitly state no real external API was called.
- Verification retrieves the external record and compares expected/actual operational state. A successful API response is not treated as a successful business outcome.
- Projected financial impact remains `PENDING_OBSERVATION` until a measured follow-up window exists.

## 7. Simulation isolation

- Simulations read an immutable metric snapshot.
- They write only `scenarios` and `simulations`; no observation or metric is mutated.
- `simulated=true`, `is_simulation=true`, `production_state_modified=false` are persisted and displayed.
- Monte Carlo assumptions and the seed are recorded.
- Best/worst case parameter changes and assumptions are explicit.

## 8. Audit trail

- `audit_logs` records actor, action, entity, before/after and request context. Code inserts and never updates audit rows.
- `business_events` provides an operational timeline.
- Workflow steps, agent executions, rule executions, decisions, reviews, approvals, actions, verifications and reports all carry timestamps and evidence.
- Alert incidents track occurrences, acknowledgement, escalation and resolution. Repeated unresolved alerts are deduplicated by fingerprint; resolved incidents allow a new incident.

## 9. Data protection and retention

MVP:

- Single-tenant demo deployment; database and object storage protected at the infrastructure layer.
- Reports and raw payloads on a mounted volume.
- No PII beyond fictional customer names; no real personal data should be loaded without a DPA and field-level controls.
- Retention is operational: configure volume/database backup retention. Suggested production defaults: raw payloads 90 days, reports 2 years, audit logs 7 years, simulations 1 year, uploaded workbooks 90 days, with legal-hold overrides.

Production requirements:

- Encrypt database and object storage at rest; TLS in transit.
- Signed URL downloads; per-report access checks.
- Data classification and PII field redaction prior to LLM calls.
- Backups, restore drills and retention automation.
- SIEM export for audit logs.

## 10. Reliability and abuse controls

- Per-IP in-memory request rate limiting (default 240/min). Use a shared Redis/gateway limiter for multi-instance.
- API request IDs and standard security headers.
- Upload size limits (25 MB) and extension checks.
- SMTP notifications are only marked `SENT` after SMTP accepts the message; otherwise status is `NOT_CONFIGURED`/`FAILED`.
- Scheduler runs one daily workflow per business with active-run deduplication; `max_instances=1` per job.
- Approval requests expire after 48 hours.
- Workflow retries are scoped to safe nodes; action execution is not automatically retried to prevent duplicate side effects.

## 11. Incident response

1. Disable a source (`DataSource.status`) or connector by configuration.
2. Stop the scheduler or specific jobs.
3. Revoke users/tokens by rotating `JWT_SECRET` (invalidates tokens).
4. Rotate connector credentials through the vault API.
5. Preserve logs, raw payloads and checkpoints.
6. Roll back an activated rule by activating a prior approved `RuleVersion`.
7. For a failed action, inspect the idempotency key and external record before any retry.

## 12. Security backlog

- SSO/OIDC, MFA, tenant-aware login.
- Per-action permission scopes and four-eyes approval for high-value actions.
- Distributed rate limiting and scheduler locking.
- Sandbox VM isolation with network egress controls.
- PostgreSQL row-level security in addition to application scoping.
- Embedding store encryption and data-loss prevention.
- Automated dependency scanning and signed images.
- Immutable/WORM audit storage and SIEM integration.
