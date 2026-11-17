export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "ADMIN" | "APPROVER" | "ANALYST" | "VIEWER";
  title: string;
  tenant_id: string;
}

export interface Kpi {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  change_pct?: number | null;
  change_pp?: number | null;
  good_direction?: string;
  period?: string;
}

export interface HealthFactor {
  key: string;
  label: string;
  weight: number;
  score: number;
  value: number | null;
}

export interface LatestPeriod {
  period: string;
  label: string;
  revenue: number | null;
  cogs: number | null;
  gross_profit: number | null;
  gross_margin_pct: number | null;
  marketing_spend: number | null;
  payroll: number | null;
  occupancy: number | null;
  other_opex: number | null;
  operating_expenses: number | null;
  net_profit: number | null;
  net_margin_pct: number | null;
  cash_balance: number | null;
  cash_runway_months: number | null;
  inventory_value: number | null;
  inventory_days: number | null;
  receivables: number | null;
  dso_days: number | null;
  units_sold: number | null;
  new_customers: number | null;
  active_customers: number | null;
  churned_customers: number | null;
  churn_rate_pct: number | null;
  supplier_cost_index: number | null;
  complete: boolean;
}

export interface Finding {
  id: string;
  kind: string;
  severity: string;
  title: string;
  detail: string;
  area: string;
  evidence: Record<string, any>;
  confidence: number;
}

export interface Snapshot {
  id: string;
  as_of: string;
  health_score: number;
  latest: LatestPeriod;
  prior: LatestPeriod;
  kpis: Kpi[];
  health: { score: number; grade: string; factors: HealthFactor[] };
  trends: Record<string, any>;
  daily_revenue: { date: string; value: number }[];
  channels: { channel: string; revenue: number; share_pct: number }[];
  summary: string;
  data_quality: Record<string, any>;
  drivers: Record<string, any>;
  intelligence?: { findings: Finding[]; counts: Record<string, number>; narrative?: any };
  custom_logic?: any;
  lineage?: any;
  periods?: LatestPeriod[];
}

export interface Alert {
  id: string;
  severity: "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  title: string;
  detail: string;
  area: string;
  evidence: Record<string, any>;
  occurrences: number;
  escalation_level: number;
  first_seen: string;
  last_seen: string;
  acknowledged_by?: string;
  resolved_by?: string;
  resolution_note?: string;
  events?: any[];
}

export interface DecisionAlternative {
  key: string;
  title: string;
  type: string;
  risk_level: string;
  reversibility: string;
  implementation_cost: number;
  time_horizon_months: number;
  expected_impact_12m: number;
  exit_gross_margin_pct: number;
  exit_cash_balance: number;
  roi_pct: number | null;
  confidence: number;
  score: number;
  selected: boolean;
  parameters: Record<string, number>;
  assumptions: string[];
  constraints: any[];
}

export interface DecisionReview {
  id: string;
  round: number;
  verdict: string;
  reasons: { code: string; severity: string; message: string; evidence?: any }[];
  conditions: string[];
  findings: { checks: any[]; narrative?: any; independence?: string };
  reviewer: string;
  model_provider: string;
  created_at: string;
}

export interface Approval {
  id: string;
  status: string;
  decided_by?: string;
  decided_at?: string;
  comment?: string;
  requested_at?: string;
  expires_at?: string;
  policy?: any;
  decision_id: string;
  decision_title?: string;
  decision_status?: string;
  expected_financial_impact?: number;
  risk_level?: string;
  workflow_run_id?: string;
}

export interface Decision {
  id: string;
  title: string;
  issue: string;
  objective: string;
  status: string;
  risk_level: string;
  confidence: number;
  reversibility: string;
  expected_financial_impact: number;
  requires_approval: boolean;
  rationale: string;
  evidence: any[];
  alternatives: DecisionAlternative[];
  chosen: any;
  audit_rounds: number;
  simulation_id?: string;
  workflow_run_id?: string;
  alert_id?: string;
  created_at: string;
  updated_at: string;
  simulated: boolean;
  approval?: Approval;
  approvals?: Approval[];
  reviews?: DecisionReview[];
  simulation?: Simulation;
  action?: any;
}

export interface Agent {
  id: string;
  key: string;
  name: string;
  role: string;
  description: string;
  status: string;
  permissions: string[];
  tools: string[];
  last_run_at?: string;
  last_error?: string;
  metrics: Record<string, any>;
}

export interface WorkflowStep {
  id: string;
  node: string;
  status: string;
  summary: string;
  payload: any;
  started_at?: string;
  finished_at?: string;
}

export interface WorkflowRun {
  id: string;
  workflow: string;
  status: string;
  trigger: string;
  summary: string;
  error?: string;
  started_at: string;
  finished_at?: string;
  initiated_by: string;
  state?: Record<string, any>;
  steps?: WorkflowStep[];
}

export interface SimulationSummary {
  revenue_12m: number;
  baseline_revenue_12m: number;
  revenue_delta: number;
  revenue_delta_pct: number;
  gross_profit_12m: number;
  baseline_gross_profit_12m: number;
  gross_profit_delta: number;
  net_profit_12m: number;
  baseline_net_profit_12m: number;
  net_profit_delta: number;
  exit_gross_margin_pct: number;
  baseline_exit_gross_margin_pct: number;
  exit_cash_balance: number;
  baseline_exit_cash_balance: number;
  minimum_cash: number;
  investment_required: number;
  roi_pct: number | null;
  break_even_month: number | null;
  net_margin_pct: number;
  constraints: any[];
  cash_runway_months: number;
}

export interface Simulation {
  id: string;
  name: string;
  status: string;
  scenario_id?: string;
  snapshot_id?: string;
  baseline: Record<string, any>;
  results: {
    scenario: {
      summary: SimulationSummary;
      monthly: any[];
      baseline_monthly: any[];
      constraints: any[];
    };
    best_case: { summary: SimulationSummary };
    worst_case: { summary: SimulationSummary };
    alternatives: any[];
    assumptions_used: Record<string, any>;
    confidence_pct: number;
    is_simulation: boolean;
    production_state_modified: boolean;
  };
  assumptions: Record<string, any>;
  alternatives: any[];
  monte_carlo: any;
  sensitivity: any;
  backtest: any;
  simulated: boolean;
  created_by: string;
  created_at: string;
  finished_at?: string;
}

export interface Report {
  id: string;
  report_type: string;
  title: string;
  status: string;
  period_start?: string;
  period_end?: string;
  files: Record<string, string>;
  generated_by: string;
  created_at: string;
  content?: any;
}

export interface BusinessRule {
  id: string;
  key: string;
  name: string;
  description: string;
  category: string;
  source: string;
  version: number;
  status: string;
  dependencies: string[];
  execution_frequency: string;
  input_schema: Record<string, string>;
  output_schema: Record<string, string>;
  tests: any[];
  approved_by?: string;
  approved_at?: string;
  excel_lineage?: any;
  created_at: string;
  updated_at: string;
  code?: string;
  versions?: any[];
  executions?: any[];
}

export interface Source {
  id: string;
  name: string;
  kind: string;
  system: string;
  status: string;
  simulated: boolean;
  last_sync_at?: string;
  freshness_at?: string;
  last_error?: string;
  records_total: number;
  health?: {
    stale: boolean;
    age_hours: number | null;
    freshness_at?: string;
    last_sync_at?: string;
    records_total?: number;
  };
  config: Record<string, any>;
}

export interface ExcelConversion {
  id: string;
  filename: string;
  status: string;
  workflow_run_id?: string;
  formula_count: number;
  workbook_meta: {
    sheets: any[];
    named_ranges: any[];
    dependency_summary: any;
    inputs: any[];
    outputs: any[];
    warnings: string[];
  };
  unsupported: any[];
  dependency_graph: any;
  validation_summary: {
    status?: string;
    passed?: boolean;
    message?: string;
    datasets?: any[];
    engine?: string;
    tolerance?: any;
    duration_ms?: number;
    mismatches?: any[];
    comparisons?: any[];
  };
  report_path?: string;
  rule_id?: string;
  approved_by?: string;
  approved_at?: string;
  created_at: string;
  error?: string;
  generated_code?: string;
}

export interface Overview {
  business: { id: string; name: string; industry: string; currency: string; is_demo: boolean; description: string };
  user: { name: string; role: string; email: string; title: string };
  system: Record<string, any>;
  snapshot: Snapshot;
  alerts: Alert[];
  alert_summary: Record<string, number>;
  decisions: Decision[];
  decision_summary: Record<string, number>;
  approvals: Approval[];
  agents: Agent[];
  workflows: WorkflowRun[];
  sources: Source[];
  events: any[];
  notifications: any[];
}
