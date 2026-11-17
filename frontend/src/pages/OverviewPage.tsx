import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Banknote,
  BarChart3,
  BrainCircuit,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Gauge,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from "lucide-react";
import { api } from "../lib/api";
import { money, number, pct, pp, relativeTime, severityTone, statusTone, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useToast } from "../components/Toast";
import { Chart } from "../components/Chart";
import {
  Badge,
  Button,
  Card,
  DemoNotice,
  EmptyState,
  ErrorState,
  LoadingBlock,
  PageHeader,
  Panel,
  ProgressBar,
  ScoreRing,
  StatCard,
  StatusBadge,
} from "../components/ui";

export function OverviewPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { data, loading, error, refresh } = useApi(api.overview, []);
  const [starting, setStarting] = useState(false);

  const snapshot = data?.snapshot;
  const latest = snapshot?.latest;
  const trends = snapshot?.trends || {};

  const revenueTrend = useMemo(() => (trends.revenue || []).map((point: any) => point.value), [trends]);
  const marginTrend = useMemo(() => (trends.gross_margin_pct || []).map((point: any) => point.value), [trends]);
  const profitTrend = useMemo(() => (trends.net_profit || []).map((point: any) => point.value), [trends]);
  const cashTrend = useMemo(() => (trends.cash_balance || []).map((point: any) => point.value), [trends]);
  const revenuePoints = trends.revenue || [];
  const marginPoints = trends.gross_margin_pct || [];

  async function startDaily() {
    setStarting(true);
    try {
      await api.runWorkflow("daily_bi", {});
      toast.push("Daily intelligence cycle started. Reports will appear shortly.", "success");
      window.setTimeout(refresh, 3500);
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to start the cycle", "danger");
    } finally {
      setStarting(false);
    }
  }

  if (loading && !data) {
    return (
      <div className="page">
        <PageHeader eyebrow="Command Center" title="Business Overview" description="Loading validated twin state…" />
        <div className="kpi-grid">
          {Array.from({ length: 6 }).map((_, index) => <Card key={index} className="stat-card"><LoadingBlock lines={3} /></Card>)}
        </div>
        <LoadingBlock lines={9} height={420} />
      </div>
    );
  }

  if (error || !data || !snapshot) {
    return (
      <div className="page">
        <PageHeader eyebrow="Command Center" title="Business Overview" />
        <ErrorState message={error || "No business state available"} onRetry={refresh} />
      </div>
    );
  }

  const activeWorkflow = data.workflows.find((run) => ["RUNNING", "WAITING_APPROVAL", "WAITING_HUMAN_REVIEW"].includes(run.status));
  const health = snapshot.health;
  const criticalAlert = data.alerts.find((alert) => alert.severity === "CRITICAL" && alert.status !== "RESOLVED");
  const topFindings = snapshot.intelligence?.findings?.slice(0, 4) || [];
  const latestKpi = (key: string) => snapshot.kpis.find((kpi) => kpi.key === key);
  const revenueKpi = latestKpi("revenue");
  const marginKpi = latestKpi("gross_margin");
  const netKpi = latestKpi("net_profit");
  const cashKpi = latestKpi("cash_balance");
  const runwayKpi = latestKpi("cash_runway");

  const chartData = [
    {
      type: "bar",
      name: "Revenue",
      x: revenuePoints.map((point: any) => point.period),
      y: revenuePoints.map((point: any) => point.value),
      marker: { color: "rgba(47,107,255,0.72)", line: { width: 0 } },
      hovertemplate: "%{x}<br>Revenue $%{y:,.0f}<extra></extra>",
      yaxis: "y",
    },
    {
      type: "scatter",
      mode: "lines+markers",
      name: "Gross margin",
      x: marginPoints.map((point: any) => point.period),
      y: marginPoints.map((point: any) => point.value),
      line: { color: "#14B8A6", width: 2.4, shape: "spline" },
      marker: { size: 5, color: "#14B8A6" },
      hovertemplate: "%{x}<br>Gross margin %{y:.1f}%<extra></extra>",
      yaxis: "y2",
    },
  ];

  const dailyData = [
    {
      type: "scatter",
      mode: "lines",
      name: "Daily revenue",
      x: snapshot.daily_revenue.map((point) => point.date),
      y: snapshot.daily_revenue.map((point) => point.value),
      line: { color: "#2F6BFF", width: 2, shape: "spline" },
      fill: "tozeroy",
      fillcolor: "rgba(47,107,255,0.10)",
      hovertemplate: "%{x}<br>$%{y:,.0f}<extra></extra>",
    },
  ];

  const channelData = [
    {
      type: "pie",
      hole: 0.66,
      labels: snapshot.channels.map((channel) => channel.channel),
      values: snapshot.channels.map((channel) => channel.revenue),
      marker: { colors: ["#2F6BFF", "#14B8A6", "#8B5CF6", "#F59E0B"] },
      textinfo: "none",
      hovertemplate: "%{label}<br>$%{value:,.0f}<extra></extra>",
    },
  ];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Command Center · Northwind Retail Co."
        title="Business Overview"
        description={snapshot.summary}
        meta={
          <div className="header-meta-row">
            <Badge tone="info" dot>Measured · {latest?.label}</Badge>
            <span className="meta-text">As of {new Date(snapshot.as_of).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
            <span className="meta-divider" />
            <span className="meta-text">Health {number(health.score, 0)}/100 · Grade {health.grade}</span>
            {activeWorkflow && <Badge tone="warning" dot>{titleCase(activeWorkflow.workflow)} {titleCase(activeWorkflow.status)}</Badge>}
          </div>
        }
        actions={
          <>
            <Button icon={<RefreshCw size={15} />} onClick={refresh}>Refresh twin</Button>
            <Button variant="primary" icon={<Sparkles size={15} />} onClick={startDaily} loading={starting}>
              Run daily cycle
            </Button>
          </>
        }
      />

      <DemoNotice>
        Northwind Retail is a fictional demo company. POS and ERP feeds are deterministic simulated sources and labelled as such.
        All financial figures below are calculated by deterministic rules from those validated records.
      </DemoNotice>

      {criticalAlert && (
        <div className="critical-banner">
          <ShieldAlert size={18} />
          <div>
            <strong>{criticalAlert.title}</strong>
            <span>{criticalAlert.detail}</span>
          </div>
          <Button size="sm" variant="secondary" onClick={() => navigate("/reports?tab=alerts")}>Open incident</Button>
        </div>
      )}

      <div className="kpi-grid">
        <StatCard
          label="Revenue"
          value={money(latest?.revenue, true)}
          change={revenueKpi?.change_pct}
          hint={`vs ${snapshot.prior?.label || "prior month"}`}
          spark={revenueTrend}
          icon={<CircleDollarSign size={18} />}
          accent="blue"
          footer={<span className="stat-footer-note">{number(latest?.units_sold, 0)} units · AOV {money((latest?.revenue || 0) / (latest?.units_sold || 1))}</span>}
        />
        <StatCard
          label="Gross margin"
          value={pct(latest?.gross_margin_pct)}
          change={marginKpi?.change_pp}
          changeSuffix="pp"
          hint="month on month"
          spark={marginTrend}
          icon={<BarChart3 size={18} />}
          accent="teal"
          footer={<span className="stat-footer-note">Gross profit {money(latest?.gross_profit, true)} · target 38%</span>}
        />
        <StatCard
          label="Net profit"
          value={money(latest?.net_profit, true)}
          change={netKpi?.change_pct}
          hint={`${pct(latest?.net_margin_pct)} net margin`}
          spark={profitTrend}
          icon={<TrendingUp size={18} />}
          accent="violet"
          footer={<span className="stat-footer-note">Opex {money(latest?.operating_expenses, true)} · incl. marketing {money(latest?.marketing_spend, true)}</span>}
        />
        <StatCard
          label="Cash position"
          value={money(latest?.cash_balance, true)}
          change={cashKpi?.change_pct}
          hint="period end"
          spark={cashTrend}
          icon={<WalletCards size={18} />}
          accent="amber"
          footer={<span className="stat-footer-note">{number(latest?.cash_runway_months, 1)} months runway · floor $250K</span>}
        />
        <StatCard
          label="Cash runway"
          value={number(latest?.cash_runway_months, 1)}
          unit="months"
          change={runwayKpi?.change_pct}
          hint="at current opex"
          icon={<Banknote size={18} />}
          accent={((latest?.cash_runway_months || 0) < 4) ? "red" : "teal"}
          footer={<span className="stat-footer-note">Inventory {money(latest?.inventory_value, true)} · {number(latest?.inventory_days, 0)} days cover</span>}
        />
        <StatCard
          label="Business health"
          value={number(health.score, 0)}
          unit="/ 100"
          hint={`Grade ${health.grade}`}
          icon={<Gauge size={18} />}
          accent={health.score >= 72 ? "teal" : health.score >= 60 ? "amber" : "red"}
          footer={<span className="stat-footer-note">Data completeness {pct(snapshot.data_quality?.completeness_pct)} · {snapshot.data_quality?.stale_sources?.length || 0} stale sources</span>}
        />
      </div>

      <div className="grid-2-1">
        <Panel
          title="Revenue & margin trajectory"
          subtitle="Measured monthly actuals from validated observations"
          actions={<Badge tone="muted">10 months</Badge>}
        >
          <Chart
            data={chartData}
            height={314}
            layout={{
              barmode: "group",
              bargap: 0.48,
              yaxis: { tickprefix: "$", tickformat: "~s", title: undefined },
              yaxis2: { overlaying: "y", side: "right", ticksuffix: "%", range: [20, 45], showgrid: false },
              margin: { l: 54, r: 46, t: 26, b: 36 },
            }}
          />
        </Panel>

        <Panel
          title="Business health"
          subtitle="Transparent weighted factors"
          actions={<Badge tone={health.score >= 72 ? "success" : health.score >= 60 ? "warning" : "danger"}>{health.grade}</Badge>}
        >
          <div className="health-panel">
            <ScoreRing score={health.score} grade={health.grade} />
            <div className="health-copy">
              <strong>{health.score >= 72 ? "Stable with watch items" : health.score >= 60 ? "Under pressure" : "Elevated risk"}</strong>
              <p>Health blends margin, profitability, liquidity, growth and inventory efficiency.</p>
            </div>
          </div>
          <div className="factor-list">
            {health.factors.map((factor) => (
              <div key={factor.key} className="factor-row">
                <div className="factor-label">
                  <span>{factor.label}</span>
                  <strong>{number(factor.score, 0)}</strong>
                </div>
                <ProgressBar value={factor.score} tone={factor.score >= 70 ? "teal" : factor.score >= 50 ? "amber" : "red"} />
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid-2-1">
        <Panel title="Daily revenue" subtitle="Last 30 days · point-of-sale feeds" actions={<Badge tone="muted">{snapshot.daily_revenue.length} days</Badge>}>
          <Chart data={dailyData} height={248} layout={{ margin: { l: 54, r: 20, t: 16, b: 36 }, yaxis: { tickprefix: "$", tickformat: "~s" } }} />
        </Panel>
        <Panel title="Revenue mix" subtitle={`${latest?.label} · channel share`}>
          <div className="channel-panel">
            <Chart
              data={channelData}
              height={196}
              layout={{ margin: { l: 8, r: 8, t: 8, b: 8 }, showlegend: false }}
            />
            <div className="channel-legend">
              {snapshot.channels.map((channel, index) => (
                <div key={channel.channel} className="channel-row">
                  <span className={`legend-dot legend-${index}`} />
                  <span>{channel.channel}</span>
                  <strong>{money(channel.revenue, true)}</strong>
                  <span>{pct(channel.share_pct)}</span>
                </div>
              ))}
            </div>
          </div>
        </Panel>
      </div>

      <div className="grid-2-1">
        <Panel
          title="Open incidents"
          subtitle={`${data.alert_summary.open} open · ${data.alert_summary.critical} critical · deduplicated by incident`}
          actions={<Button size="sm" variant="ghost" onClick={() => navigate("/reports?tab=alerts")}>All incidents <ArrowRight size={14} /></Button>}
          flush
        >
          {data.alerts.length === 0 ? (
            <EmptyState title="No incidents" description="Monitoring has not raised any business exceptions." icon={<CheckCircle2 size={22} />} />
          ) : (
            <div className="incident-list">
              {data.alerts.slice(0, 5).map((alert) => (
                <button key={alert.id} className="incident-row" onClick={() => navigate(`/reports?tab=alerts&alert=${alert.id}`)}>
                  <span className={`severity-bar severity-${severityTone(alert.severity)}`} />
                  <div className="incident-main">
                    <div className="incident-head">
                      <strong>{alert.title}</strong>
                      <div className="incident-badges">
                        <Badge tone={severityTone(alert.severity)} dot>{alert.severity}</Badge>
                        <StatusBadge status={alert.status} size="sm" />
                      </div>
                    </div>
                    <p>{alert.detail}</p>
                    <div className="incident-meta">
                      <span>{titleCase(alert.area)}</span>
                      <span>First seen {relativeTime(alert.first_seen)}</span>
                      <span>{alert.occurrences} occurrence{alert.occurrences === 1 ? "" : "s"}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>

        <Panel
          title="Decision queue"
          subtitle="Recommendations requiring validation or authorisation"
          actions={<Button size="sm" variant="ghost" onClick={() => navigate("/decisions")}>Open center <ArrowRight size={14} /></Button>}
          flush
        >
          {data.decisions.length === 0 ? (
            <EmptyState
              title="No decisions yet"
              description="Run the daily cycle and investigate an incident to generate recommendations."
              icon={<BrainCircuit size={22} />}
              action={<Button size="sm" onClick={() => navigate("/decisions")}>Go to Decision Center</Button>}
            />
          ) : (
            <div className="decision-mini-list">
              {data.decisions.slice(0, 4).map((decision) => (
                <button key={decision.id} className="decision-mini" onClick={() => navigate(`/decisions?id=${decision.id}`)}>
                  <div className="decision-mini-top">
                    <StatusBadge status={decision.status} size="sm" />
                    <Badge tone={decision.risk_level === "HIGH" ? "danger" : decision.risk_level === "MEDIUM" ? "warning" : "info"}>{decision.risk_level} risk</Badge>
                  </div>
                  <strong>{decision.title}</strong>
                  <div className="decision-mini-bottom">
                    <span>Projected impact <b>{money(decision.expected_financial_impact, true)}</b></span>
                    <span>{pct(decision.confidence * 100, 0)} confidence</span>
                  </div>
                </button>
              ))}
              <div className="decision-queue-foot">
                <span><Clock3 size={14} /> {data.alert_summary.open} incidents monitored · {data.approvals.length} awaiting approval</span>
              </div>
            </div>
          )}
        </Panel>
      </div>

      <div className="grid-2-1">
        <Panel
          title="Intelligence findings"
          subtitle="Measured facts, statistical anomalies and hypotheses are labelled separately"
          actions={<Badge tone={topFindings.some((finding) => finding.severity === "CRITICAL") ? "danger" : "warning"}>{topFindings.length} findings</Badge>}
        >
          {topFindings.length === 0 ? (
            <EmptyState title="No analysis yet" description="The Business Intelligence Agent has not analysed the current snapshot." />
          ) : (
            <div className="finding-list">
              {topFindings.map((finding) => (
                <div key={finding.id} className="finding-row">
                  <div className="finding-icon">
                    {finding.severity === "CRITICAL" || finding.severity === "HIGH" ? <ShieldAlert size={16} /> : <Activity size={16} />}
                  </div>
                  <div className="finding-copy">
                    <div className="finding-head">
                      <strong>{finding.title}</strong>
                      <Badge tone={severityTone(finding.severity)}>{titleCase(finding.kind)}</Badge>
                    </div>
                    <p>{finding.detail}</p>
                    <div className="finding-meta">
                      <span>{titleCase(finding.area)}</span>
                      <span>{pct(finding.confidence * 100, 0)} confidence</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Agent mesh" subtitle={`${data.agents.filter((agent) => agent.status === "ACTIVE").length}/${data.agents.length} agents active`} actions={<Button size="sm" variant="ghost" onClick={() => navigate("/agents")}>Control center <ArrowRight size={14} /></Button>}>
          <div className="agent-mini-grid">
            {data.agents.slice(0, 6).map((agent) => (
              <button key={agent.id} className="agent-mini" onClick={() => navigate("/agents")}>
                <span className={`agent-status-dot status-${agent.status.toLowerCase()}`} />
                <div>
                  <strong>{agent.name.replace(" Agent", "")}</strong>
                  <span>{relativeTime(agent.last_run_at)} · {agent.metrics?.executions || 0} runs</span>
                </div>
              </button>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid-2-1">
        <Panel title="Activity timeline" subtitle="Operational events across data, agents and decisions" flush>
          <div className="timeline">
            {data.events.slice(0, 9).map((event) => (
              <div key={event.id} className="timeline-row">
                <div className={`timeline-dot timeline-${severityTone(event.severity)}`} />
                <div className="timeline-copy">
                  <strong>{event.title}</strong>
                  <span>{event.actor} · {relativeTime(event.created_at)}</span>
                  <p>{event.detail}</p>
                </div>
                <Badge tone={severityTone(event.severity)}>{event.severity}</Badge>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Deterministic logic evidence" subtitle="Custom rules executed for this snapshot">
          <div className="logic-evidence">
            {Object.entries(snapshot.custom_logic?.rule_outputs || {}).slice(0, 5).map(([key, value]: [string, any]) => (
              <div key={key} className="logic-row">
                <span>{titleCase(key)}</span>
                <strong>
                  {typeof Object.values(value || {})[0] === "number" ? number(Number(Object.values(value || {})[0]), 2) : "executed"}
                </strong>
                <Badge tone="success" dot>Sandboxed</Badge>
              </div>
            ))}
            {(!snapshot.custom_logic?.rule_outputs || Object.keys(snapshot.custom_logic.rule_outputs).length === 0) && (
              <EmptyState title="No rule evidence" description="Run the daily cycle to execute the approved business rules." />
            )}
          </div>
          <div className="evidence-foot">
            <span><CheckCircle2 size={14} /> Every metric traces to validated observations</span>
            <Button size="sm" variant="ghost" onClick={() => navigate("/logic")}>Open Logic Studio <ArrowRight size={14} /></Button>
          </div>
        </Panel>
      </div>
    </div>
  );
}
