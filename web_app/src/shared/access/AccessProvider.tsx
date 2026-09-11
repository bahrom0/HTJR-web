import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {
  getAccessSession,
  getAnonymousSessionToken,
  loginAccount,
  logoutAccessSession,
  registerAccount,
  refreshCsrfToken,
  type AccountProfile,
} from '@shared/api/client';

type State = 'checking' | 'authenticated' | 'anonymous';
type AccessContextValue = Readonly<{
  state: State;
  expiresAt: string | null;
  csrfToken: string | null;
  user: AccountProfile | null;
  register: (email: string, name: string, password: string) => Promise<string | null>;
  login: (email: string, password: string) => Promise<string | null>;
  logout: () => Promise<void>;
  reconnect: () => Promise<void>;
}>;

const AccessContext = createContext<AccessContextValue | null>(null);

export function AccessProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [state, setState] = useState<State>('checking');
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [user, setUser] = useState<AccountProfile | null>(null);

  const reconnect = useCallback(async () => {
    setState('checking');
    try {
      const session = await getAccessSession();
      if (session.ok) {
        const csrf = await refreshCsrfToken();
        setExpiresAt(session.value.expiresAt);
        setCsrfToken(csrf.ok ? (csrf.value.csrfToken ?? null) : null);
        setUser(session.value.user);
        setState('authenticated');
        return;
      }
    } catch {
      // continue to anonymous session fallback
    }

    // Seamless anonymous session without registration
    const anonToken = getAnonymousSessionToken();
    setUser({
      id: anonToken,
      name: 'Пользователь',
      email: '',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    setExpiresAt(new Date(Date.now() + 10 * 365 * 24 * 3600 * 1000).toISOString());
    setCsrfToken(null);
    setState('authenticated');
  }, []);

  const clear = useCallback(() => {
    localStorage.removeItem('htr_anonymous_token');
    void reconnect();
  }, [reconnect]);

  useEffect(() => {
    const timeout = window.setTimeout(() => void reconnect(), 0);
    return () => window.clearTimeout(timeout);
  }, [reconnect]);

  useEffect(() => {
    if (!expiresAt) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    if (remaining <= 0) {
      const timeout = window.setTimeout(clear, 0);
      return () => window.clearTimeout(timeout);
    }
    const timeout = window.setTimeout(() => {
      setCsrfToken(null);
      setExpiresAt(null);
      setUser(null);
      setState('anonymous');
    }, remaining);
    return () => window.clearTimeout(timeout);
  }, [clear, expiresAt]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginAccount(email, password);
    if (!result.ok) return `${result.error.code}:${result.error.message}`;
    setExpiresAt(result.value.expiresAt);
    setCsrfToken(result.value.csrfToken ?? null);
    setUser(result.value.user);
    setState('authenticated');
    return null;
  }, []);

  const register = useCallback(async (email: string, name: string, password: string) => {
    const result = await registerAccount(email, name, password);
    if (!result.ok) return `${result.error.code}:${result.error.message}`;
    setExpiresAt(result.value.expiresAt);
    setCsrfToken(result.value.csrfToken ?? null);
    setUser(result.value.user);
    setState('authenticated');
    return null;
  }, []);

  const logout = useCallback(async () => {
    if (csrfToken) await logoutAccessSession(csrfToken);
    clear();
  }, [clear, csrfToken]);

  const value = useMemo(
    () => ({
      state,
      expiresAt,
      csrfToken,
      user,
      register,
      login,
      logout,
      reconnect,
    }),
    [state, expiresAt, csrfToken, user, register, login, logout, reconnect],
  );
  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>;
}

export function useAccess(): AccessContextValue {
  const value = useContext(AccessContext);
  if (!value) throw new Error('useAccess must be used within AccessProvider');
  return value;
}
