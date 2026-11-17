import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  Bell,
  BrainCircuit,
  ChevronRight,
  Command,
  Database,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { titleCase, relativeTime } from "../lib/format";
import { useTheme } from "../lib/theme";
import { useAuth as useAuthContext } from "../lib/auth";
import { useApi, useInterval } from "../lib/useApi";
import { Badge, Button, IconButton, Modal } from "./ui";

const navigation = [
  {
    label: "Command",
    items: [
      { to: "/", label: "Business Overview", icon: LayoutDashboard, description: "Live twin state and KPIs" },
      { to: "/decisions", label: "Decision Center", icon: ShieldCheck, description: "Recommendations, audit and approvals" },
      { to: "/reports", label: "Reports & Alerts", icon: Bell, description: "Management reporting and incidents" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/agents", label: "Agent Control", icon: BrainCircuit, description: "Agent health and workflows" },
      { to: "/simulation", label: "Simulation", icon: FlaskConical, description: "Scenario and Monte Carlo analysis" },
      { to: "/logic", label: "Logic Studio", icon: Settings2, description: "Rules, tests and Excel conversion" },
    ],
  },
  {
    label: "Foundation",
    items: [
      { to: "/integrations", label: "Data Integrations", icon: Database, description: "Sources, lineage and quality" },
    ],
  },
];

const pageNames: Record<string, string> = {
  "/": "Business Overview",
  "/decisions": "Decision Center",
  "/reports": "Reports & Alerts",
  "/agents": "Agent Control Center",
  "/simulation": "Business Simulation",
  "/logic": "Business Logic Studio",
  "/integrations": "Data Integrations",
};

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [alerts, setAlerts] = useState(0);
  const [approvals, setApprovals] = useState(0);
  const [userMenu, setUserMenu] = useState(false);

  useEffect(() => {
    setMobileOpen(false);
    setPaletteOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
      if (event.key === "Escape") {
        setPaletteOpen(false);
        setUserMenu(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  useInterval(() => {
    Promise.all([api.alerts(), api.approvals()])
      .then(([alertData, approvalData]) => {
        setAlerts(alertData.summary?.open ?? 0);
        setApprovals(approvalData.pending.length);
      })
      .catch(() => undefined);
  }, 60000);

  useEffect(() => {
    Promise.all([api.alerts(), api.approvals()])
      .then(([alertData, approvalData]) => {
        setAlerts(alertData.summary?.open ?? 0);
        setApprovals(approvalData.pending.length);
      })
      .catch(() => undefined);
  }, [location.pathname]);

  const commands = useMemo(() => {
    const text = query.trim().toLowerCase();
    return navigation
      .flatMap((section) => section.items)
      .filter((item) => !text || item.label.toLowerCase().includes(text) || item.description.toLowerCase().includes(text));
  }, [query]);

  const initials = (user?.full_name || "User")
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("");

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">
            <span />
            <span />
            <span />
          </div>
          <div className="brand-copy">
            <strong>BUSINESS TWIN</strong>
            <span>Autonomous Intelligence</span>
          </div>
          <IconButton label="Close navigation" className="sidebar-close" onClick={() => setMobileOpen(false)}>
            <X size={18} />
          </IconButton>
        </div>

        <div className="sidebar-environment">
          <span className="live-dot" />
          <span>Production Twin</span>
          <Badge tone="violet" className="badge-sm">DEMO</Badge>
        </div>

        <nav className="sidebar-nav">
          {navigation.map((section) => (
            <div key={section.label} className="nav-section">
              <div className="nav-section-label">{section.label}</div>
              {section.items.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : ""}`}
                  >
                    <Icon size={17} strokeWidth={1.9} />
                    <span>{item.label}</span>
                    {item.to === "/decisions" && approvals > 0 && <span className="nav-count">{approvals}</span>}
                    {item.to === "/reports" && alerts > 0 && <span className="nav-count nav-count-alert">{alerts}</span>}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-status-card">
            <div className="sidebar-status-row">
              <Activity size={15} />
              <span>Agent mesh online</span>
              <span className="live-dot" />
            </div>
            <p>10 specialised agents · checkpointed workflows</p>
          </div>
          <div className="sidebar-user">
            <div className="avatar">{initials}</div>
            <div>
              <strong>{user?.full_name}</strong>
              <span>{titleCase(user?.role)}</span>
            </div>
            <button className="icon-button subtle" onClick={logout} title="Sign out">
              <LogOut size={16} />
            </button>
          </div>
          <div className="sidebar-version">v0.1.0 · Enterprise Preview</div>
        </div>
      </aside>
      {mobileOpen && <div className="sidebar-backdrop" onClick={() => setMobileOpen(false)} />}

      <div className="app-column">
        <header className="topbar">
          <div className="topbar-left">
            <IconButton label="Open navigation" className="mobile-menu" onClick={() => setMobileOpen(true)}>
              <Menu size={19} />
            </IconButton>
            <div className="breadcrumb">
              <span>Business Twin</span>
              <ChevronRight size={13} />
              <strong>{pageNames[location.pathname] || "Workspace"}</strong>
            </div>
          </div>
          <div className="topbar-right">
            <button className="command-trigger" onClick={() => setPaletteOpen(true)}>
              <Search size={15} />
              <span>Search workspace</span>
              <kbd><Command size={11} /> K</kbd>
            </button>
            <Badge tone="violet" dot className="demo-pill">DEMO ENVIRONMENT</Badge>
            <IconButton label="Toggle theme" onClick={toggle}>
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </IconButton>
            <button className="icon-button notification-button" onClick={() => navigate("/reports?tab=alerts")} title="Open incidents">
              <Bell size={17} />
              {alerts > 0 && <span className="notification-dot">{alerts > 9 ? "9+" : alerts}</span>}
            </button>
            <div className="topbar-divider" />
            <div className="user-menu-wrap">
              <button className="user-chip" onClick={() => setUserMenu((open) => !open)}>
                <div className="avatar avatar-sm">{initials}</div>
                <div className="user-chip-copy">
                  <strong>{user?.full_name}</strong>
                  <span>{user?.title || titleCase(user?.role)}</span>
                </div>
              </button>
              {userMenu && (
                <div className="user-menu">
                  <div className="user-menu-head">
                    <div className="avatar">{initials}</div>
                    <div>
                      <strong>{user?.full_name}</strong>
                      <span>{user?.email}</span>
                      <Badge tone={user?.role === "ADMIN" ? "violet" : "info"} className="badge-sm">{titleCase(user?.role)}</Badge>
                    </div>
                  </div>
                  <div className="user-menu-divider" />
                  <button className="menu-row" onClick={() => navigate("/agents")}><Sparkles size={15} /> Agent control center</button>
                  <button className="menu-row" onClick={() => navigate("/integrations")}><Database size={15} /> Data connections</button>
                  <div className="user-menu-divider" />
                  <button className="menu-row menu-danger" onClick={logout}><LogOut size={15} /> Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="app-main">
          <Outlet />
          <footer className="app-footer">
            <span>Measured actuals, calculated metrics, AI interpretation and simulated projections are kept separate.</span>
            <span>Business Twin · Enterprise Preview</span>
          </footer>
        </main>
      </div>

      <Modal open={paletteOpen} onClose={() => setPaletteOpen(false)} title="Command palette" subtitle="Jump to a workspace" width="520px">
        <div className="command-search">
          <Search size={16} />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search pages..." />
        </div>
        <div className="command-list">
          {commands.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.to}
                className="command-item"
                onClick={() => {
                  navigate(item.to);
                  setPaletteOpen(false);
                }}
              >
                <span className="command-icon"><Icon size={17} /></span>
                <span><strong>{item.label}</strong><small>{item.description}</small></span>
                <ChevronRight size={15} />
              </button>
            );
          })}
        </div>
        <div className="command-help"><kbd>↵</kbd> open · <kbd>Esc</kbd> close</div>
      </Modal>
    </div>
  );
}

export function NotificationPreview() {
  const { data } = useApi(() => api.notifications(), []);
  if (!data?.length) return null;
  return (
    <div className="notification-preview">
      {data.slice(0, 4).map((item) => (
        <div key={item.id} className="notification-row">
          <span className="live-dot" />
          <div>
            <strong>{item.subject}</strong>
            <span>{item.channel} · {relativeTime(item.created_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
