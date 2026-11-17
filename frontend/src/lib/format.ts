export function money(value: number | null | undefined, compact = false, currency = "USD"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (compact) {
    const abs = Math.abs(value);
    if (abs >= 1_000_000) return `${value < 0 ? "-" : ""}$${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 1 : 2)}M`;
    if (abs >= 1_000) return `${value < 0 ? "-" : ""}$${(abs / 1_000).toFixed(abs >= 100_000 ? 0 : 1)}K`;
    return `${value < 0 ? "-" : ""}$${abs.toFixed(0)}`;
  }
  return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 0 }).format(value);
}

export function number(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export function pct(value: number | null | undefined, digits = 1, signed = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const formatted = `${Math.abs(value).toFixed(digits)}%`;
  if (signed) return `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatted}`;
  return `${value < 0 ? "−" : ""}${formatted}`;
}

export function pp(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(digits)}pp`;
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export function relativeTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value).getTime();
  const seconds = Math.round((Date.now() - date) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return shortDate(value);
}

export function titleCase(value?: string | null): string {
  if (!value) return "—";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function severityTone(severity?: string): string {
  switch ((severity || "").toUpperCase()) {
    case "CRITICAL":
      return "danger";
    case "HIGH":
      return "warning";
    case "MEDIUM":
      return "amber";
    case "LOW":
      return "info";
    case "INFO":
      return "muted";
    default:
      return "muted";
  }
}

export function statusTone(status?: string): string {
  switch ((status || "").toUpperCase()) {
    case "COMPLETED":
    case "ACTIVATED":
    case "ACTIVE":
    case "VERIFIED":
    case "APPROVED":
    case "SENT":
    case "READY":
      return "success";
    case "RUNNING":
    case "EXECUTING":
    case "WAITING_APPROVAL":
    case "WAITING_HUMAN_REVIEW":
    case "AWAITING_APPROVAL":
    case "PENDING":
    case "TESTING":
    case "TRANSLATED":
    case "AUDITED":
    case "SYNCING":
      return "warning";
    case "FAILED":
    case "REJECTED":
    case "ERROR":
    case "REQUIRES_REVIEW":
    case "DEGRADED":
      return "danger";
    case "OPEN":
    case "ACKNOWLEDGED":
      return "info";
    case "RESOLVED":
      return "success";
    default:
      return "muted";
  }
}

export function verdictTone(verdict?: string): string {
  switch (verdict) {
    case "APPROVED":
      return "success";
    case "APPROVED_WITH_CONDITIONS":
      return "warning";
    case "REJECTED":
      return "danger";
    case "REQUIRES_HUMAN_REVIEW":
      return "amber";
    default:
      return "muted";
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export const CHART_COLORS = ["#2F6BFF", "#14B8A6", "#F59E0B", "#EF4444", "#8B5CF6", "#64748B"];
