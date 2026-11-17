import { useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Cloud,
  Database,
  FileSpreadsheet,
  Globe2,
  KeyRound,
  Link2,
  Loader2,
  LockKeyhole,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Table2,
  TriangleAlert,
  UploadCloud,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { canRun, useAuth } from "../lib/auth";
import { dateTime, number, relativeTime, statusTone, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useToast } from "../components/Toast";
import {
  Badge,
  Button,
  Card,
  DefinitionList,
  Drawer,
  EmptyState,
  ErrorState,
  JsonBlock,
  LoadingBlock,
  Modal,
  PageHeader,
  Panel,
  StatusBadge,
} from "../components/ui";
import type { Source } from "../lib/types";

export function IntegrationsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const integrations = useApi(api.integrations, []);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<any | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [entity, setEntity] = useState("revenue");
  const [metric, setMetric] = useState("revenue");
  const [connectOpen, setConnectOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  async function sync(source: Source) {
    setSyncing(source.id);
    try {
      const result = await api.syncSource(source.id);
      toast.push(
        result.run.status === "SUCCEEDED"
          ? `${source.name}: ${result.run.records_ingested} new facts ingested, ${result.run.duplicates_blocked} duplicates blocked.`
          : `${source.name}: sync ${result.run.status}. ${result.run.error || ""}`,
        result.run.status === "SUCCEEDED" ? "success" : "danger",
      );
      integrations.refresh();
    } catch (exc: any) {
      toast.push(exc?.message || "Synchronisation failed", "danger");
    } finally {
      setSyncing(null);
    }
  }

  async function upload() {
    if (!uploadFile) return;
    setUploading(true);
    try {
      const result = await api.uploadTabular(uploadFile, entity, metric);
      toast.push(`Upload ingested ${result.run.records_ingested} facts (${result.run.records_rejected} rejected).`, result.run.status === "SUCCEEDED" ? "success" : "danger");
      setUploadOpen(false);
      setUploadFile(null);
      integrations.refresh();
    } catch (exc: any) {
      toast.push(exc?.message || "Upload failed", "danger");
    } finally {
      setUploading(false);
    }
  }

  const data = integrations.data;

  return (
    <div className="page">
      <PageHeader
        eyebrow="Foundation · Data lineage"
        title="Data Integrations"
        description="Every business fact enters through a named connector with validation, deduplication, raw payload lineage and freshness tracking."
        meta={
          <div className="header-meta-row">
            <Badge tone="success" dot>{data?.summary?.connected || 0} connected</Badge>
            <Badge tone={(data?.summary?.stale || 0) > 0 ? "warning" : "muted"} dot>{data?.summary?.stale || 0} stale</Badge>
            <Badge tone="violet" dot>{data?.summary?.simulated || 0} simulated</Badge>
            <span className="meta-divider" />
            <span className="meta-text">Credentials are never returned by the API</span>
          </div>
        }
        actions={
          <>
            <Button icon={<RefreshCw size={15} />} onClick={integrations.refresh}>Refresh</Button>
            {canRun(user) && <Button icon={<Plus size={15} />} onClick={() => setConnectOpen(true)}>Connect source</Button>}
            {canRun(user) && <Button variant="primary" icon={<UploadCloud size={15} />} onClick={() => setUploadOpen(true)}>Upload data</Button>}
          </>
        }
      />

      {integrations.loading && !data ? <LoadingBlock lines={9} height={420} /> : integrations.error ? <ErrorState message={integrations.error} onRetry={integrations.refresh} /> : (
        <>
          <div className="integration-summary">
            <Card className="mini-stat"><div className="mini-stat-icon"><Database size={18} /></div><div><span>Sources</span><strong>{data?.sources.length || 0}</strong></div></Card>
            <Card className="mini-stat"><div className="mini-stat-icon"><Activity size={18} /></div><div><span>Facts ingested</span><strong>{number(data?.sources.reduce((total: number, source: Source) => total + (source.records_total || 0), 0), 0)}</strong></div></Card>
            <Card className="mini-stat"><div className="mini-stat-icon"><ShieldCheck size={18} /></div><div><span>Simulated sources</span><strong>{data?.summary.simulated || 0}</strong></div></Card>
            <Card className="mini-stat"><div className="mini-stat-icon"><RefreshCw size={18} /></div><div><span>Recent syncs</span><strong>{data?.recent_ingestions.length || 0}</strong></div></Card>
          </div>

          <div className="notice-strip">
            <LockKeyhole size={15} />
            <span>Raw payloads are stored before validation and never overwritten. Missing values are rejected or flagged — never treated as zero.</span>
          </div>

          <div className="source-grid">
            {(data?.sources || []).map((source) => (
              <Card key={source.id} className="source-card">
                <div className="source-head">
                  <div className={`source-icon ${source.simulated ? "source-simulated" : ""}`}>
                    {source.kind.includes("SIMULATED") ? <Server size={19} /> : source.kind === "SQL_DATABASE" ? <Database size={19} /> : source.kind === "GOOGLE_SHEETS" ? <Table2 size={19} /> : source.kind === "EXCEL" ? <FileSpreadsheet size={19} /> : <Globe2 size={19} />}
                  </div>
                  <div className="source-title"><strong>{source.name}</strong><span>{source.kind} · {source.system || "file"}</span></div>
                  <StatusBadge status={source.status} size="sm" />
                </div>
                <div className="source-badges">
                  {source.simulated && <Badge tone="violet" dot>SIMULATED</Badge>}
                  <Badge tone={source.health?.stale ? "warning" : "success"} dot>{source.health?.stale ? "Stale" : "Fresh"}</Badge>
                  <Badge tone="muted">{(source.records_total || 0).toLocaleString()} facts</Badge>
                </div>
                <div className="source-metrics">
                  <div><span>Freshness</span><strong>{source.health?.age_hours !== null && source.health?.age_hours !== undefined ? `${source.health.age_hours}h old` : "Unknown"}</strong></div>
                  <div><span>Last sync</span><strong>{relativeTime(source.last_sync_at)}</strong></div>
                  <div><span>Records</span><strong>{source.records_total?.toLocaleString() || 0}</strong></div>
                </div>
                {source.last_error && <div className="source-error"><TriangleAlert size={14} /> {source.last_error}</div>}
                <div className="source-foot">
                  <span>{source.freshness_at ? `Data through ${dateTime(source.freshness_at)}` : "No freshness timestamp"}</span>
                  {canRun(user) && <Button size="sm" icon={<RefreshCw size={13} className={syncing === source.id ? "spin" : ""} />} loading={syncing === source.id} onClick={() => sync(source)}>Sync now</Button>}
                </div>
              </Card>
            ))}
          </div>

          <div className="grid-2-1">
            <Panel title="Recent ingestion runs" subtitle="Lineage, validation and deduplication outcomes" flush>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Source</th><th>Status</th><th>Read</th><th>Ingested</th><th>Rejected</th><th>Duplicates</th><th>Started</th><th /></tr></thead>
                  <tbody>
                    {(data?.recent_ingestions || []).map((run: any) => {
                      const source = data?.sources.find((item: Source) => item.id === run.source_id);
                      return (
                        <tr key={run.id} className="row-clickable" onClick={() => setSelectedRun(run)}>
                          <td><strong>{source?.name || run.source_id}</strong><span className="table-sub">{titleCase(run.trigger)}</span></td>
                          <td><StatusBadge status={run.status} size="sm" /></td>
                          <td>{run.records_read}</td>
                          <td className="positive">{run.records_ingested}</td>
                          <td className={run.records_rejected ? "negative" : ""}>{run.records_rejected}</td>
                          <td>{run.duplicates_blocked}</td>
                          <td><span className="table-sub">{relativeTime(run.started_at)}</span></td>
                          <td><Button size="sm" variant="ghost">Lineage</Button></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {(data?.recent_ingestions || []).length === 0 && <EmptyState title="No ingestion runs" />}
              </div>
            </Panel>

            <Panel title="Connection framework" subtitle="Configured capability">
              <div className="connector-list">
                {[
                  { name: "REST APIs", icon: Globe2, status: "Supported", note: "HTTPX · pagination · retry · rate-limit handling" },
                  { name: "GraphQL", icon: Cloud, status: "Supported", note: "Typed query envelope; field mapping required" },
                  { name: "SQL databases", icon: Database, status: "Active · SQL demo", note: "PostgreSQL · MySQL · SQLite · read-only transactions" },
                  { name: "Google Sheets", icon: Table2, status: "Supported", note: "Public CSV, API key or service-account read access" },
                  { name: "CSV / Excel", icon: FileSpreadsheet, status: "Active", note: "Explicit column mapping and row validation" },
                  { name: "Simulated POS / ERP", icon: Server, status: "Active · Demo", note: "Deterministic demo sources, clearly labelled" },
                ].map((connector) => {
                  const Icon = connector.icon;
                  return (
                    <div key={connector.name} className="connector-row">
                      <span className="connector-icon"><Icon size={16} /></span>
                      <div><strong>{connector.name}</strong><span>{connector.note}</span></div>
                      <Badge tone={connector.status.startsWith("Active") ? "success" : "muted"}>{connector.status}</Badge>
                    </div>
                  );
                })}
              </div>
              <div className="credential-note"><KeyRound size={14} /><span>Credentials are read from server-side secret references and are never exposed in connector responses.</span></div>
            </Panel>
          </div>

          <Row gap="lg">
            <Panel title="Transformation registry" subtitle="Normalisation rules with original-value lineage" actions={<Badge tone="info">{data?.transformations.length || 0} rules</Badge>}>
              <div className="transform-grid">
                {(data?.transformations || []).map((transform: any) => (
                  <div key={transform.id} className="transform-card">
                    <div className="transform-head"><strong>{transform.name}</strong><StatusBadge status={transform.status} size="sm" /></div>
                    <p>{transform.description}</p>
                    <div className="transform-meta">
                      <Badge tone={transform.ai_assisted ? "violet" : "muted"}>{transform.ai_assisted ? "AI assisted" : "Deterministic"}</Badge>
                      <span>{transform.source_field} → {transform.target_field}</span>
                      <span>v{transform.version}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel title="Data quality posture" subtitle="Policy and current state">
              <DefinitionList
                items={[
                  { label: "Freshness threshold", value: "48 hours" },
                  { label: "Stale sources", value: <Badge tone={data?.summary.stale ? "warning" : "success"}>{data?.summary.stale || 0}</Badge> },
                  { label: "Rejected records", value: number(data?.recent_ingestions.reduce((total: number, run: any) => total + (run.records_rejected || 0), 0), 0) },
                  { label: "Duplicates blocked", value: number(data?.recent_ingestions.reduce((total: number, run: any) => total + (run.duplicates_blocked || 0), 0), 0) },
                  { label: "Simulated source policy", value: <span className="positive"><CheckCircle2 size={13} /> Labelled end-to-end</span> },
                ]}
              />
              <div className="notice-strip compact"><ShieldCheck size={14} /><span>{data?.notice}</span></div>
            </Panel>
          </Row>

          <Panel title="Transformations executed" subtitle="Latest passes over normalized observations" flush>
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Transformation</th><th>Status</th><th>Examined</th><th>Changed</th><th>Skipped</th><th>Errors</th><th>When</th></tr></thead>
                <tbody>
                  {(data?.transformation_runs || []).map((run: any) => (
                    <tr key={run.id}>
                      <td className="mono">{run.id.slice(-12)}</td>
                      <td><StatusBadge status={run.status} size="sm" /></td>
                      <td>{run.stats?.examined || 0}</td>
                      <td>{run.stats?.changed || 0}</td>
                      <td>{run.stats?.skipped || 0}</td>
                      <td className={run.stats?.errors ? "negative" : ""}>{run.stats?.errors || 0}</td>
                      <td><span className="table-sub">{relativeTime(run.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </>
      )}

      <Drawer open={Boolean(selectedRun)} onClose={() => setSelectedRun(null)} title="Ingestion lineage" subtitle={selectedRun?.id}>
        {selectedRun && (
          <div className="stack-lg">
            <div className="drawer-status-row"><StatusBadge status={selectedRun.status} /><span>{titleCase(selectedRun.trigger)} trigger</span><span>{dateTime(selectedRun.started_at)}</span></div>
            <DefinitionList items={[
              { label: "Records read", value: selectedRun.records_read },
              { label: "Ingested", value: selectedRun.records_ingested },
              { label: "Rejected", value: selectedRun.records_rejected },
              { label: "Duplicates blocked", value: selectedRun.duplicates_blocked },
              { label: "Raw payload", value: <span className="mono small-text">{selectedRun.raw_payload_ref || "—"}</span> },
            ]} />
            <div><h3 className="section-title">Lineage record</h3><JsonBlock value={selectedRun.lineage} maxHeight={520} /></div>
          </div>
        )}
      </Drawer>

      <Modal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title="Upload operational data"
        subtitle="CSV or Excel. Raw files are retained; each row is validated and deduplicated."
        width="580px"
        footer={<><Button onClick={() => setUploadOpen(false)}>Cancel</Button><Button variant="primary" loading={uploading} disabled={!uploadFile} onClick={upload}>Ingest file</Button></>}
      >
        <div className="form-grid">
          <div className="upload-mini span-2" onClick={() => inputRef.current?.click()}>
            <input ref={inputRef} hidden type="file" accept=".csv,.xlsx,.xlsm" onChange={(event) => setUploadFile(event.target.files?.[0] || null)} />
            <UploadCloud size={22} />
            <div><strong>{uploadFile?.name || "Select a CSV or Excel file"}</strong><span>Required columns: period, value, channel, category</span></div>
          </div>
          <label className="field"><span>Entity</span><select value={entity} onChange={(event) => setEntity(event.target.value)}><option value="revenue">Revenue</option><option value="expense">Expense</option><option value="cogs">Cost of sales</option><option value="cash">Cash</option><option value="inventory">Inventory</option></select></label>
          <label className="field"><span>Metric</span><input value={metric} onChange={(event) => setMetric(event.target.value)} /></label>
        </div>
        <div className="notice-strip compact"><LockKeyhole size={14} /><span>Uploads are untrusted input: values are validated, negatives rejected where invalid, and no formulas are executed.</span></div>
      </Modal>

      <ConnectSourceModal
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        onCreated={() => {
          setConnectOpen(false);
          integrations.refresh();
        }}
      />
    </div>
  );
}

function ConnectSourceModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [kind, setKind] = useState("SQL_DATABASE");
  const [name, setName] = useState("Analytics warehouse");
  const [testing, setTesting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [testResult, setTestResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, string>>({
    connection_env: "ANALYTICS_DATABASE_URL",
    query: "SELECT period, channel, metric, value, unit, category FROM analytics.campaign_metrics ORDER BY period",
    spreadsheet: "",
    sheet_name: "Sheet1",
    range: "",
    service_account_env: "GOOGLE_SERVICE_ACCOUNT_JSON",
    api_key_env: "GOOGLE_SHEETS_API_KEY",
    base_url: "",
    path: "/v1/sales",
    records_path: "data",
    auth_env: "VENDOR_API_TOKEN",
    value_column: "value",
    period_column: "period",
    entity_column: "",
    metric_column: "metric",
    channel_column: "channel",
    category_column: "category",
    entity: "revenue",
    metric: "revenue",
  });

  function update(key: string, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
    setTestResult(null);
    setError(null);
  }

  function configFor(kindValue: string): Record<string, any> {
    const mapping = {
      entity: form.entity_column,
      metric: form.metric_column || (kindValue === "REST" ? form.metric : ""),
      period: form.period_column,
      value: form.value_column,
      channel: form.channel_column,
      category: form.category_column,
    };
    if (kindValue === "SQL_DATABASE") {
      return {
        connection_env: form.connection_env,
        query: form.query,
        max_rows: 1000,
        default_entity: form.entity,
        default_metric: form.metric,
        mapping,
      };
    }
    if (kindValue === "GOOGLE_SHEETS") {
      return {
        spreadsheet_id: form.spreadsheet,
        sheet_name: form.sheet_name || undefined,
        range: form.range || undefined,
        service_account_env: form.service_account_env || undefined,
        api_key_env: form.api_key_env || undefined,
        default_entity: form.entity,
        default_metric: form.metric,
        mapping,
      };
    }
    return {
      base_url: form.base_url,
      path: form.path,
      records_path: form.records_path,
      auth_env: form.auth_env || undefined,
      mapping: { ...mapping, value: form.value_column, period: form.period_column },
    };
  }

  async function test() {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const result = await api.testConnector(kind, configFor(kind));
      setTestResult(result);
      toast.push(`Connection succeeded: ${result.fact_count} mapped records.`, "success");
    } catch (exc: any) {
      setError(exc?.message || "Connection test failed");
    } finally {
      setTesting(false);
    }
  }

  async function create() {
    setCreating(true);
    setError(null);
    try {
      const result = await api.createSource({ name, kind, system: kind.toLowerCase(), config: configFor(kind), sync_now: true });
      if (result.run?.status === "SUCCEEDED") {
        toast.push(`${result.run.records_ingested} new records ingested from ${name}.`, "success");
      } else {
        toast.push(`Source created, but sync ${result.run?.status || "did not run"}: ${result.run?.error || ""}`, "danger");
      }
      onCreated();
    } catch (exc: any) {
      setError(exc?.message || "Unable to create source");
    } finally {
      setCreating(false);
    }
  }

  const kinds = [
    { key: "SQL_DATABASE", label: "SQL database", icon: Database, description: "PostgreSQL, MySQL, SQLite" },
    { key: "GOOGLE_SHEETS", label: "Google Sheets", icon: Table2, description: "Public or private read" },
    { key: "REST", label: "REST API", icon: Globe2, description: "Paginated JSON endpoint" },
  ];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Connect a data source"
      subtitle="Credentials are environment references. Raw payloads are retained; nothing is executed except the read query."
      width="760px"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button icon={<ShieldCheck size={15} />} onClick={test} loading={testing}>Test connection</Button>
          <Button variant="primary" icon={<Plus size={15} />} onClick={create} loading={creating}>Create & sync</Button>
        </>
      }
    >
      <div className="source-kind-grid">
        {kinds.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.key} className={`source-kind ${kind === item.key ? "source-kind-active" : ""}`} onClick={() => { setKind(item.key); setTestResult(null); setError(null); }}>
              <Icon size={18} />
              <span><strong>{item.label}</strong><small>{item.description}</small></span>
              {kind === item.key && <CheckCircle2 size={15} />}
            </button>
          );
        })}
      </div>

      <div className="form-grid">
        <label className="field span-2"><span>Source name</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>

        {kind === "SQL_DATABASE" && (
          <>
            <label className="field"><span>Connection secret reference</span><input value={form.connection_env} onChange={(event) => update("connection_env", event.target.value)} placeholder="ANALYTICS_DATABASE_URL" /></label>
            <label className="field"><span>Default metric</span><input value={form.metric} onChange={(event) => update("metric", event.target.value)} /></label>
            <label className="field span-2"><span>Read-only SQL query</span><textarea className="code-input" rows={5} value={form.query} onChange={(event) => update("query", event.target.value)} /></label>
            <div className="notice-strip compact span-2"><LockKeyhole size={14} /><span>Set the connection URL in the backend environment, e.g. <code>postgresql+asyncpg://readonly_user:password@host:5432/analytics</code>. Use a read-only database role. Only SELECT / WITH statements are accepted.</span></div>
          </>
        )}

        {kind === "GOOGLE_SHEETS" && (
          <>
            <label className="field span-2"><span>Spreadsheet URL or ID</span><input value={form.spreadsheet} onChange={(event) => update("spreadsheet", event.target.value)} placeholder="https://docs.google.com/spreadsheets/d/..." /></label>
            <label className="field"><span>Sheet name</span><input value={form.sheet_name} onChange={(event) => update("sheet_name", event.target.value)} /></label>
            <label className="field"><span>A1 range (optional)</span><input value={form.range} onChange={(event) => update("range", event.target.value)} placeholder="Campaign!A1:F200" /></label>
            <label className="field"><span>Service account env</span><input value={form.service_account_env} onChange={(event) => update("service_account_env", event.target.value)} /></label>
            <label className="field"><span>API key env</span><input value={form.api_key_env} onChange={(event) => update("api_key_env", event.target.value)} /></label>
            <div className="notice-strip compact span-2"><ShieldCheck size={14} /><span>Link-shared sheets work without credentials. Private sheets need <code>GOOGLE_SERVICE_ACCOUNT_JSON</code> or <code>GOOGLE_SHEETS_API_KEY</code>. Read-only scope only.</span></div>
          </>
        )}

        {kind === "REST" && (
          <>
            <label className="field"><span>Base URL</span><input value={form.base_url} onChange={(event) => update("base_url", event.target.value)} placeholder="https://api.vendor.com" /></label>
            <label className="field"><span>Path</span><input value={form.path} onChange={(event) => update("path", event.target.value)} /></label>
            <label className="field"><span>Records path</span><input value={form.records_path} onChange={(event) => update("records_path", event.target.value)} placeholder="data" /></label>
            <label className="field"><span>Auth env reference</span><input value={form.auth_env} onChange={(event) => update("auth_env", event.target.value)} /></label>
            <label className="field span-2"><span>Metric</span><input value={form.metric} onChange={(event) => update("metric", event.target.value)} /></label>
          </>
        )}

        <label className="field"><span>Value column / field</span><input value={form.value_column} onChange={(event) => update("value_column", event.target.value)} /></label>
        <label className="field"><span>Period column / field</span><input value={form.period_column} onChange={(event) => update("period_column", event.target.value)} /></label>
        <label className="field"><span>Entity column (optional)</span><input value={form.entity_column} onChange={(event) => update("entity_column", event.target.value)} /></label>
        <label className="field"><span>Metric column (optional)</span><input value={form.metric_column} onChange={(event) => update("metric_column", event.target.value)} /></label>
        <label className="field"><span>Channel column (optional)</span><input value={form.channel_column} onChange={(event) => update("channel_column", event.target.value)} /></label>
        <label className="field"><span>Category column (optional)</span><input value={form.category_column} onChange={(event) => update("category_column", event.target.value)} /></label>
        <label className="field"><span>Default entity</span><input value={form.entity} onChange={(event) => update("entity", event.target.value)} /></label>
        <label className="field"><span>Default metric</span><input value={form.metric} onChange={(event) => update("metric", event.target.value)} /></label>
      </div>

      {error && <div className="error-banner compact">{error}</div>}
      {testResult && (
        <div className="connection-test-result">
          <div className="connection-test-head"><CheckCircle2 size={16} /><strong>Connection successful</strong><Badge tone="success">{testResult.fact_count} mapped facts</Badge><span>{testResult.notes}</span></div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Period</th><th>Entity</th><th>Metric</th><th>Value</th><th>Channel</th></tr></thead>
              <tbody>
                {(testResult.sample || []).map((row: any, index: number) => (
                  <tr key={index}><td>{row.period?.slice(0, 10) || "—"}</td><td>{row.entity}</td><td>{row.metric}</td><td>{number(row.value, 2)}</td><td>{row.channel || "—"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}

function Row({ children, gap = "md" }: { children: React.ReactNode; gap?: string }) {
  return <div className={`grid-2 gap-${gap}`}>{children}</div>;
}
