import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./lib/auth";
import { AppLayout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";
import { AgentsPage } from "./pages/AgentsPage";
import { LogicStudioPage } from "./pages/LogicStudioPage";
import { DecisionCenterPage } from "./pages/DecisionCenterPage";
import { SimulationPage } from "./pages/SimulationPage";
import { ReportsPage } from "./pages/ReportsPage";
import { IntegrationsPage } from "./pages/IntegrationsPage";
import { Spinner } from "./components/ui";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="app-loading">
        <div className="loading-brand">
          <div className="brand-mark"><span /><span /><span /></div>
          <strong>BUSINESS TWIN</strong>
          <span>Connecting to the digital twin…</span>
          <Spinner size={20} />
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return <>{children}</>;
}

export default function App() {
  const { user, loading } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={loading ? <div className="app-loading"><Spinner size={22} /></div> : user ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route
        path="/"
        element={
          <Protected>
            <AppLayout />
          </Protected>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="decisions" element={<DecisionCenterPage />} />
        <Route path="simulation" element={<SimulationPage />} />
        <Route path="logic" element={<LogicStudioPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
