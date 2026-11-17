import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  BadgeCheck,
  BrainCircuit,
  Check,
  CheckCircle2,
  CircleDollarSign,
  ClipboardCheck,
  Clock3,
  FileSearch,
  FlaskConical,
  GitCompareArrows,
  Info,
  LockKeyhole,
  MessageSquareWarning,
  Play,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { canApprove, canRun, useAuth } from "../lib/auth";
import { money, number, pct, relativeTime, severityTone, statusTone, titleCase, verdictTone } from "../lib/format";
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
  ProgressBar,
  StatusBadge,
  Tabs,
} from "../components/ui";
import type { Decision, DecisionReview } from "../lib/types";

export function DecisionCenterPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const decisions = useApi(() => api.decisions(), []);
  const [selectedId, setSelectedId] = useState<string | null>(params.get("id"));
  const [detail, setDetail] = useState<Decision | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [tab, setTab] = useState("overview");
  const [comment, setComment] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [starting, setStarting] = useState(false);
  const [filter, setFilter] = useState("all");
  const workflows = useApi(() => api.workflows(undefined, 20), []);

  const list = decisions.data || [];
  const activeDecision = useMemo(() => list.find((decision) => decision.id === selectedId) || null, [list, selectedId]);
  const pendingWorkflow = workflows.data?.find((run) => run.workflow === "decision_execution" && ["RUNNING", "WAITING_APPROVAL", "WAITING_HUMAN_REVIEW"].includes(run.status));

  useEffect(() => {
    if (!selectedId && list.length) {
      setSelectedId(list[0].id);
    }
  }, [list, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    api
      .decision(selectedId)
      .then((result) => {
        if (active) setDetail(result);
      })
      .catch((exc) => toast.push(exc?.message || "Unable to load decision", "danger"))
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedId, decisions.data]);

  useInterval(() => {
    if (detail && ["AWAITING_APPROVAL", "AUDITED", "EXECUTING"].includes(detail.status)) {
      decisions.refresh();
      setDetail((current) => current);
    }
    if (pendingWorkflow) workflows.refresh();
  }, detail && ["AWAITING_APPROVAL", "AUDITED", "EXECUTING"].includes(detail.status) ? 6000 : null);

  function choose(id: string) {
    setSelectedId(id);
    setParams({ id });
    setTab("overview");
    setComment("");
  }

  async function startDecisionWorkflow() {
    setStarting(true);
    try {
      await api.runWorkflow("decision_execution", {});
      toast.push("Decision workflow started. The auditor will review the recommendation.", "success");
      workflows.refresh();
      window.setTimeout(() => decisions.refresh(), 5000);
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to start decision workflow", "danger");
    } finally {
      setStarting(false);
    }
  }

  async function decide(approved: boolean) {
    const approval = detail?.approval;
    if (!approval) return;
    setDeciding(true);
    try {
      const result = await api.decideApproval(approval.id, approved, comment);
      toast.push(result.message || (approved ? "Decision approved." : "Decision rejected."), approved ? "success" : "info");
      setComment("");
      await decisions.refresh();
      if (selectedId) {
        const refreshed = await api.decision(selectedId);
        setDetail(refreshed);
      }
      window.setTimeout(() => {
        decisions.refresh();
        workflows.refresh();
      }, 4000);
    } catch (exc: any) {
      toast.push(exc?.message || "Unable to record approval", "danger");
    } finally {
      setDeciding(false);
    }
  }

  const filtered = list.filter((decision) => {
    if (filter === "all") return true;
    if (filter === "approval") return decision.status === "AWAITING_APPROVAL";
    if (filter === "executed") return ["EXECUTED", "VERIFIED", "FAILED"].includes(decision.status);
    if (filter === "rejected") return decision.status === "REJECTED";
    return true;
  });
  const current = detail || activeDecision;

  return (
    <div className="page page-wide">
      <PageHeader
        eyebrow="Governance · Independent audit"
        title="Decision Center"
        description="Recommendations are generated from simulated alternatives, independently audited and only executed after policy-compliant authorisation."
        meta={
          <div className="header-meta-row">
            <Badge tone="warning" dot>{list.filter((decision) => decision.status === "AWAITING_APPROVAL").length} awaiting approval</Badge>
            <Badge tone="info" dot>{list.filter((decision) => decision.status === "AUDITED").length} audited</Badge>
            <span className="meta-divider" />
            <span className="meta-text">{list.filter((decision) => ["EXECUTED", "VERIFIED"].includes(decision.status)).length} executed</span>
          </div>
        }
        actions={
          <>
            <Button icon={<RefreshCw size={15} />} onClick={() => { decisions.refresh(); if (selectedId) api.decision(selectedId).then(setDetail); }}>Refresh</Button>
            {canRun(user) && (
              <Button variant="primary" icon={<Sparkles size={15} />} loading={starting} onClick={startDecisionWorkflow} disabled={Boolean(pendingWorkflow)}>
                {pendingWorkflow ? "Workflow in progress" : "Analyse latest anomaly"}
              </Button>
            )}
          </>
        }
      />

      <div className="split-layout">
        <aside className="decision-list-column">
          <div className="decision-filter">
            <div className="filter-tabs">
              {[
                ["all", "All"],
                ["approval", "Approval"],
                ["executed", "Executed"],
                ["rejected", "Rejected"],
              ].map(([key, label]) => (
                <button key={key} className={`filter-tab ${filter === key ? "filter-tab-active" : ""}`} onClick={() => setFilter(key)}>{label}</button>
              ))}
            </div>
          </div>
          {decisions.loading && !decisions.data ? <LoadingBlock lines={8} /> : decisions.error ? <ErrorState message={decisions.error} onRetry={decisions.refresh} /> : (
            <div className="decision-list">
              {filtered.map((decision) => (
                <button
                  key={decision.id}
                  className={`decision-card ${current?.id === decision.id ? "decision-card-active" : ""}`}
                  onClick={() => choose(decision.id)}
                >
                  <div className="decision-card-top">
                    <StatusBadge status={decision.status} size="sm" />
                    <Badge tone={decision.risk_level === "HIGH" ? "danger" : decision.risk_level === "MEDIUM" ? "warning" : "info"} className="badge-sm">{decision.risk_level}</Badge>
                  </div>
                  <strong>{decision.title}</strong>
                  <p>{decision.issue}</p>
                  <div className="decision-card-meta">
                    <span><CircleDollarSign size={13} /> {money(decision.expected_financial_impact, true)} projected</span>
                    <span>{relativeTime(decision.created_at)}</span>
                  </div>
                  <div className="decision-card-progress"><ProgressBar value={decision.confidence * 100} tone={decision.confidence > 0.7 ? "teal" : "amber"} /></div>
                </button>
              ))}
              {filtered.length === 0 && <EmptyState title="No matching decisions" description="Run the daily intelligence cycle or investigate an incident." icon={<Scale size={22} />} />}
            </div>
          )}
        </aside>

        <section className="decision-detail-column">
          {!current ? (
            <Card className="detail-placeholder">
              <EmptyState
                title="Select a decision"
                description="Choose a recommendation to review its evidence, independent audit and execution trail."
                icon={<ShieldCheck size={24} />}
              />
            </Card>
          ) : detailLoading && !detail ? (
            <Card><LoadingBlock lines={10} /></Card>
          ) : (
            <DecisionDetail
              decision={current}
              tab={tab}
              setTab={setTab}
              comment={comment}
              setComment={setComment}
              decide={decide}
              deciding={deciding}
              canApprove={canApprove(user)}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function DecisionDetail({
  decision,
  tab,
  setTab,
  comment,
  setComment,
  decide,
  deciding,
  canApprove,
}: {
  decision: Decision;
  tab: string;
  setTab: (key: string) => void;
  comment: string;
  setComment: (value: string) => void;
  decide: (approved: boolean) => void;
  deciding: boolean;
  canApprove: boolean;
}) {
  const review: DecisionReview | undefined = decision.reviews?.[0];
  const approval = decision.approval;
  const chosen = decision.chosen || {};
  const benchmark = decision.alternatives?.find((alt) => alt.selected) || decision.alternatives?.[0];

  return (
    <div className="stack-lg">
      <Card className="decision-hero">
        <div className="decision-hero-top">
          <div>
            <div className="eyebrow">Recommendation</div>
            <h2>{decision.title}</h2>
            <p>{decision.issue}</p>
          </div>
          <div className="decision-hero-badges">
            <StatusBadge status={decision.status} />
            <Badge tone={decision.risk_level === "HIGH" ? "danger" : decision.risk_level === "MEDIUM" ? "warning" : "info"} dot>{decision.risk_level} risk</Badge>
            {decision.requires_approval && <Badge tone="violet" dot><LockKeyhole size={12} /> Human approval</Badge>}
          </div>
        </div>
        <div className="decision-metric-row">
          <div className="decision-metric"><span>Projected 12-month impact</span><strong className={decision.expected_financial_impact >= 0 ? "positive" : "negative"}>{money(decision.expected_financial_impact)}</strong><small>Simulated, not measured</small></div>
          <div className="decision-metric"><span>Confidence</span><strong>{pct(decision.confidence * 100, 0)}</strong><small>Model + data quality</small></div>
          <div className="decision-metric"><span>Implementation cost</span><strong>{money(chosen.implementation_cost)}</strong><small>{chosen.time_horizon_months || "—"} month horizon</small></div>
          <div className="decision-metric"><span>Reversibility</span><strong>{titleCase(decision.reversibility)}</strong><small>{chosen.type ? titleCase(chosen.type) : "Intervention"}</small></div>
        </div>
        <div className="decision-objective"><Info size={15} /><span>{decision.objective}</span></div>
      </Card>

      {decision.status === "AWAITING_APPROVAL" && approval?.status === "PENDING" && (
        <Card className="approval-card">
          <div className="approval-head">
            <div className="approval-shield"><LockKeyhole size={20} /></div>
            <div>
              <strong>Human authorisation required</strong>
              <p>
                {approval.policy?.type === "AUDIT_ESCALATION"
                  ? "The independent auditor escalated this recommendation. Accepting it means knowingly accepting the residual risk documented below."
                  : "Policy requires a named approver before the Action Execution Agent can proceed."}
              </p>
            </div>
            <Badge tone="violet">{titleCase(approval.policy?.type || "approval")}</Badge>
          </div>
          <div className="approval-conditions">
            {(approval.policy?.conditions || review?.conditions || []).slice(0, 4).map((condition: string) => (
              <div key={condition} className="condition-row"><CheckCircle2 size={14} /><span>{condition}</span></div>
            ))}
          </div>
          {canApprove ? (
            <div className="approval-form">
              <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Approval note — record the rationale, conditions accepted and any required follow-up." rows={3} />
              <div className="approval-actions">
                <Button variant="danger" icon={<X size={15} />} loading={deciding} onClick={() => decide(false)}>Reject</Button>
                <Button variant="success" icon={<Check size={15} />} loading={deciding} onClick={() => decide(true)}>Approve & execute</Button>
              </div>
              <p className="approval-hint">Your decision is recorded in the immutable audit log. Execution uses idempotency keys and is independently verified.</p>
            </div>
          ) : (
            <div className="permission-note"><LockKeyhole size={15} /> Your role cannot authorise this decision. Sign in as an APPROVER or ADMIN to act.</div>
          )}
        </Card>
      )}

      <div className="tab-row-with-meta">
        <Tabs
          tabs={[
            { key: "overview", label: "Overview" },
            { key: "evidence", label: "Evidence", count: decision.evidence?.length },
            { key: "alternatives", label: "Alternatives", count: decision.alternatives?.length },
            { key: "audit", label: "Audit", count: decision.reviews?.length },
            { key: "execution", label: "Execution" },
          ]}
          active={tab}
          onChange={setTab}
        />
        <span className="meta-text mono">{decision.id.slice(-12)}</span>
      </div>

      {tab === "overview" && (
        <div className="stack-lg">
          <Panel title="Decision rationale" subtitle="LLM commentary only — figures originate from deterministic logic and simulation">
            <p className="long-copy">{decision.rationale}</p>
            <div className="separation-strip">
              <Badge tone="info">PROJECTED</Badge>
              <span>All financial impact figures are simulated. Measured results are tracked separately after execution.</span>
            </div>
          </Panel>

          <div className="grid-2-1">
            <Panel title="Chosen intervention" subtitle={chosen.title}>
              <DefinitionList
                items={[
                  { label: "Type", value: titleCase(chosen.type) },
                  { label: "Action", value: titleCase(chosen.action_type) },
                  { label: "Implementation cost", value: money(chosen.implementation_cost) },
                  { label: "Risk", value: <Badge tone={decision.risk_level === "HIGH" ? "danger" : "warning"}>{decision.risk_level}</Badge> },
                  { label: "Reversibility", value: titleCase(decision.reversibility) },
                  { label: "Simulation", value: decision.simulation_id ? <span className="mono">{decision.simulation_id.slice(-10)}</span> : "—" },
                ]}
              />
              <div className="assumption-list">
                {(chosen.assumptions || []).map((assumption: string) => (
                  <div key={assumption} className="assumption-row"><span className="assumption-dot" />{assumption}</div>
                ))}
              </div>
            </Panel>
            <Panel title="Audit snapshot" subtitle={review ? `Round ${review.round} · ${review.reviewer}` : "Awaiting audit"}>
              {review ? (
                <>
                  <div className={`verdict verdict-${verdictTone(review.verdict)}`}>
                    <ShieldCheck size={20} />
                    <div><span>Verdict</span><strong>{titleCase(review.verdict)}</strong></div>
                  </div>
                  <div className="audit-mini-checks">
                    {review.findings?.checks?.slice(0, 5).map((check: any) => (
                      <div key={check.key} className="audit-mini-check">
                        {check.passed ? <CheckCircle2 size={14} className="positive" /> : <AlertTriangle size={14} className="negative" />}
                        <span>{check.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className="audit-mini-conditions">
                    <span>{review.conditions.length} condition(s)</span>
                    <Badge tone="muted">{pct(decision.confidence * 100, 0)} confidence</Badge>
                  </div>
                </>
              ) : <EmptyState title="No audit yet" description="The independent auditor has not reviewed this decision." />}
            </Panel>
          </div>

          <Panel title="Projected outcomes" subtitle="From the deterministic scenario model">
            {decision.simulation ? (
              <div className="projection-grid">
                <div><span>Exit gross margin</span><strong>{pct(decision.simulation.results.scenario.summary.exit_gross_margin_pct)}</strong><small>baseline {pct(decision.simulation.results.scenario.summary.baseline_exit_gross_margin_pct)}</small></div>
                <div><span>Exit cash</span><strong>{money(decision.simulation.results.scenario.summary.exit_cash_balance, true)}</strong><small>minimum {money(decision.simulation.results.scenario.summary.minimum_cash, true)}</small></div>
                <div><span>12-month net profit</span><strong>{money(decision.simulation.results.scenario.summary.net_profit_12m, true)}</strong><small>baseline {money(decision.simulation.results.scenario.summary.baseline_net_profit_12m, true)}</small></div>
                <div><span>Monte Carlo P10–P90</span><strong>{money(decision.simulation.monte_carlo?.p10, true)} – {money(decision.simulation.monte_carlo?.p90, true)}</strong><small>{decision.simulation.monte_carlo?.probability_above_baseline}% beat baseline</small></div>
              </div>
            ) : <EmptyState title="No simulation linked" />}
          </Panel>
        </div>
      )}

      {tab === "evidence" && (
        <div className="stack-lg">
          {decision.evidence?.map((evidence, index) => (
            <Panel key={index} title={titleCase(evidence.type)} subtitle={evidence.source}>
              <JsonBlock value={evidence} maxHeight={320} />
            </Panel>
          ))}
          {(!decision.evidence || decision.evidence.length === 0) && <EmptyState title="No evidence recorded" />}
        </div>
      )}

      {tab === "alternatives" && (
        <Panel title="Ranked alternatives" subtitle="Every option scored by deterministic simulation, risk, cost and reversibility" flush>
          <div className="alternatives-table">
            <div className="alternative-head">
              <span>Intervention</span><span>Projected impact</span><span>Exit margin</span><span>Risk</span><span>Score</span><span />
            </div>
            {(decision.alternatives || []).map((alternative) => (
              <div key={alternative.key} className={`alternative-row ${alternative.selected ? "alternative-selected" : ""}`}>
                <div className="alternative-title">
                  <strong>{alternative.title}</strong>
                  <span>{titleCase(alternative.type)} · {alternative.time_horizon_months}m · {money(alternative.implementation_cost, true)} cost</span>
                  {alternative.selected && <Badge tone="success" dot>Selected</Badge>}
                </div>
                <strong className={alternative.expected_impact_12m >= 0 ? "positive" : "negative"}>{money(alternative.expected_impact_12m, true)}</strong>
                <span>{pct(alternative.exit_gross_margin_pct)}</span>
                <Badge tone={alternative.risk_level === "HIGH" ? "danger" : alternative.risk_level === "MEDIUM" ? "warning" : "info"}>{alternative.risk_level}</Badge>
                <span>{number(alternative.score, 2)}</span>
                <span className="mono subtle">{pct(alternative.confidence * 100, 0)}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {tab === "audit" && (
        <div className="stack-lg">
          {(decision.reviews || []).map((item) => (
            <Panel
              key={item.id}
              title={`Audit round ${item.round}`}
              subtitle={`${item.reviewer} · ${item.model_provider}`}
              actions={<Badge tone={verdictTone(item.verdict)} dot>{titleCase(item.verdict)}</Badge>}
            >
              <div className="audit-narrative"><BrainCircuit size={16} /><p>{item.findings?.narrative?.text || "No narrative recorded."}</p></div>
              <div className="check-grid">
                {item.findings?.checks?.map((check: any) => (
                  <div key={check.key} className={`check-card ${check.passed ? "check-pass" : "check-fail"}`}>
                    <div className="check-head">
                      {check.passed ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
                      <strong>{check.label}</strong>
                      <Badge tone={check.severity === "HIGH" || check.severity === "CRITICAL" ? "danger" : "muted"} className="badge-sm">{check.severity}</Badge>
                    </div>
                    <p>{check.detail}</p>
                  </div>
                ))}
              </div>
              {item.conditions.length > 0 && (
                <div className="conditions-block">
                  <h4><ClipboardCheck size={15} /> Conditions</h4>
                  {item.conditions.map((condition) => <div key={condition} className="condition-row"><CheckCircle2 size={14} /><span>{condition}</span></div>)}
                </div>
              )}
              <details className="raw-details"><summary>Audit reasons & raw findings</summary><JsonBlock value={{ reasons: item.reasons, findings: item.findings }} /></details>
            </Panel>
          ))}
          {(!decision.reviews || decision.reviews.length === 0) && <EmptyState title="No audit rounds" description="This recommendation has not yet passed through the independent auditor." />}
        </div>
      )}

      {tab === "execution" && (
        <div className="stack-lg">
          {decision.action ? (
            <>
              <Panel title="Action execution" subtitle={`${decision.action.action_type} → ${decision.action.target_system}`} actions={<StatusBadge status={decision.action.status} />}>
                <DefinitionList
                  items={[
                    { label: "Executed by", value: "Action Execution Agent" },
                    { label: "Executed at", value: decision.action.executed_at ? relativeTime(decision.action.executed_at) : "—" },
                    { label: "External ID", value: <span className="mono">{decision.action.external_id || "—"}</span> },
                    { label: "Idempotent", value: "Yes · single action per decision" },
                    { label: "Simulated target", value: decision.action.simulated ? <Badge tone="violet">SIMULATED ERP</Badge> : <Badge tone="danger">LIVE</Badge> },
                  ]}
                />
                <div className="separation-strip"><Badge tone="violet">SIMULATED</Badge><span>No real external API was called. The operational request was written to the local integration simulator.</span></div>
              </Panel>
              <div className="grid-2-1">
                <Panel title="Independent verification" subtitle="Execution Verification Agent">
                  {decision.action.verification ? (
                    <>
                      <div className={`verification-box verification-${statusTone(decision.action.verification.status)}`}>
                        {decision.action.verification.status === "VERIFIED" ? <BadgeCheck size={22} /> : <ShieldAlert size={22} />}
                        <div><strong>{titleCase(decision.action.verification.status)}</strong><p>{decision.action.verification.notes}</p></div>
                      </div>
                      <div className="difference-list">
                        {(decision.action.verification.differences || []).map((difference: any) => (
                          <div key={difference.field} className="difference-row">
                            <span className="mono">{difference.field}</span>
                            <span>expected {String(difference.expected)}</span>
                            <span>actual {String(difference.actual)}</span>
                          </div>
                        ))}
                        {(decision.action.verification.differences || []).length === 0 && <div className="difference-ok"><CheckCircle2 size={14} /> Operational state matches the approved request.</div>}
                      </div>
                    </>
                  ) : <EmptyState title="Verification pending" />}
                </Panel>
                <Panel title="Projected vs measured" subtitle="These categories are never merged">
                  <div className="impact-compare">
                    <div><span>Projected</span><strong>{money(decision.action.expected_outcome?.net_profit_delta_12m, true)}</strong><small>12-month net profit impact · SIMULATED</small></div>
                    <div><span>Measured</span><strong>{decision.action.verification?.business_impact?.measured ? money(decision.action.verification.business_impact.measured, true) : "Pending"}</strong><small>{decision.action.verification?.business_impact?.note || "Follow-up observation window required."}</small></div>
                  </div>
                </Panel>
              </div>
            </>
          ) : (
            <Panel title="Execution trail">
              <EmptyState
                title={decision.status === "REJECTED" ? "Decision was rejected" : "No action executed"}
                description={decision.status === "AWAITING_APPROVAL" ? "Execution is blocked until a human approver authorises the decision." : "Once approved, the action agent executes with idempotency and the verification agent checks operational state."}
                icon={decision.status === "REJECTED" ? <X size={22} /> : <Clock3 size={22} />}
              />
            </Panel>
          )}
        </div>
      )}

      <div className="decision-footnote">
        <LockKeyhole size={14} />
        <span>Auditor independence: the Independent Decision Auditor has read-only evidence access and no action execution tools.</span>
      </div>
    </div>
  );
}
