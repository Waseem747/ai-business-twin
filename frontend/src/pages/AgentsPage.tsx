import { useMemo, useState } from "react";
import {
  Activity,
  Bot,
  CheckCircle2,
  Clock3,
  Cpu,
  GitBranch,
  KeyRound,
  Play,
  RefreshCw,
  Shield,
  Sparkles,
  Terminal,
  Timer,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { api } from "../lib/api";
import { useAuth, canRun } from "../lib/auth";
import { dateTime, relativeTime, statusTone, titleCase } from "../lib/format";
import { useApi, useInterval } from "../lib/useApi";
import { useToast } from "../components/Toast";
import {
  Badge,
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorState,
  JsonBlock,
  LoadingBlock,
  PageHeader,
  Panel,
  ProgressBar,
  StatusBadge,
  Tabs,
} from "../components/ui";
import type { WorkflowRun } from "../lib/types";

export function AgentsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState("agents");
  const [selectedRun, setSelectedRun] = useState<WorkflowRun | null>(null);
  const [runDetail, setRunDetail] = useState<WorkflowRun | null>(null);
  const [starting, setStarting] = useState(false);

  const agents = useApi(api.agents, []);
  const executions = useApi(() => api.agentExecutions(undefined, 80), []);
  const workflows = useApi(() => api.workflows(undefined, 60), []);
  const activeWf = workflows.data?.find((run) => ["RUNNING", "WAITING_APPROVAL", "WAITING_HUMAN_REVIEW"].includes(run.status));

  useInterval(() => {
    if (activeWf) {
      workflows.refresh();
      executions.refresh();
      agents.refresh();
    }
  }, activeWf ? 6000 : null);

  const stats = useMemo(() => {
    const list = agents.data || [];
    return {
      total: list.length,
      active: list.filter((agent) => agent.status === "ACTIVE").length,
      degraded: list.filter((agent) => agent.status === "DEGRADED").length,
      executions: list.reduce((total, agent) => total + Number(agent.metrics?.executions || 0), 0),
      failures: list.reduce((total, agent) => total + Number(agent.metrics?.failures || 0), 0),
      avg: list.length ? list.reduce((total, agent) => total + Number(agent.metrics?.avg_duration_ms || 0), 0) / list.length : 0,
    };
  }, [agents.data]);

  async function startDaily() {
    setStarting(true);
    try {
      await api.runWorkflow("daily_bi", {});
      toast.push("Daily intelligence workflow started.", "success");
      workflows.refresh();
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to start workflow", "danger");
    } finally {
      setStarting(false);
    }
  }

  async function openRun(run: WorkflowRun) {
    setSelectedRun(run);
    setRunDetail(null);
    try {
      setRunDetail(await api.workflow(run.id));
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to load workflow", "danger");
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Orchestration · LangGraph"
        title="Agent Control Center"
        description="Inspect every specialised agent, its permissions, active workflows and execution history."
        meta={
          <div className="header-meta-row">
            <Badge tone="success" dot>{stats.active} active</Badge>
            {stats.degraded > 0 && <Badge tone="danger" dot>{stats.degraded} degraded</Badge>}
            <span className="meta-text">{stats.executions} total executions</span>
            <span className="meta-divider" />
            <span className="meta-text">{activeWf ? `Active: ${titleCase(activeWf.workflow)}` : "All workflows idle"}</span>
          </div>
        }
        actions={
          <>
            <Button icon={<RefreshCw size={15} />} onClick={() => { agents.refresh(); workflows.refresh(); executions.refresh(); }}>Refresh</Button>
            {canRun(user) && <Button variant="primary" icon={<Play size={15} />} loading={starting} onClick={startDaily}>Run daily cycle</Button>}
          </>
        }
      />

      <div className="agent-stat-row">
        <Card className="mini-stat"><div className="mini-stat-icon"><Bot size={18} /></div><div><span>Registered agents</span><strong>{stats.total}</strong></div></Card>
        <Card className="mini-stat"><div className="mini-stat-icon"><CheckCircle2 size={18} /></div><div><span>Successful executions</span><strong>{Math.max(stats.executions - stats.failures, 0)}</strong></div></Card>
        <Card className="mini-stat"><div className="mini-stat-icon"><TriangleAlert size={18} /></div><div><span>Recorded failures</span><strong>{stats.failures}</strong></div></Card>
        <Card className="mini-stat"><div className="mini-stat-icon"><Timer size={18} /></div><div><span>Avg agent duration</span><strong>{Math.round(stats.avg)} ms</strong></div></Card>
      </div>

      <Tabs
        tabs={[
          { key: "agents", label: "Agents", count: agents.data?.length },
          { key: "workflows", label: "Workflows", count: workflows.data?.length },
          { key: "executions", label: "Execution log", count: executions.data?.length },
        ]}
        active={tab}
        onChange={setTab}
      />

      {tab === "agents" && (
        <div className="agent-grid">
          {agents.loading && !agents.data && Array.from({ length: 3 }).map((_, index) => <Card key={index} className="agent-card"><LoadingBlock lines={5} /></Card>)}
          {agents.error && <ErrorState message={agents.error} onRetry={agents.refresh} />}
          {(agents.data || []).map((agent) => (
            <Card key={agent.id} className="agent-card">
              <div className="agent-card-head">
                <div className="agent-avatar"><Cpu size={18} /></div>
                <div className="agent-card-title">
                  <strong>{agent.name}</strong>
                  <span>{agent.role}</span>
                </div>
                <Badge tone={statusTone(agent.status)} dot>{titleCase(agent.status)}</Badge>
              </div>
              <p className="agent-description">{agent.description}</p>
              <div className="agent-metrics">
                <div><span>Executions</span><strong>{agent.metrics?.executions || 0}</strong></div>
                <div><span>Failures</span><strong>{agent.metrics?.failures || 0}</strong></div>
                <div><span>Avg duration</span><strong>{Math.round(agent.metrics?.avg_duration_ms || 0)} ms</strong></div>
                <div><span>Last run</span><strong>{relativeTime(agent.last_run_at)}</strong></div>
              </div>
              <div className="agent-permissions">
                <div className="agent-section-label"><KeyRound size={13} /> Permissions</div>
                <div className="chip-wrap">{agent.permissions.map((permission) => <span key={permission} className="chip">{permission}</span>)}</div>
              </div>
              <div className="agent-tools">
                <div className="agent-section-label"><Wrench size={13} /> Tools</div>
                <div className="chip-wrap">{agent.tools.map((tool) => <span key={tool} className="chip chip-muted">{tool}</span>)}</div>
              </div>
              {agent.last_error && <div className="agent-error"><TriangleAlert size={14} /> {agent.last_error}</div>}
            </Card>
          ))}
        </div>
      )}

      {tab === "workflows" && (
        <Panel
          title="Workflow runs"
          subtitle="Durable LangGraph checkpoints with human-in-the-loop interruptions"
          actions={<Badge tone="violet"><GitBranch size={12} /> Checkpointed</Badge>}
          flush
        >
          {workflows.loading && !workflows.data ? <LoadingBlock lines={8} /> : workflows.error ? <ErrorState message={workflows.error} onRetry={workflows.refresh} /> : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Workflow</th><th>Status</th><th>Trigger</th><th>Started</th><th>Duration</th><th>Summary</th><th /></tr>
                </thead>
                <tbody>
                  {(workflows.data || []).map((run) => {
                    const duration = run.finished_at ? (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000 : null;
                    return (
                      <tr key={run.id} onClick={() => openRun(run)} className="row-clickable">
                        <td><strong>{titleCase(run.workflow)}</strong><span className="table-sub mono">{run.id.slice(-10)}</span></td>
                        <td><StatusBadge status={run.status} /></td>
                        <td><span className="table-sub">{titleCase(run.trigger)}</span></td>
                        <td><span className="table-sub">{dateTime(run.started_at)}</span></td>
                        <td>{duration !== null ? `${duration.toFixed(1)}s` : "running"}</td>
                        <td className="cell-summary">{run.summary || run.error || "—"}</td>
                        <td><Button size="sm" variant="ghost">Inspect</Button></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {(workflows.data || []).length === 0 && <EmptyState title="No workflow runs" description="Start a daily cycle or investigate an alert." />}
            </div>
          )}
        </Panel>
      )}

      {tab === "executions" && (
        <Panel title="Agent execution log" subtitle="Structured outputs, model provider and duration per task" flush>
          {executions.loading && !executions.data ? <LoadingBlock lines={8} /> : executions.error ? <ErrorState message={executions.error} onRetry={executions.refresh} /> : (
            <div className="execution-feed">
              {(executions.data || []).map((execution) => (
                <div key={execution.id} className="execution-row">
                  <div className="execution-time"><strong>{relativeTime(execution.created_at)}</strong><span>{dateTime(execution.created_at)}</span></div>
                  <div className={`execution-marker ${execution.status === "FAILED" ? "marker-danger" : "marker-success"}`} />
                  <div className="execution-copy">
                    <div className="execution-head">
                      <strong>{titleCase(execution.agent_key)}</strong>
                      <StatusBadge status={execution.status} size="sm" />
                      <Badge tone="muted" className="badge-sm">{execution.model_provider}</Badge>
                      <span className="execution-duration">{Math.round(execution.duration_ms || 0)} ms</span>
                    </div>
                    <p>{execution.summary}</p>
                    {execution.error && <span className="execution-error">{execution.error}</span>}
                    <div className="execution-chips">
                      {Object.entries(execution.output_summary || {}).slice(0, 3).map(([key, value]) => (
                        <span key={key} className="chip chip-muted">{titleCase(key)}: {typeof value === "object" ? "structured" : String(value).slice(0, 38)}</span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
              {(executions.data || []).length === 0 && <EmptyState title="No executions recorded" />}
            </div>
          )}
        </Panel>
      )}

      <Drawer
        open={Boolean(selectedRun)}
        onClose={() => { setSelectedRun(null); setRunDetail(null); }}
        title={selectedRun ? titleCase(selectedRun.workflow) : "Workflow"}
        subtitle={selectedRun ? `${selectedRun.id} · ${titleCase(selectedRun.trigger)} trigger` : undefined}
      >
        {!runDetail ? <LoadingBlock lines={8} /> : (
          <div className="stack-lg">
            <div className="drawer-status-row">
              <StatusBadge status={runDetail.status} />
              <span>Started {dateTime(runDetail.started_at)}</span>
              {runDetail.finished_at && <span>Finished {dateTime(runDetail.finished_at)}</span>}
            </div>
            {runDetail.error && <div className="error-banner">{runDetail.error}</div>}
            <div className="drawer-summary"><Activity size={16} /><p>{runDetail.summary || "No summary recorded."}</p></div>

            <div>
              <h3 className="section-title">Execution steps</h3>
              <div className="workflow-steps">
                {(runDetail.steps || []).map((step) => (
                  <div key={step.id} className="workflow-step">
                    <div className={`step-marker step-${statusTone(step.status)}`} />
                    <div className="step-copy">
                      <div className="step-head"><strong>{titleCase(step.node)}</strong><StatusBadge status={step.status} size="sm" /></div>
                      <p>{step.summary}</p>
                      <span className="step-time">{dateTime(step.finished_at || step.started_at)}</span>
                    </div>
                  </div>
                ))}
                {(runDetail.steps || []).length === 0 && <EmptyState title="No step records" />}
              </div>
            </div>

            <div>
              <h3 className="section-title">Checkpoint state</h3>
              <JsonBlock value={runDetail.state || {}} maxHeight={420} />
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
