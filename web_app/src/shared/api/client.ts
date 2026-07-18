import { environment } from '../lib/env';

export type ApiError = Readonly<{
  code: string;
  message: string;
  retryable: boolean;
  requestId: string;
}>;

export type ApiResult<T> =
  | { ok: true; value: T; requestId: string }
  | { ok: false; error: ApiError };

export type HealthLive = Readonly<{ status: 'ok'; requestId: string }>;

function createRequestId(): string {
  return crypto.randomUUID();
}

function isErrorEnvelope(
  value: unknown,
): value is { code: string; message: string; retryable: boolean; request_id: string } {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.code === 'string' &&
    typeof candidate.message === 'string' &&
    typeof candidate.retryable === 'boolean' &&
    typeof candidate.request_id === 'string'
  );
}

function normalizeError(value: unknown, requestId: string): ApiError {
  if (isErrorEnvelope(value))
    return {
      code: value.code,
      message: value.message,
      retryable: value.retryable,
      requestId: value.request_id,
    };
  return {
    code: 'network_error',
    message: 'The server could not be reached.',
    retryable: true,
    requestId,
  };
}

export async function request<T>(
  path: string,
  parse: (value: unknown) => T | null,
  signal?: AbortSignal,
  init?: Readonly<{ method?: 'GET' | 'POST'; body?: unknown; csrfToken?: string }>,
): Promise<ApiResult<T>> {
  const requestId = createRequestId();
  const timeout = AbortSignal.timeout(10_000);
  const combinedSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  try {
    const response = await fetch(`${environment.apiBaseUrl}${path}`, {
      method: init?.method ?? 'GET',
      credentials: 'include',
      headers: {
        'X-Request-ID': requestId,
        ...(init?.body === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(init?.csrfToken ? { 'X-CSRF-Token': init.csrfToken } : {}),
      },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      signal: combinedSignal,
    });
    const body: unknown = response.status === 204 ? {} : await response.json();
    if (!response.ok) return { ok: false, error: normalizeError(body, requestId) };
    const parsed = parse(body);
    if (parsed === null)
      return {
        ok: false,
        error: {
          code: 'invalid_response',
          message: 'The server response was invalid.',
          retryable: false,
          requestId,
        },
      };
    return {
      ok: true,
      value: parsed,
      requestId: response.headers.get('X-Request-ID') ?? requestId,
    };
  } catch {
    return { ok: false, error: normalizeError(null, requestId) };
  }
}

export type AccessSession = Readonly<{ authenticated: true; expiresAt: string; csrfToken?: string }>;

function parseAccessSession(value: unknown): AccessSession | null {
  if (typeof value !== 'object' || value === null) return null;
  const item = value as Record<string, unknown>;
  if (item.authenticated !== true || typeof item.expires_at !== 'string') return null;
  if (item.csrf_token !== undefined && item.csrf_token !== null && typeof item.csrf_token !== 'string') return null;
  return { authenticated: true, expiresAt: item.expires_at, ...(typeof item.csrf_token === 'string' ? { csrfToken: item.csrf_token } : {}) };
}

export function exchangeAccessCode(code: string): Promise<ApiResult<AccessSession>> {
  return request('/access/exchange', parseAccessSession, undefined, { method: 'POST', body: { code } });
}

export function getAccessSession(signal?: AbortSignal): Promise<ApiResult<AccessSession>> {
  return request('/access/session', parseAccessSession, signal);
}

export function refreshCsrfToken(): Promise<ApiResult<AccessSession>> {
  return request('/access/csrf', parseAccessSession, undefined, { method: 'POST' });
}

export async function logoutAccessSession(csrfToken: string): Promise<ApiResult<true>> {
  return request('/access/logout', () => true, undefined, { method: 'POST', csrfToken });
}

export function parseHealthLive(value: unknown): HealthLive | null {
  if (typeof value !== 'object' || value === null) return null;
  const candidate = value as Record<string, unknown>;
  return candidate.status === 'ok' && typeof candidate.request_id === 'string'
    ? { status: 'ok', requestId: candidate.request_id }
    : null;
}

export function getLiveHealth(signal?: AbortSignal): Promise<ApiResult<HealthLive>> {
  return request('/health/live', parseHealthLive, signal);
}
