import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  CheckCircle2,
  ClipboardList,
  Download,
  ExternalLink,
  FileText,
  Inbox,
  Megaphone,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Siren,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { canRun, useAuth } from "../lib/auth";
import { dateTime, money, number, pct, relativeTime, severityTone, statusTone, titleCase } from "../lib/format";
import { useApi, useInterval } from "../lib/useApi";
import { useToast } from "../components/Toast";
import {
  Badge,
  Button,
  Card,
  DefinitionList,
  EmptyState,
  ErrorState,
  JsonBlock,
  LoadingBlock,
  PageHeader,
  Panel,
  StatusBadge,
  Tabs,
} from "../components/ui";
import type { Alert, Report } from "../lib/types";

export function ReportsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "reports";
  const [reportFilter, setReportFilter] = useState("ALL");
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(params.get("alert"));
  const [alertDetail, setAlertDetail] = useState<Alert | null>(null);
  const [note, setNote] = useState("");
  const [acting, setActing] = useState(false);

  const reports = useApi(() => api.reports(), []);
  const alerts = useApi(() => api.alerts(), []);
  const notifications = useApi(api.notifications, []);
  const audit = useApi(
    () => (["ADMIN", "ANALYST", "APPROVER"].includes(user?.role || "") ? api.auditLogs() : Promise.resolve([])),
    [user?.role],
  );

  useEffect(() => {
    if (!selectedReportId && reports.data?.length) setSelectedReportId(reports.data[0].id);
  }, [reports.data, selectedReportId]);

  useEffect(() => {
    if (!selectedReportId) { setReport(null); return; }
    let active = true;
    api.report(selectedReportId).then((result) => active && setReport(result)).catch((exc) => toast.push(exc?.message || "Unable to load report", "danger"));
    return () => { active = false; };
  }, [selectedReportId]);

  useEffect(() => {
    if (!selectedAlertId) { setAlertDetail(null); return; }
    let active = true;
    api.alert(selectedAlertId).then((result) => active && setAlertDetail(result)).catch(() => undefined);
    return () => { active = false; };
  }, [selectedAlertId]);

  useEffect(() => {
    if (!selectedAlertId && alerts.data?.alerts?.length) {
      setSelectedAlertId(alerts.data.alerts[0].id);
    }
  }, [alerts.data, selectedAlertId]);

  useEffect(() => {
    if (params.get("alert")) setSelectedAlertId(params.get("alert"));
  }, [params]);

  useInterval(() => {
    if (report?.content?.provenance || tab === "alerts") {
      alerts.refresh();
    }
  }, tab === "alerts" ? 15000 : null);

  const filteredReports = useMemo(
    () => (reports.data || []).filter((item) => reportFilter === "ALL" || item.report_type === reportFilter),
    [reports.data, reportFilter],
  );

  async function alertAction(action: "ack" | "resolve" | "escalate" | "investigate") {
    if (!alertDetail) return;
    setActing(true);
    try {
      if (action === "ack") await api.acknowledgeAlert(alertDetail.id, note);
      if (action === "resolve") await api.resolveAlert(alertDetail.id, note);
      if (action === "escalate") await api.escalateAlert(alertDetail.id, note);
      if (action === "investigate") {
        const result = await api.investigateAlert(alertDetail.id);
        toast.push(result.existing ? "A decision workflow is already active for this incident." : "Decision workflow started. Recommendations will appear in the Decision Center.", "success");
      } else {
        toast.push(`Incident ${action === "ack" ? "acknowledged" : action === "resolve" ? "resolved" : "escalated"}.`, "success");
      }
      setNote("");
      alerts.refresh();
      const refreshed = await api.alert(alertDetail.id);
      setAlertDetail(refreshed);
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to update incident", "danger");
    } finally {
      setActing(false);
    }
  }

  function switchTab(next: string) {
    const nextParams: Record<string, string> = { tab: next };
    if (next === "alerts" && selectedAlertId) nextParams.alert = selectedAlertId;
    setParams(nextParams);
  }

  const content = report?.content || {};
  const actuals = content.measured_actuals || {};
  const interpretation = content.ai_interpretation;

  return (
    <div className="page page-wide">
      <PageHeader
        eyebrow="Management communications · Evidence-led"
        title="Reports & Alerts"
        description="Daily executive summaries, exception reports, decision records and the incident register."
        meta={
          <div className="header-meta-row">
            <Badge tone="info" dot>{reports.data?.length || 0} reports</Badge>
            <Badge tone={alerts.data?.summary?.critical ? "danger" : "warning"} dot>{alerts.data?.summary?.open || 0} open incidents</Badge>
            <span className="meta-divider" />
            <span className="meta-text">PDF · Excel · CSV</span>
          </div>
        }
        actions={<Button icon={<RefreshCw size={15} />} onClick={() => { reports.refresh(); alerts.refresh(); notifications.refresh(); }}>Refresh</Button>}
      />

      <Tabs
        tabs={[
          { key: "reports", label: "Management reports", count: reports.data?.length },
          { key: "alerts", label: "Alert register", count: alerts.data?.alerts?.length },
          { key: "notifications", label: "Notifications", count: notifications.data?.length },
          { key: "audit", label: "Audit trail", count: audit.data?.length },
        ]}
        active={tab}
        onChange={switchTab}
      />

      {tab === "reports" && (
        <div className="split-layout reports-layout">
          <aside className="reports-list-column">
            <Card className="logic-list-card">
              <div className="logic-list-head">
                <div><span className="eyebrow">Report library</span><h2>Generated artifacts</h2></div>
              </div>
              <div className="report-filters">
                {["ALL", "DAILY_SUMMARY", "EXCEPTION", "DECISION", "SIMULATION"].map((type) => (
                  <button key={type} className={`filter-tab ${reportFilter === type ? "filter-tab-active" : ""}`} onClick={() => setReportFilter(type)}>
                    {type === "ALL" ? "All" : titleCase(type)}
                  </button>
                ))}
              </div>
              {reports.loading && !reports.data ? <LoadingBlock lines={7} /> : reports.error ? <ErrorState message={reports.error} onRetry={reports.refresh} /> : (
                <div className="report-list">
                  {filteredReports.map((item) => (
                    <button key={item.id} className={`report-row ${selectedReportId === item.id ? "report-row-active" : ""}`} onClick={() => setSelectedReportId(item.id)}>
                      <div className={`report-icon report-icon-${item.report_type.toLowerCase()}`}>
                        {item.report_type === "EXCEPTION" ? <Siren size={16} /> : item.report_type === "DECISION" ? <ClipboardList size={16} /> : <FileText size={16} />}
                      </div>
                      <div>
                        <strong>{item.title}</strong>
                        <span>{titleCase(item.report_type)} · {relativeTime(item.created_at)}</span>
                      </div>
                      <StatusBadge status={item.status} size="sm" />
                    </button>
                  ))}
                  {filteredReports.length === 0 && <EmptyState title="No reports" description="Run a daily cycle to generate management reports." />}
                </div>
              )}
            </Card>
          </aside>

          <section className="report-view-column">
            {!report ? <Card className="detail-placeholder"><EmptyState title="Select a report" icon={<FileText size={24} />} /></Card> : (
              <div className="stack-lg">
                <Card className="report-view-head">
                  <div>
                    <div className="eyebrow">{titleCase(report.report_type)} · {report.generated_by}</div>
                    <h2>{report.title}</h2>
                    <p>{dateTime(report.created_at)}</p>
                  </div>
                  <div className="report-downloads">
                    {Object.keys(report.files || {}).map((format) => (
                      <Button key={format} size="sm" icon={<Download size={14} />} onClick={() => api.downloadReport(report.id, format)}>
                        {format.toUpperCase()}
                      </Button>
                    ))}
                  </div>
                </Card>

                {content.measured_actuals ? (
                  <>
                    <div className="report-actual-grid">
                      {[
                        ["Revenue", money(actuals.revenue), "Measured"],
                        ["Gross margin", pct(actuals.gross_margin_pct), "Calculated"],
                        ["Net profit", money(actuals.net_profit), "Calculated"],
                        ["Cash position", money(actuals.cash_balance), "Measured"],
                        ["Cash runway", `${number(actuals.cash_runway_months, 1)} mo`, "Calculated"],
                        ["Inventory days", `${number(actuals.inventory_days, 0)} d`, "Calculated"],
                      ].map(([label, value, classification]) => (
                        <div key={label} className="report-actual">
                          <span>{label}</span><strong>{value}</strong><small>{classification}</small>
                        </div>
                      ))}
                    </div>

                    <Panel title="Executive summary" subtitle="Measured results and deterministic conclusions">
                      <p className="long-copy">{content.executive_summary}</p>
                      {interpretation && (
                        <div className="interpretation-block">
                          <div className="interpretation-head">
                            <Sparkles size={15} />
                            <strong>{interpretation.label}</strong>
                            <Badge tone={interpretation.provider === "deterministic" ? "muted" : "violet"}>{interpretation.provider}</Badge>
                          </div>
                          <p>{interpretation.text}</p>
                          <span>Interpretation is generated after deterministic metrics and cannot alter them.</span>
                        </div>
                      )}
                    </Panel>

                    <div className="grid-2">
                      <Panel title="Exceptions" subtitle="Open incidents at report time" flush>
                        <div className="report-exception-list">
                          {(content.exceptions || []).map((exception: any) => (
                            <div key={`${exception.title}-${exception.area}`} className="report-exception">
                              <Badge tone={severityTone(exception.severity)} dot>{exception.severity}</Badge>
                              <div><strong>{exception.title}</strong><span>{exception.area} · {exception.status}</span><p>{exception.detail}</p></div>
                            </div>
                          ))}
                          {(content.exceptions || []).length === 0 && <EmptyState title="No open exceptions" icon={<CheckCircle2 size={22} />} />}
                        </div>
                      </Panel>
                      <Panel title="Business health" subtitle="Transparent factor scores">
                        <div className="report-health">
                          <div><span>Score</span><strong>{number(content.health?.score, 0)}</strong><Badge tone="info">Grade {content.health?.grade}</Badge></div>
                          {(content.health?.factors || []).map((factor: any) => (
                            <div key={factor.key} className="report-health-factor"><span>{factor.label}</span><div className="progress-track"><div className="progress-fill progress-blue" style={{ width: `${factor.score}%` }} /></div><strong>{number(factor.score, 0)}</strong></div>
                          ))}
                        </div>
                      </Panel>
                    </div>

                    <div className="grid-2">
                      <Panel title="Decisions in the report" flush>
                        <div className="table-wrap">
                          <table className="data-table">
                            <thead><tr><th>Decision</th><th>Status</th><th>Projected</th></tr></thead>
                            <tbody>
                              {(content.decisions || []).slice(0, 6).map((decision: any) => (
                                <tr key={decision.id}><td>{decision.title}</td><td><StatusBadge status={decision.status} size="sm" /></td><td>{money(decision.expected_impact, true)}</td></tr>
                              ))}
                            </tbody>
                          </table>
                          {(content.decisions || []).length === 0 && <EmptyState title="No decisions in period" />}
                        </div>
                      </Panel>
                      <Panel title="Executed actions" flush>
                        <div className="table-wrap">
                          <table className="data-table">
                            <thead><tr><th>Action</th><th>Status</th><th>Verified</th></tr></thead>
                            <tbody>
                              {(content.actions || []).slice(0, 6).map((action: any) => (
                                <tr key={action.id}><td>{titleCase(action.type)}</td><td><StatusBadge status={action.status} size="sm" /></td><td>{action.verification || "Pending"}</td></tr>
                              ))}
                            </tbody>
                          </table>
                          {(content.actions || []).length === 0 && <EmptyState title="No actions executed" />}
                        </div>
                      </Panel>
                    </div>
                    <div className="notice-strip compact"><ShieldCheck size={14} /><span>{content.provenance?.notice} Snapshot {content.provenance?.snapshot_id}.</span></div>
                  </>
                ) : (
                  <Panel title="Report content" subtitle="Structured record">
                    <JsonBlock value={content} maxHeight={640} />
                  </Panel>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      {tab === "alerts" && (
        <div className="alerts-layout">
          <div className="alert-summary-row">
            <Card className="alert-stat"><span>Open</span><strong>{alerts.data?.summary?.open || 0}</strong><small>unresolved incidents</small></Card>
            <Card className="alert-stat"><span>Critical</span><strong className="negative">{alerts.data?.summary?.critical || 0}</strong><small>immediate attention</small></Card>
            <Card className="alert-stat"><span>High</span><strong>{alerts.data?.summary?.high || 0}</strong><small>management review</small></Card>
            <Card className="alert-stat"><span>Acknowledged</span><strong>{alerts.data?.summary?.acknowledged || 0}</strong><small>in progress</small></Card>
          </div>

          <div className="split-layout alerts-split">
            <div className="alert-list-column">
              {alerts.loading && !alerts.data ? <LoadingBlock lines={8} /> : alerts.error ? <ErrorState message={alerts.error} onRetry={alerts.refresh} /> : (
                <div className="alert-list">
                  {(alerts.data?.alerts || []).map((alert) => (
                    <button key={alert.id} className={`alert-card ${selectedAlertId === alert.id ? "alert-card-active" : ""}`} onClick={() => { setSelectedAlertId(alert.id); setParams({ tab: "alerts", alert: alert.id }); }}>
                      <div className={`alert-severity severity-${severityTone(alert.severity)}`} />
                      <div className="alert-card-copy">
                        <div className="alert-card-head"><Badge tone={severityTone(alert.severity)} dot>{alert.severity}</Badge><StatusBadge status={alert.status} size="sm" /><span>{relativeTime(alert.last_seen)}</span></div>
                        <strong>{alert.title}</strong>
                        <p>{alert.detail}</p>
                        <div className="alert-card-meta"><span>{titleCase(alert.area)}</span><span>{alert.occurrences} occurrences</span>{alert.escalation_level > 0 && <Badge tone="danger" className="badge-sm">Escalated L{alert.escalation_level}</Badge>}</div>
                      </div>
                    </button>
                  ))}
                  {(alerts.data?.alerts || []).length === 0 && <EmptyState title="No incidents" description="The monitoring service has no open exceptions." icon={<CheckCircle2 size={22} />} />}
                </div>
              )}
            </div>

            <div className="alert-detail-column">
              {!alertDetail ? <Card className="detail-placeholder"><EmptyState title="Select an incident" description="Review evidence, acknowledge, resolve or launch an investigation." icon={<ShieldAlert size={24} />} /></Card> : (
                <div className="stack-lg">
                  <Card className={`alert-detail-head severity-border-${severityTone(alertDetail.severity)}`}>
                    <div className="alert-detail-top">
                      <div><div className="eyebrow">{titleCase(alertDetail.area)} · Incident</div><h2>{alertDetail.title}</h2><p>{alertDetail.detail}</p></div>
                      <div className="alert-detail-badges"><Badge tone={severityTone(alertDetail.severity)} dot>{alertDetail.severity}</Badge><StatusBadge status={alertDetail.status} /></div>
                    </div>
                    <div className="alert-detail-meta">
                      <span>First seen {dateTime(alertDetail.first_seen)}</span>
                      <span>Last seen {relativeTime(alertDetail.last_seen)}</span>
                      <span>{alertDetail.occurrences} occurrences</span>
                      {alertDetail.acknowledged_by && <span>Acknowledged by {alertDetail.acknowledged_by}</span>}
                    </div>
                  </Card>

                  <Panel title="Evidence" subtitle="Underlying validated business data">
                    <JsonBlock value={alertDetail.evidence || {}} maxHeight={340} />
                  </Panel>

                  <Panel title="Incident actions" subtitle="Deduplication prevents repeated alerts for the same unresolved incident">
                    <label className="field"><span>Action note</span><textarea value={note} onChange={(event) => setNote(event.target.value)} rows={3} placeholder="Record context, owner or resolution evidence…" /></label>
                    <div className="alert-actions">
                      <Button size="sm" loading={acting} onClick={() => alertAction("ack")} disabled={alertDetail.status !== "OPEN"}>Acknowledge</Button>
                      <Button size="sm" variant="success" loading={acting} onClick={() => alertAction("resolve")} disabled={alertDetail.status === "RESOLVED"}>Resolve</Button>
                      <Button size="sm" variant="danger" loading={acting} onClick={() => alertAction("escalate")}>Escalate</Button>
                      {canRun(user) && (
                        <Button size="sm" variant="primary" icon={<Sparkles size={14} />} loading={acting} onClick={() => alertAction("investigate")} disabled={alertDetail.status === "RESOLVED"}>
                          Investigate with agents
                        </Button>
                      )}
                    </div>
                  </Panel>

                  <Panel title="Incident timeline" subtitle="Acknowledgement, escalation and resolution events">
                    <div className="alert-timeline">
                      {(alertDetail.events || []).map((event: any) => (
                        <div key={event.id} className="alert-event">
                          <div className={`event-dot event-${statusTone(event.kind)}`} />
                          <div><strong>{titleCase(event.kind)}</strong><p>{event.message}</p><span>{event.actor} · {relativeTime(event.created_at)}</span></div>
                        </div>
                      ))}
                    </div>
                  </Panel>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === "notifications" && (
        <Panel title="Notification log" subtitle="In-app and email delivery records. Email is only marked sent after SMTP acceptance." flush>
          <div className="notification-list">
            {(notifications.data || []).map((notification: any) => (
              <div key={notification.id} className="notification-item">
                <div className={`notification-icon notification-${notification.status.toLowerCase()}`}><Bell size={16} /></div>
                <div className="notification-copy">
                  <div><strong>{notification.subject}</strong><Badge tone={statusTone(notification.status)}>{notification.status}</Badge></div>
                  <p>{notification.body}</p>
                  <span>{notification.channel} · {notification.recipient} · {relativeTime(notification.created_at)}</span>
                </div>
              </div>
            ))}
            {(notifications.data || []).length === 0 && <EmptyState title="No notifications" />}
          </div>
        </Panel>
      )}

      {tab === "audit" && (
        <Panel
          title="Immutable audit trail"
          subtitle="Actor, action and entity changes across decisions, approvals, workflows and credentials"
          actions={<Badge tone="muted">{audit.data?.length || 0} events</Badge>}
          flush
        >
          {audit.loading && !audit.data ? <LoadingBlock lines={8} /> : audit.error ? <ErrorState message={audit.error} onRetry={audit.refresh} /> : (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Detail</th><th>Change</th></tr></thead>
                <tbody>
                  {(audit.data || []).map((entry: any) => (
                    <tr key={entry.id}>
                      <td><span className="table-sub">{dateTime(entry.created_at)}</span></td>
                      <td><strong>{entry.actor}</strong><span className="table-sub">{entry.actor_type}</span></td>
                      <td><Badge tone={entry.action.includes("APPROVED") || entry.action.includes("ACTIVATED") ? "success" : entry.action.includes("REJECTED") ? "danger" : "info"}>{titleCase(entry.action)}</Badge></td>
                      <td><span className="mono small-text">{entry.entity_type}</span><span className="table-sub">{entry.entity_id}</span></td>
                      <td className="cell-summary">{entry.detail || "—"}</td>
                      <td>
                        <details className="audit-change">
                          <summary>View</summary>
                          <JsonBlock value={{ before: entry.before, after: entry.after }} maxHeight={180} />
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(audit.data || []).length === 0 && <EmptyState title="No audit entries" description="Privileged actions will appear here." />}
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
