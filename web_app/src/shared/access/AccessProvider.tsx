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
  loginAccount,
  logoutAccessSession,
  refreshCsrfToken,
  type AccountProfile,
} from '@shared/api/client';

type State = 'checking' | 'authenticated' | 'anonymous';
type AccessContextValue = Readonly<{
  state: State;
  expiresAt: string | null;
  csrfToken: string | null;
  authMethod: 'account' | 'access_code' | null;
  user: AccountProfile | null;
  exchange: (code: string) => Promise<string | null>;
  login: (email: string, password: string) => Promise<string | null>;
  logout: () => Promise<void>;
  reconnect: () => Promise<void>;
}>;

const AccessContext = createContext<AccessContextValue | null>(null);

export function AccessProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [state, setState] = useState<State>('checking');
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [authMethod, setAuthMethod] = useState<'account' | 'access_code' | null>(null);
  const [user, setUser] = useState<AccountProfile | null>(null);

  const clear = useCallback(() => {
    setExpiresAt(null);
    setCsrfToken(null);
    setAuthMethod(null);
    setUser(null);
    setState('anonymous');
  }, []);

  const reconnect = useCallback(async () => {
    setState('checking');
    const session = await getAccessSession();
    if (!session.ok) {
      clear();
      return;
    }
    const csrf = await refreshCsrfToken();
    setExpiresAt(session.value.expiresAt);
    setCsrfToken(csrf.ok ? (csrf.value.csrfToken ?? null) : null);
    setAuthMethod(session.value.authMethod);
    setUser(session.value.user ?? null);
    setState('authenticated');
  }, [clear]);

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
      setAuthMethod(null);
      setUser(null);
      setState('anonymous');
    }, remaining);
    return () => window.clearTimeout(timeout);
  }, [clear, expiresAt]);

  const exchange = useCallback(async (code: string) => {
    const result = await exchangeAccessCode(code);
    if (!result.ok) return result.error.message;
    setExpiresAt(result.value.expiresAt);
    setCsrfToken(result.value.csrfToken ?? null);
    setAuthMethod(result.value.authMethod);
    setUser(result.value.user ?? null);
    setState('authenticated');
    return null;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const result = await loginAccount(email, password);
    if (!result.ok) return `${result.error.code}:${result.error.message}`;
    setExpiresAt(result.value.expiresAt);
    setCsrfToken(result.value.csrfToken ?? null);
    setAuthMethod(result.value.authMethod);
    setUser(result.value.user ?? null);
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
      authMethod,
      user,
      exchange,
      login,
      logout,
      reconnect,
    }),
    [state, expiresAt, csrfToken, authMethod, user, exchange, login, logout, reconnect],
  );
  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>;
}

export function useAccess(): AccessContextValue {
  const value = useContext(AccessContext);
  if (!value) throw new Error('useAccess must be used within AccessProvider');
  return value;
}
