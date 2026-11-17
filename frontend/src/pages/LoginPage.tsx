import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  BrainCircuit,
  Eye,
  EyeOff,
  Fingerprint,
  GitBranch,
  LineChart,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  Waypoints,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { Button } from "../components/ui";

const accounts = [
  { role: "CFO · Approver", email: "cfo@northwind.demo" },
  { role: "Analyst", email: "analyst@northwind.demo" },
  { role: "Administrator", email: "admin@northwind.demo" },
];

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@northwind.demo");
  const [password, setPassword] = useState("TwinDemo!2026");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate("/");
    } catch (exc: any) {
      setError(exc?.message || "Unable to sign in");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-shell">
      <section className="login-visual">
        <div className="login-grid" />
        <div className="login-orbit login-orbit-one" />
        <div className="login-orbit login-orbit-two" />
        <div className="login-brand">
          <div className="brand-mark brand-mark-light">
            <span /><span /><span />
          </div>
          <div><strong>BUSINESS TWIN</strong><span>Autonomous Intelligence</span></div>
        </div>
        <div className="login-hero">
          <div className="login-eyebrow"><Sparkles size={14} /> Multi-agent business operating system</div>
          <h1>The operational brain<br />for the modern business.</h1>
          <p>
            Continuous intelligence, independent decision audit, controlled execution and a
            predictive twin — built on deterministic business logic, not guesswork.
          </p>
          <div className="login-capabilities">
            <div className="capability">
              <span className="capability-icon"><Waypoints size={18} /></span>
              <div><strong>Observe & calculate</strong><span>Every number traced to validated evidence</span></div>
            </div>
            <div className="capability">
              <span className="capability-icon"><GitBranch size={18} /></span>
              <div><strong>Decide & audit</strong><span>An independent controller challenges every recommendation</span></div>
            </div>
            <div className="capability">
              <span className="capability-icon"><LineChart size={18} /></span>
              <div><strong>Simulate & measure</strong><span>Scenarios, Monte Carlo and projected-versus-actual</span></div>
            </div>
          </div>
        </div>
        <div className="login-pipeline">
          <span>DATA</span><i /><span>LOGIC</span><i /><span>TWIN</span><i /><span>DECISION</span><i /><span>EXECUTE</span>
        </div>
        <div className="login-foot">
          <ShieldCheck size={15} />
          <span>Human authorisation · Immutable audit trail · Tenant isolation</span>
        </div>
      </section>

      <section className="login-form-side">
        <div className="login-form-wrap">
          <div className="login-form-head">
            <span className="login-badge"><Fingerprint size={14} /> Secure workspace</span>
            <h2>Welcome back</h2>
            <p>Sign in to the Northwind Retail digital twin.</p>
          </div>

          <form onSubmit={submit} className="login-form">
            <label className="field">
              <span>Work email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="username"
                required
              />
            </label>
            <label className="field">
              <span>Password</span>
              <span className="password-field">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button type="button" onClick={() => setShowPassword((value) => !value)} aria-label="Toggle password visibility">
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </span>
            </label>
            {error && <div className="login-error">{error}</div>}
            <Button type="submit" variant="primary" size="lg" loading={loading} className="login-submit">
              Enter command center <ArrowRight size={16} />
            </Button>
          </form>

          <div className="login-divider"><span>Demo personas</span></div>
          <div className="login-personas">
            {accounts.map((account) => (
              <button
                key={account.email}
                type="button"
                className={`persona ${email === account.email ? "persona-active" : ""}`}
                onClick={() => {
                  setEmail(account.email);
                  setPassword("TwinDemo!2026");
                }}
              >
                <span>{account.role}</span>
                <strong>{account.email.split("@")[0]}</strong>
              </button>
            ))}
          </div>
          <div className="login-hint">
            <LockKeyhole size={14} />
            <span>All personas use the demo password <code>TwinDemo!2026</code>. Simulated sources are clearly labelled.</span>
          </div>

          <div className="login-system">
            <span><span className="live-dot" /> System operational</span>
            <span><BrainCircuit size={14} /> 10 agents registered</span>
          </div>
        </div>
      </section>
    </div>
  );
}
