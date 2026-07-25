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
  exchangeAccessCode,
  getAccessSession,
  logoutAccessSession,
  refreshCsrfToken,
} from '@shared/api/client';

type State = 'checking' | 'authenticated' | 'anonymous';
type AccessContextValue = Readonly<{
  state: State;
  expiresAt: string | null;
  csrfToken: string | null;
  exchange: (code: string) => Promise<string | null>;
  logout: () => Promise<void>;
  reconnect: () => Promise<void>;
}>;

const AccessContext = createContext<AccessContextValue | null>(null);

export function AccessProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [state, setState] = useState<State>('checking');
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);

  const reconnect = useCallback(async () => {
    setState('checking');
    const session = await getAccessSession();
    if (!session.ok) {
      setExpiresAt(null);
      setCsrfToken(null);
      setState('anonymous');
      return;
    }
    const csrf = await refreshCsrfToken();
    setExpiresAt(session.value.expiresAt);
    setCsrfToken(csrf.ok ? (csrf.value.csrfToken ?? null) : null);
    setState('authenticated');
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => void reconnect(), 0);
    return () => window.clearTimeout(timeout);
  }, [reconnect]);

  useEffect(() => {
    if (!expiresAt) return;
    const remaining = new Date(expiresAt).getTime() - Date.now();
    if (remaining <= 0) {
      const timeout = window.setTimeout(() => setState('anonymous'), 0);
      return () => window.clearTimeout(timeout);
    }
    const timeout = window.setTimeout(() => {
      setCsrfToken(null);
      setExpiresAt(null);
      setState('anonymous');
    }, remaining);
    return () => window.clearTimeout(timeout);
  }, [expiresAt]);

  const exchange = useCallback(async (code: string) => {
    const result = await exchangeAccessCode(code);
    if (!result.ok) return result.error.message;
    setExpiresAt(result.value.expiresAt);
    setCsrfToken(result.value.csrfToken ?? null);
    setState('authenticated');
    return null;
  }, []);

  const logout = useCallback(async () => {
    if (csrfToken) await logoutAccessSession(csrfToken);
    setExpiresAt(null);
    setCsrfToken(null);
    setState('anonymous');
  }, [csrfToken]);

  const value = useMemo(
    () => ({ state, expiresAt, csrfToken, exchange, logout, reconnect }),
    [state, expiresAt, csrfToken, exchange, logout, reconnect],
  );
  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>;
}

export function useAccess(): AccessContextValue {
  const value = useContext(AccessContext);
  if (!value) throw new Error('useAccess must be used within AccessProvider');
  return value;
}
