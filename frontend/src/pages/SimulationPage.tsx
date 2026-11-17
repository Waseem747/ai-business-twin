import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Check,
  CircleDollarSign,
  Clock3,
  FlaskConical,
  Gauge,
  History,
  Info,
  LineChart,
  Play,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert,
  WalletCards,
} from "lucide-react";
import { api } from "../lib/api";
import { canRun, useAuth } from "../lib/auth";
import { money, number, pct, relativeTime, titleCase } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useToast } from "../components/Toast";
import { Chart } from "../components/Chart";
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
import type { Simulation } from "../lib/types";

const defaults: Record<string, number> = {
  price_change_pct: 0,
  marketing_change_pct: 0,
  cogs_change_pct: 0,
  discount_change_pp: 0,
  headcount_change: 0,
  inventory_change_pct: 0,
  revenue_impact_pct: 0,
  other_opex_change_pct: 0,
  one_off_cost: 0,
};

const primaryParams = [
  { key: "price_change_pct", label: "Price change", unit: "%", min: -10, max: 10, step: 0.5, description: "Applied to the retail book. Wholesale is contractually locked." },
  { key: "marketing_change_pct", label: "Marketing spend", unit: "%", min: -50, max: 100, step: 5, description: "Revenue response uses a diminishing-returns elasticity, not a 1:1 ratio." },
  { key: "cogs_change_pct", label: "Landed COGS", unit: "%", min: -15, max: 15, step: 0.5, description: "Supplier concession or cost escalation flowing into gross profit." },
  { key: "discount_change_pp", label: "Discount depth", unit: "pp", min: -8, max: 8, step: 0.5, description: "Reducing discount depth raises realised price but affects volume." },
];

const advancedParams = [
  { key: "headcount_change", label: "Headcount change", unit: "people", min: -20, max: 20, step: 1 },
  { key: "inventory_change_pct", label: "Inventory change", unit: "%", min: -30, max: 30, step: 1 },
  { key: "revenue_impact_pct", label: "New revenue initiative", unit: "%", min: -20, max: 30, step: 1 },
  { key: "other_opex_change_pct", label: "Other opex", unit: "%", min: -20, max: 20, step: 1 },
  { key: "one_off_cost", label: "One-off cost", unit: "USD", min: 0, max: 250000, step: 1000 },
];

const presets = [
  {
    name: "Margin recovery",
    description: "Supplier concession, discount discipline and modest pricing.",
    parameters: { ...defaults, cogs_change_pct: -5, discount_change_pp: -3, price_change_pct: 2, one_off_cost: 25000 },
  },
  {
    name: "Growth push",
    description: "Step up marketing, add sales capacity and launch a new range.",
    parameters: { ...defaults, marketing_change_pct: 20, headcount_change: 4, revenue_impact_pct: 4, one_off_cost: 15000 },
  },
  {
    name: "Cash preservation",
    description: "Release inventory, trim discretionary costs and reduce marketing.",
    parameters: { ...defaults, inventory_change_pct: -8, other_opex_change_pct: -6, marketing_change_pct: -10, one_off_cost: 5000 },
  },
];

export function SimulationPage() {
  const { user } = useAuth();
  const toast = useToast();
  const assumptions = useApi(api.simulationAssumptions, []);
  const history = useApi(api.simulations, []);
  const [parameters, setParameters] = useState<Record<string, number>>({ ...defaults });
  const [name, setName] = useState("Untitled scenario");
  const [advanced, setAdvanced] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Simulation | null>(null);
  const [tab, setTab] = useState("projection");

  useEffect(() => {
    if (!result && history.data?.length) {
      const latest = history.data[0];
      setResult(latest);
      setName(latest.name);
      if (latest.assumptions?.parameter_assumptions) {
        setParameters({ ...defaults, ...latest.assumptions.parameter_assumptions });
      }
    }
  }, [history.data, result]);

  const definition = useMemo(() => {
    const map: Record<string, any> = {};
    [...primaryParams, ...advancedParams].forEach((param) => (map[param.key] = param));
    return map;
  }, []);

  const scenario = result?.results?.scenario;
  const summary = scenario?.summary;
  const monteCarlo = result?.monte_carlo;
  const sensitivity = result?.sensitivity;

  async function runSimulation() {
    setRunning(true);
    try {
      const response = await api.runSimulation({
        parameters,
        name: name || "Untitled scenario",
        description: "Interactive simulation created from the management dashboard.",
        with_monte_carlo: true,
      });
      setResult(response.simulation);
      toast.push("Simulation completed in isolation. Production state was not modified.", "success");
      history.refresh();
      setTab("projection");
    } catch (exc: any) {
      toast.push(exc?.message || "Simulation failed", "danger");
    } finally {
      setRunning(false);
    }
  }

  function applyPreset(preset: (typeof presets)[number]) {
    setParameters({ ...preset.parameters });
    setName(preset.name);
    toast.push(`${preset.name} assumptions loaded. Adjust any driver before running.`, "info");
  }

  function selectSimulation(simulation: Simulation) {
    setResult(simulation);
    setName(simulation.name);
    if (simulation.assumptions?.parameter_assumptions) {
      setParameters({ ...defaults, ...simulation.assumptions.parameter_assumptions });
    }
    setTab("projection");
  }

  const chartBase = scenario?.baseline_monthly || [];
  const chartScenario = scenario?.monthly || [];
  const months = chartScenario.map((point: any) => `M${point.month}`);
  const revenueChart = [
    { type: "scatter", mode: "lines", name: "Baseline revenue", x: months, y: chartBase.map((point: any) => point.revenue), line: { color: "#8A99AD", width: 1.8, dash: "dot" }, hovertemplate: "$%{y:,.0f}<extra>Baseline</extra>" },
    { type: "scatter", mode: "lines", name: "Scenario revenue", x: months, y: chartScenario.map((point: any) => point.revenue), line: { color: "#2F6BFF", width: 2.6, shape: "spline" }, fill: "tonexty", fillcolor: "rgba(47,107,255,0.07)", hovertemplate: "$%{y:,.0f}<extra>Scenario</extra>" },
  ];
  const profitChart = [
    { type: "bar", name: "Baseline net profit", x: months, y: chartBase.map((point: any) => point.net_profit), marker: { color: "rgba(138,153,173,0.45)" }, hovertemplate: "$%{y:,.0f}<extra>Baseline</extra>" },
    { type: "bar", name: "Scenario net profit", x: months, y: chartScenario.map((point: any) => point.net_profit), marker: { color: "rgba(20,184,166,0.82)" }, hovertemplate: "$%{y:,.0f}<extra>Scenario</extra>" },
  ];
  const mcChart = monteCarlo?.histogram ? [
    {
      type: "bar",
      x: monteCarlo.histogram.map((bucket: any) => (bucket.bucket_start + bucket.bucket_end) / 2),
      y: monteCarlo.histogram.map((bucket: any) => bucket.count),
      marker: { color: "rgba(139,92,246,0.75)" },
      hovertemplate: "~$%{x:,.0f}<br>%{y} simulations<extra></extra>",
    },
  ] : [];
  const tornado = sensitivity?.dimensions ? [
    {
      type: "bar",
      orientation: "h",
      name: "Low",
      y: sensitivity.dimensions.map((item: any) => item.label),
      x: sensitivity.dimensions.map((item: any) => item.delta_low),
      marker: { color: "rgba(239,68,68,0.72)" },
      hovertemplate: "$%{x:,.0f}<extra>Low</extra>",
    },
    {
      type: "bar",
      orientation: "h",
      name: "High",
      y: sensitivity.dimensions.map((item: any) => item.label),
      x: sensitivity.dimensions.map((item: any) => item.delta_high),
      marker: { color: "rgba(20,184,166,0.72)" },
      hovertemplate: "$%{x:,.0f}<extra>High</extra>",
    },
  ] : [];

  return (
    <div className="page page-wide">
      <PageHeader
        eyebrow="Predictive Twin · Isolated environment"
        title="Business Simulation"
        description="Test alternative decisions against a snapshot of the validated business. Simulations never modify production observations or metrics."
        meta={
          <div className="header-meta-row">
            <Badge tone="violet" dot><FlaskConical size={12} /> SIMULATION ONLY</Badge>
            <Badge tone="success" dot>Production state isolated</Badge>
            <span className="meta-divider" />
            <span className="meta-text">{history.data?.length || 0} saved scenarios</span>
          </div>
        }
        actions={<Button icon={<History size={15} />} onClick={history.refresh}>Refresh history</Button>}
      />

      <div className="simulation-layout">
        <Card className="scenario-builder">
          <div className="scenario-builder-head">
            <div>
              <span className="eyebrow">Scenario builder</span>
              <h2>Configure the intervention</h2>
            </div>
            <span className="sim-icon"><SlidersHorizontal size={18} /></span>
          </div>
          <p className="scenario-intro">Start from a preset or set each driver. Every driver maps to an explicit, inspectable assumption.</p>

          <div className="preset-row">
            {presets.map((preset) => (
              <button key={preset.name} className="preset-chip" onClick={() => applyPreset(preset)}>
                <Sparkles size={13} />
                <span>{preset.name}</span>
              </button>
            ))}
          </div>

          <label className="field compact">
            <span>Scenario name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} />
          </label>

          <div className="scenario-params">
            {primaryParams.map((param) => (
              <div key={param.key} className="param-row">
                <div className="param-head">
                  <div>
                    <span>{param.label}</span>
                    <small>{param.description}</small>
                  </div>
                  <div className="param-input">
                    <input
                      type="number"
                      value={parameters[param.key]}
                      min={param.min}
                      max={param.max}
                      step={param.step}
                      onChange={(event) => setParameters((current) => ({ ...current, [param.key]: Number(event.target.value) }))}
                    />
                    <span>{param.unit === "USD" ? "$" : param.unit}</span>
                  </div>
                </div>
                <input
                  type="range"
                  min={param.min}
                  max={param.max}
                  step={param.step}
                  value={parameters[param.key]}
                  onChange={(event) => setParameters((current) => ({ ...current, [param.key]: Number(event.target.value) }))}
                  className="range-input"
                />
              </div>
            ))}
          </div>

          <button className="advanced-toggle" onClick={() => setAdvanced((value) => !value)}>
            <span>{advanced ? "Hide" : "Show"} advanced drivers</span>
            <span>{advanced ? "−" : "+"}</span>
          </button>
          {advanced && (
            <div className="scenario-params advanced-params">
              {advancedParams.map((param) => (
                <div key={param.key} className="param-row compact">
                  <div className="param-head">
                    <span>{param.label}</span>
                    <div className="param-input">
                      <input
                        type="number"
                        value={parameters[param.key]}
                        min={param.min}
                        max={param.max}
                        step={param.step}
                        onChange={(event) => setParameters((current) => ({ ...current, [param.key]: Number(event.target.value) }))}
                      />
                      <span>{param.unit === "USD" ? "$" : param.unit}</span>
                    </div>
                  </div>
                  <input
                    type="range"
                    min={param.min}
                    max={param.max}
                    step={param.step}
                    value={parameters[param.key]}
                    onChange={(event) => setParameters((current) => ({ ...current, [param.key]: Number(event.target.value) }))}
                    className="range-input"
                  />
                </div>
              ))}
            </div>
          )}

          <div className="scenario-builder-foot">
            <div className="scenario-cost">
              <span>One-off investment</span>
              <strong>{money(parameters.one_off_cost)}</strong>
            </div>
            <Button
              variant="primary"
              size="lg"
              icon={<Play size={15} />}
              loading={running}
              onClick={runSimulation}
              disabled={!canRun(user)}
              className="sim-run"
            >
              {running ? "Modelling outcomes…" : "Run simulation"}
            </Button>
            <div className="scenario-notice"><ShieldCheck size={13} /> Deterministic model · no LLM arithmetic</div>
          </div>
        </Card>

        <section className="simulation-results">
          {running && (
            <Card className="simulation-running">
              <div className="running-orbit"><FlaskConical size={26} /></div>
              <h3>Computing base, best and worst cases</h3>
              <p>Running 2,000 Monte Carlo draws, sensitivity analysis and the baseline backtest.</p>
              <LoadingBlock lines={3} />
            </Card>
          )}

          {!running && !result && (
            <Card className="detail-placeholder">
              <EmptyState
                title="No scenario selected"
                description="Configure an intervention and run the simulation, or open a saved scenario from the history."
                icon={<FlaskConical size={26} />}
                action={<Button variant="primary" icon={<Play size={15} />} onClick={runSimulation} loading={running}>Run first simulation</Button>}
              />
            </Card>
          )}

          {!running && result && summary && (
            <div className="stack-lg">
              <Card className="sim-result-head">
                <div>
                  <div className="eyebrow">Scenario result · SIMULATED</div>
                  <h2>{result.name}</h2>
                  <div className="sim-param-strip">
                    {[...primaryParams, ...advancedParams]
                      .filter((param) => Number(parameters[param.key] || 0) !== 0)
                      .map((param) => (
                        <span key={param.key} className="sim-param-chip">
                          {param.label}
                          <strong>{parameters[param.key] > 0 ? "+" : ""}{number(parameters[param.key], 1)}{param.unit === "USD" ? " USD" : param.unit}</strong>
                        </span>
                      ))}
                    {Object.values(parameters).every((value) => Number(value) === 0) && <span className="sim-param-chip">Unchanged baseline</span>}
                  </div>
                </div>
                <div className="sim-result-badges">
                  <Badge tone="violet" dot>Not a forecast guarantee</Badge>
                  <Badge tone="info">Confidence {pct(result.results.confidence_pct, 0)}</Badge>
                  <StatusBadge status={result.status} />
                </div>
              </Card>

              <div className="sim-kpi-grid">
                <Card className="sim-kpi">
                  <span>12-month net profit delta</span>
                  <strong className={summary.net_profit_delta >= 0 ? "positive" : "negative"}>{summary.net_profit_delta >= 0 ? "+" : "−"}{money(Math.abs(summary.net_profit_delta), true)}</strong>
                  <small>vs baseline {money(summary.baseline_net_profit_12m, true)}</small>
                </Card>
                <Card className="sim-kpi">
                  <span>Exit gross margin</span>
                  <strong>{pct(summary.exit_gross_margin_pct)}</strong>
                  <small>{summary.exit_gross_margin_pct >= summary.baseline_exit_gross_margin_pct ? "+" : "−"}{number(Math.abs(summary.exit_gross_margin_pct - summary.baseline_exit_gross_margin_pct), 2)}pp vs baseline</small>
                </Card>
                <Card className="sim-kpi">
                  <span>Exit cash</span>
                  <strong>{money(summary.exit_cash_balance, true)}</strong>
                  <small>minimum {money(summary.minimum_cash, true)}</small>
                </Card>
                <Card className="sim-kpi">
                  <span>ROI on investment</span>
                  <strong>{summary.roi_pct === null ? "—" : pct(summary.roi_pct, 0)}</strong>
                  <small>{summary.break_even_month ? `break-even month ${summary.break_even_month}` : "no payback in horizon"}</small>
                </Card>
              </div>

              <div className="sim-range-grid">
                {[
                  { label: "Worst case", value: result.results.worst_case.summary, tone: "danger" },
                  { label: "Base case", value: summary, tone: "primary" },
                  { label: "Best case", value: result.results.best_case.summary, tone: "success" },
                ].map((item) => (
                  <Card key={item.label} className={`range-card range-${item.tone}`}>
                    <span>{item.label}</span>
                    <strong>{item.value.net_profit_delta >= 0 ? "+" : "−"}{money(Math.abs(item.value.net_profit_delta), true)}</strong>
                    <small>margin {pct(item.value.exit_gross_margin_pct)} · cash {money(item.value.exit_cash_balance, true)}</small>
                  </Card>
                ))}
              </div>

              <div className="tab-row-with-meta">
                <Tabs
                  tabs={[
                    { key: "projection", label: "Projections" },
                    { key: "uncertainty", label: "Uncertainty" },
                    { key: "sensitivity", label: "Sensitivity" },
                    { key: "assumptions", label: "Assumptions" },
                    { key: "history", label: "History", count: history.data?.length },
                  ]}
                  active={tab}
                  onChange={setTab}
                />
                <span className="meta-text"><Clock3 size={12} /> {relativeTime(result.created_at)}</span>
              </div>

              {tab === "projection" && (
                <div className="stack-lg">
                  <div className="grid-2">
                    <Panel title="Revenue trajectory" subtitle="Baseline vs scenario · 12 months">
                      <Chart data={revenueChart} height={286} layout={{ barmode: "group", margin: { l: 56, r: 20, t: 24, b: 36 }, yaxis: { tickprefix: "$", tickformat: "~s" } }} />
                    </Panel>
                    <Panel title="Net profit trajectory" subtitle="Monthly simulated contribution">
                      <Chart data={profitChart} height={286} layout={{ barmode: "group", margin: { l: 56, r: 20, t: 24, b: 36 }, yaxis: { tickprefix: "$", tickformat: "~s" } }} />
                    </Panel>
                  </div>
                  <Panel title="Constraint checks" subtitle="Configured business policy for this scenario">
                    <div className="constraint-list">
                      {(summary.constraints || []).map((constraint: any) => (
                        <div key={constraint.rule} className={`constraint-row ${constraint.status === "BREACHED" ? "constraint-breach" : "constraint-pass"}`}>
                          {constraint.status === "BREACHED" ? <TriangleAlert size={16} /> : <Check size={16} />}
                          <div><strong>{titleCase(constraint.rule)}</strong><span>{constraint.message}</span></div>
                          <Badge tone={constraint.status === "BREACHED" ? "danger" : "success"}>{constraint.status}</Badge>
                        </div>
                      ))}
                    </div>
                  </Panel>
                  <Panel title="Alternative outcomes" subtitle="Best, base and worst case modelled with explicit assumption ranges" flush>
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead><tr><th>Case</th><th>Net profit 12m</th><th>Delta vs baseline</th><th>Exit margin</th><th>Exit cash</th></tr></thead>
                        <tbody>
                          {result.results.alternatives?.map((alternative: any) => (
                            <tr key={alternative.key}>
                              <td><strong>{alternative.name}</strong></td>
                              <td>{money(alternative.net_profit_12m)}</td>
                              <td className={alternative.net_profit_delta >= 0 ? "positive" : "negative"}>{money(alternative.net_profit_delta)}</td>
                              <td>{pct(alternative.exit_gross_margin_pct)}</td>
                              <td>{money(alternative.exit_cash_balance)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Panel>
                </div>
              )}

              {tab === "uncertainty" && (
                <div className="stack-lg">
                  <div className="grid-2">
                    <Panel title="Monte Carlo distribution" subtitle={`${monteCarlo?.iterations?.toLocaleString() || 0} draws · 12-month net profit`}>
                      {mcChart.length ? <Chart data={mcChart} height={320} layout={{ margin: { l: 52, r: 20, t: 24, b: 42 }, xaxis: { tickprefix: "$", tickformat: "~s" }, yaxis: { title: undefined } }} /> : <EmptyState title="No Monte Carlo draws" />}
                    </Panel>
                    <Panel title="Probability & range" subtitle="Modelled uncertainty, not a guarantee">
                      <div className="mc-stats">
                        <div><span>P10</span><strong>{money(monteCarlo?.p10, true)}</strong></div>
                        <div><span>P50</span><strong>{money(monteCarlo?.p50, true)}</strong></div>
                        <div><span>P90</span><strong>{money(monteCarlo?.p90, true)}</strong></div>
                        <div><span>Mean</span><strong>{money(monteCarlo?.mean_net_profit_12m, true)}</strong></div>
                        <div><span>Above baseline</span><strong>{pct(monteCarlo?.probability_above_baseline, 0)}</strong></div>
                        <div><span>Positive outcome</span><strong>{pct(monteCarlo?.probability_positive, 0)}</strong></div>
                      </div>
                      <div className="notice-strip compact"><Info size={14} /><span>{monteCarlo?.disclaimer}</span></div>
                      <div className="definition-block">
                        <DefinitionList items={[
                          { label: "Seed", value: <span className="mono">{monteCarlo?.seed}</span> },
                          { label: "Std deviation", value: money(monteCarlo?.std_dev, true) },
                          { label: "Exit margin range", value: `${pct(monteCarlo?.exit_margin_p10)} – ${pct(monteCarlo?.exit_margin_p90)}` },
                        ]} />
                      </div>
                    </Panel>
                  </div>
                  <Panel title="Baseline backtest" subtitle="Validates the baseline growth assumption only — not a counterfactual test">
                    {result.backtest?.status === "OK" ? (
                      <div className="backtest-grid">
                        <div><span>Method</span><strong>{titleCase(result.backtest.method)}</strong></div>
                        <div><span>MAPE</span><strong>{pct(result.backtest.mape_pct)}</strong></div>
                        <div><span>Samples</span><strong>{result.backtest.samples}</strong></div>
                        <p>{result.backtest.note}</p>
                      </div>
                    ) : <EmptyState title="Insufficient history for backtest" />}
                  </Panel>
                </div>
              )}

              {tab === "sensitivity" && (
                <Panel title="Sensitivity analysis" subtitle="Change in 12-month net profit versus the base case">
                  {tornado.length ? <Chart data={tornado} height={360} layout={{ barmode: "relative", margin: { l: 190, r: 30, t: 24, b: 42 }, xaxis: { tickprefix: "$", tickformat: "~s" } }} /> : <EmptyState title="No sensitivity analysis" />}
                  <div className="sensitivity-note"><AlertTriangle size={14} /> Ranking shows which assumptions dominate the outcome. It does not assign probability to any assumption.</div>
                </Panel>
              )}

              {tab === "assumptions" && (
                <div className="stack-lg">
                  <Panel title="Model assumptions" subtitle="Every relationship is explicit and configurable">
                    <div className="assumption-grid">
                      {Object.entries(result.results.assumptions_used || {}).filter(([key]) => key !== "note").map(([key, value]) => (
                        <div key={key} className="assumption-item">
                          <span>{titleCase(key)}</span>
                          <strong>{typeof value === "number" ? number(value, 4) : String(value)}</strong>
                        </div>
                      ))}
                    </div>
                    <div className="notice-strip compact"><Info size={14} /><span>{result.results.assumptions_used?.note}</span></div>
                  </Panel>
                  <Panel title="Limitations" subtitle="Read before using a projection in a management decision">
                    <ul className="limitation-list">
                      {(result.assumptions?.limitations || []).map((item: string) => <li key={item}>{item}</li>)}
                    </ul>
                  </Panel>
                  <details className="raw-details"><summary>Raw assumptions & parameters</summary><JsonBlock value={result.assumptions} /></details>
                </div>
              )}

              {tab === "history" && (
                <Panel title="Saved simulations" subtitle="Every run is versioned and isolated" flush>
                  <div className="history-list">
                    {(history.data || []).map((simulation) => (
                      <button key={simulation.id} className="history-row" onClick={() => selectSimulation(simulation)}>
                        <FlaskConical size={16} />
                        <div><strong>{simulation.name}</strong><span>{relativeTime(simulation.created_at)} · {money(simulation.results?.scenario?.summary?.net_profit_delta, true)} projected delta</span></div>
                        <Badge tone="muted">{simulation.results?.confidence_pct || 0}% confidence</Badge>
                      </button>
                    ))}
                    {(history.data || []).length === 0 && <EmptyState title="No saved simulations" />}
                  </div>
                </Panel>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
