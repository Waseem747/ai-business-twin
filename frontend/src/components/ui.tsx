import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Check, Copy, Inbox, Loader2, X } from "lucide-react";
import { useState } from "react";
import { money, number, pct, statusTone, titleCase } from "../lib/format";

export function Badge({
  children,
  tone = "muted",
  dot = false,
  className = "",
}: {
  children: ReactNode;
  tone?: string;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={`badge badge-${tone} ${className}`}>
      {dot && <span className={`badge-dot dot-${tone}`} />}
      {children}
    </span>
  );
}

export function StatusBadge({ status, size }: { status?: string; size?: "sm" | "md" }) {
  return (
    <Badge tone={statusTone(status)} dot className={size === "sm" ? "badge-sm" : ""}>
      {titleCase(status)}
    </Badge>
  );
}

export function Button({
  children,
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "success" | "dark";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={`button button-${variant} button-${size} ${className}`}
    >
      {loading ? <Loader2 size={15} className="spin" /> : icon}
      <span>{children}</span>
    </button>
  );
}

export function IconButton({
  children,
  label,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button {...props} aria-label={label} title={label} className={`icon-button ${className}`}>
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article";
}) {
  const Tag = as;
  return <Tag className={`card ${className}`}>{children}</Tag>;
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
  flush = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-header">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {subtitle && <p className="panel-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className={flush ? "panel-body-flush" : "panel-body"}>{children}</div>
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  meta,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="page-header-copy">
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
        {meta && <div className="page-header-meta">{meta}</div>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Delta({ value, suffix = "%", goodUp = true, digits = 1 }: { value?: number | null; suffix?: string; goodUp?: boolean; digits?: number }) {
  if (value === null || value === undefined) return <span className="delta muted">—</span>;
  const up = value >= 0;
  const good = goodUp ? up : !up;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`delta ${good ? "delta-good" : "delta-bad"}`}>
      <Icon size={13} />
      {suffix === "%" ? pct(value, digits, true) : `${Math.abs(value).toFixed(digits)}${suffix}`}
    </span>
  );
}

export function Sparkline({
  values,
  width = 108,
  height = 34,
  color = "var(--primary)",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  const clean = values.filter((value) => Number.isFinite(value));
  if (clean.length < 2) return <div className="sparkline-empty" />;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const span = max - min || 1;
  const points = clean
    .map((value, index) => {
      const x = (index / (clean.length - 1)) * width;
      const y = height - 4 - ((value - min) / span) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = clean[clean.length - 1];
  const lastX = width;
  const lastY = height - 4 - ((last - min) / span) * (height - 8);
  return (
    <svg width={width} height={height} className="sparkline" aria-hidden="true">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lastX} cy={lastY} r="2.4" fill={color} />
    </svg>
  );
}

export function StatCard({
  label,
  value,
  unit,
  change,
  changeSuffix,
  hint,
  spark,
  icon,
  accent = "blue",
  footer,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  change?: number | null;
  changeSuffix?: string;
  hint?: ReactNode;
  spark?: number[];
  icon?: ReactNode;
  accent?: "blue" | "teal" | "amber" | "red" | "violet";
  footer?: ReactNode;
}) {
  return (
    <Card className="stat-card">
      <div className="stat-card-top">
        <span className="stat-label">{label}</span>
        {icon && <span className={`stat-icon accent-${accent}`}>{icon}</span>}
      </div>
      <div className="stat-value-row">
        <span className="stat-value">{value}</span>
        {unit && <span className="stat-unit">{unit}</span>}
      </div>
      <div className="stat-card-bottom">
        <div className="stat-change">
          {change !== undefined && <Delta value={change} suffix={changeSuffix || "%"} />}
          {hint && <span className="stat-hint">{hint}</span>}
        </div>
        {spark && <Sparkline values={spark} />}
      </div>
      {footer && <div className="stat-footer">{footer}</div>}
    </Card>
  );
}

export function ScoreRing({ score, grade, size = 116 }: { score: number; grade: string; size?: number }) {
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  const tone = score >= 72 ? "var(--success)" : score >= 55 ? "var(--warning)" : "var(--danger)";
  return (
    <div className="score-ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth="8" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={tone}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="score-ring-label">
        <strong>{number(score, 0)}</strong>
        <span>Grade {grade}</span>
      </div>
    </div>
  );
}

export function ProgressBar({ value, tone = "blue" }: { value: number; tone?: string }) {
  return (
    <div className="progress-track">
      <div className={`progress-fill progress-${tone}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon || <Inbox size={22} />}</div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}

export function LoadingBlock({ lines = 4, height }: { lines?: number; height?: number }) {
  return (
    <div className="loading-block" style={height ? { height } : undefined}>
      {Array.from({ length: lines }).map((_, index) => (
        <div key={index} className="skeleton" style={{ width: `${92 - index * 9}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-state">
      <AlertTriangle size={20} />
      <div>
        <strong>Unable to load this view</strong>
        <p>{message}</p>
      </div>
      {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Spinner({ size = 18 }: { size?: number }) {
  return <Loader2 size={size} className="spin" />;
}

export function Tabs({
  tabs,
  active,
  onChange,
  className = "",
}: {
  tabs: { key: string; label: string; count?: number }[];
  active: string;
  onChange: (key: string) => void;
  className?: string;
}) {
  return (
    <div className={`tabs ${className}`} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={active === tab.key}
          className={`tab ${active === tab.key ? "tab-active" : ""}`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
          {tab.count !== undefined && <span className="tab-count">{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  title,
  subtitle,
  onClose,
  children,
  footer,
  width = "560px",
}: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  if (!open) return null;
  return (
    <div className="modal-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: width }} role="dialog" aria-modal="true">
        <header className="modal-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <IconButton label="Close" onClick={onClose}><X size={17} /></IconButton>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-footer">{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({
  open,
  title,
  subtitle,
  onClose,
  children,
  width = "680px",
}: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  if (!open) return null;
  return (
    <div className="drawer-overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="drawer" style={{ maxWidth: width }} aria-modal="true" role="dialog">
        <header className="drawer-header">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <IconButton label="Close" onClick={onClose}><X size={17} /></IconButton>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy-button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? "Copied" : label}
    </button>
  );
}

export function JsonBlock({ value, maxHeight = 360 }: { value: any; maxHeight?: number }) {
  return (
    <div className="json-block-wrap">
      <CopyButton value={typeof value === "string" ? value : JSON.stringify(value, null, 2)} />
      <pre className="json-block" style={{ maxHeight }}>
        {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export function DefinitionList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="definition-list">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function MetricChip({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <div className="metric-chip">
      <span>{label}</span>
      <strong>{value}</strong>
      {tone && <span className={`metric-chip-dot dot-${tone}`} />}
    </div>
  );
}

export function DemoNotice({ children }: { children?: ReactNode }) {
  return (
    <div className="notice-strip">
      <Activity size={15} />
      <span>{children || "This environment uses clearly labelled simulated data sources. No external system is represented as live."}</span>
    </div>
  );
}

export function formatValue(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined) return "—";
  if (unit === "USD") return money(value);
  if (unit === "pct") return pct(value);
  if (unit === "count") return number(value, 0);
  if (unit === "months") return `${number(value, 1)} mo`;
  if (unit === "score") return number(value, 0);
  return number(value, 2);
}
