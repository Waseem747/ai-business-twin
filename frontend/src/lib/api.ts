import type {
  Agent,
  Alert,
  Approval,
  BusinessRule,
  Decision,
  ExcelConversion,
  Overview,
  Report,
  Simulation,
  Source,
  User,
  WorkflowRun,
} from "./types";

const TOKEN_KEY = "twin.token";
const USER_KEY = "twin.user";

export class ApiError extends Error {
  status: number;
  code?: string;
  details?: any;
  constructor(message: string, status: number, code?: string, details?: any) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string, user: User) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function cachedUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError("The API is unreachable. Check that the backend is running.", 0);
  }
  if (response.status === 401) {
    clearSession();
    window.dispatchEvent(new CustomEvent("twin:unauthorized"));
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    let code: string | undefined;
    let details: any;
    try {
      const body = await response.json();
      if (body?.detail && typeof body.detail === "string") message = body.detail;
      else if (body?.error?.message) {
        message = body.error.message;
        code = body.error.code;
        details = body.error.details;
      } else if (Array.isArray(body?.detail)) {
        message = body.detail.map((item: any) => item.msg).join(", ");
      } else if (body?.detail) {
        message = typeof body.detail === "object" ? JSON.stringify(body.detail) : String(body.detail);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(message, response.status, code, details);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function qs(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  async login(email: string, password: string): Promise<{ access_token: string; user: User }> {
    return request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
  },
  me: () => request<User>("/auth/me"),
  overview: () => request<Overview>("/overview"),
  system: () => request<Record<string, any>>("/system"),

  agents: () => request<Agent[]>("/agents"),
  agentExecutions: (agentKey?: string, limit = 60) =>
    request<any[]>(`/agents/executions${qs({ agent_key: agentKey, limit })}`),
  workflows: (workflow?: string, limit = 50) =>
    request<WorkflowRun[]>(`/workflows${qs({ workflow, limit })}`),
  workflow: (id: string) => request<WorkflowRun>(`/workflows/${id}`),
  runWorkflow: (workflow: string, body: Record<string, any>) =>
    request<WorkflowRun>(`/workflows/${workflow}/run`, { method: "POST", body: JSON.stringify(body) }),

  decisions: (status?: string) => request<Decision[]>(`/decisions${qs({ status })}`),
  decision: (id: string) => request<Decision>(`/decisions/${id}`),
  actions: () => request<any[]>("/actions"),
  approvals: () => request<{ pending: Approval[]; history: Approval[] }>("/approvals"),
  decideApproval: (id: string, approved: boolean, comment: string) =>
    request<any>(`/approvals/${id}/decide`, { method: "POST", body: JSON.stringify({ approved, comment }) }),

  alerts: (status?: string) => request<{ alerts: Alert[]; summary: Record<string, number> }>(`/alerts${qs({ status })}`),
  alert: (id: string) => request<Alert>(`/alerts/${id}`),
  acknowledgeAlert: (id: string, note = "") =>
    request<Alert>(`/alerts/${id}/acknowledge`, { method: "POST", body: JSON.stringify({ note }) }),
  resolveAlert: (id: string, note = "") =>
    request<Alert>(`/alerts/${id}/resolve`, { method: "POST", body: JSON.stringify({ note }) }),
  escalateAlert: (id: string, note = "") =>
    request<Alert>(`/alerts/${id}/escalate`, { method: "POST", body: JSON.stringify({ note }) }),
  investigateAlert: (id: string) =>
    request<any>(`/alerts/${id}/investigate`, { method: "POST" }),
  notifications: () => request<any[]>("/notifications"),
  events: (limit = 50) => request<any[]>(`/events${qs({ limit })}`),
  auditLogs: () => request<any[]>("/audit-logs"),

  simulations: () => request<Simulation[]>("/simulations"),
  simulation: (id: string) => request<Simulation>(`/simulations/${id}`),
  simulationAssumptions: () => request<any>("/simulations/assumptions"),
  runSimulation: (body: Record<string, any>) =>
    request<{ simulation: Simulation; workflow: any }>("/simulations", { method: "POST", body: JSON.stringify(body) }),

  rules: () => request<BusinessRule[]>("/logic/rules"),
  rule: (id: string) => request<BusinessRule>(`/logic/rules/${id}`),
  testRule: (id: string, body: Record<string, any>) =>
    request<any>(`/logic/rules/${id}/test`, { method: "POST", body: JSON.stringify(body) }),
  runRule: (id: string, inputs: Record<string, any>, testMode = false) =>
    request<any>(`/logic/rules/${id}/run`, { method: "POST", body: JSON.stringify({ inputs, test_mode: testMode }) }),
  activateRule: (id: string, versionId: string) =>
    request<any>(`/logic/rules/${id}/activate`, { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
  createRule: (body: Record<string, any>) =>
    request<any>("/logic/rules", { method: "POST", body: JSON.stringify(body) }),
  createDraft: (id: string, body: Record<string, any>) =>
    request<any>(`/logic/rules/${id}/draft`, { method: "POST", body: JSON.stringify(body) }),

  conversions: () => request<ExcelConversion[]>("/logic/excel/conversions"),
  conversion: (id: string) => request<ExcelConversion>(`/logic/excel/conversions/${id}`),
  uploadConversion: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<any>("/logic/excel/conversions", { method: "POST", body: form });
  },
  approveConversion: (id: string, approved: boolean, comment = "") =>
    request<any>(`/logic/excel/conversions/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved, comment }),
    }),

  reports: (type?: string) => request<Report[]>(`/reports${qs({ report_type: type })}`),
  report: (id: string) => request<Report>(`/reports/${id}`),
  download: async (path: string, filename: string) => {
    const token = getToken();
    const response = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) throw new ApiError("Download failed", response.status);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
  downloadReport: (reportId: string, format: string) =>
    api.download(`/api/reports/${reportId}/download?format=${format}`, `report_${reportId}.${format}`),
  downloadConversionReport: (conversionId: string, filename: string) =>
    api.download(`/api/logic/excel/conversions/${conversionId}/report`, filename),

  integrations: () =>
    request<{
      sources: Source[];
      summary: Record<string, number>;
      recent_ingestions: any[];
      transformations: any[];
      transformation_runs: any[];
      notice: string;
    }>("/integrations"),
  connectorTypes: () => request<{ connectors: any[]; auth: any }>("/integrations/connector-types"),
  testConnector: (kind: string, config: Record<string, any>) =>
    request<any>("/integrations/connectors/test", { method: "POST", body: JSON.stringify({ kind, config }) }),
  createSource: (body: Record<string, any>) =>
    request<any>("/integrations/sources", { method: "POST", body: JSON.stringify(body) }),
  syncSource: (id: string) =>
    request<any>(`/integrations/${id}/sync`, { method: "POST", body: JSON.stringify({}) }),
  uploadTabular: (file: File, entity: string, metric: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("entity", entity);
    form.append("metric", metric);
    return request<any>("/integrations/upload", { method: "POST", body: form });
  },
};
