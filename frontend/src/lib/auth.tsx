import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, cachedUser, clearSession, getToken, setSession } from "./api";
import type { User } from "./types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => (getToken() ? cachedUser() : null));
  const [loading, setLoading] = useState(() => Boolean(getToken()));

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
  }, []);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    let active = true;
    api
      .me()
      .then((me) => {
        if (active) setUser(me);
      })
      .catch(() => {
        if (active) logout();
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [logout]);

  useEffect(() => {
    const handler = () => setUser(null);
    window.addEventListener("twin:unauthorized", handler);
    return () => window.removeEventListener("twin:unauthorized", handler);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await api.login(email, password);
    setSession(result.access_token, result.user);
    setUser(result.user);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}

export function canApprove(user: User | null): boolean {
  return user?.role === "ADMIN" || user?.role === "APPROVER";
}

export function canEditLogic(user: User | null): boolean {
  return user?.role === "ADMIN" || user?.role === "ANALYST";
}

export function canRun(user: User | null): boolean {
  return user?.role !== "VIEWER";
}
