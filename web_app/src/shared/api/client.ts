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
export type RequestMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export type RequestOptions = Readonly<{
  method?: RequestMethod;
  signal?: AbortSignal;
  timeoutMs?: number;
  json?: unknown;
  body?: BodyInit | null;
  headers?: Readonly<Record<string, string>>;
  csrfToken?: string;
}>;

function createRequestId(): string {
  return crypto.randomUUID();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isUuid(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
  );
}

export function isIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isErrorEnvelope(
  value: unknown,
): value is { code: string; message: string; retryable: boolean; request_id: string } {
  if (!isRecord(value)) return false;
  return (
    typeof value.code === 'string' &&
    typeof value.message === 'string' &&
    typeof value.retryable === 'boolean' &&
    typeof value.request_id === 'string'
  );
}

function normalizeError(value: unknown, requestId: string): ApiError {
  if (isErrorEnvelope(value)) {
    return {
      code: value.code,
      message: value.message,
      retryable: value.retryable,
      requestId: value.request_id,
    };
  }
  return {
    code: 'invalid_error_response',
    message: 'The server returned an invalid error response.',
    retryable: false,
    requestId,
  };
}

function transportError(error: unknown, requestId: string, signal?: AbortSignal): ApiError {
  if (signal?.aborted) {
    return {
      code: 'request_aborted',
      message: 'The request was cancelled.',
      retryable: true,
      requestId,
    };
  }
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return {
      code: 'request_timeout',
      message: 'The server took too long to respond.',
      retryable: true,
      requestId,
    };
  }
  return {
    code: 'network_error',
    message: 'The server could not be reached.',
    retryable: true,
    requestId,
  };
}

async function readJson(response: Response): Promise<unknown> {
  if (response.status === 204 || response.headers.get('content-length') === '0') return null;
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().includes('application/json')) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function request<T>(
  path: string,
  parse: (value: unknown) => T | null,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  const requestId = createRequestId();
  if (options.json !== undefined && options.body !== undefined) {
    return {
      ok: false,
      error: {
        code: 'invalid_request',
        message: 'A request cannot contain both JSON and a raw body.',
        retryable: false,
        requestId,
      },
    };
  }

  const timeout = AbortSignal.timeout(options.timeoutMs ?? 10_000);
  const combinedSignal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
  try {
    const response = await fetch(`${environment.apiBaseUrl}${path}`, {
      method: options.method ?? 'GET',
      credentials: 'include',
      headers: {
        'X-Request-ID': requestId,
        ...(options.json === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(options.csrfToken ? { 'X-CSRF-Token': options.csrfToken } : {}),
        ...options.headers,
      },
      body: options.json !== undefined ? JSON.stringify(options.json) : (options.body ?? undefined),
      signal: combinedSignal,
    });
    const body = await readJson(response);
    if (!response.ok) return { ok: false, error: normalizeError(body, requestId) };
    const parsed = parse(body);
    if (parsed === null) {
      return {
        ok: false,
        error: {
          code: 'invalid_response',
          message: 'The server response was invalid.',
          retryable: false,
          requestId,
        },
      };
    }
    return {
      ok: true,
      value: parsed,
      requestId: response.headers.get('X-Request-ID') ?? requestId,
    };
  } catch (error) {
    return { ok: false, error: transportError(error, requestId, options.signal) };
  }
}

export type AccessSession = Readonly<{
  authenticated: true;
  expiresAt: string;
  csrfToken?: string;
  authMethod: 'account' | 'access_code';
  user?: AccountProfile;
}>;

export type AccountProfile = Readonly<{
  id: string;
  email: string;
  name: string;
  emailVerified: boolean;
  createdAt: string;
  updatedAt: string;
}>;

function parseAccountProfile(value: unknown): AccountProfile | null {
  if (!isRecord(value)) return null;
  if (
    !isUuid(value.id) ||
    typeof value.email !== 'string' ||
    typeof value.name !== 'string' ||
    typeof value.email_verified !== 'boolean' ||
    !isIsoTimestamp(value.created_at) ||
    !isIsoTimestamp(value.updated_at)
  )
    return null;
  return {
    id: value.id,
    email: value.email,
    name: value.name,
    emailVerified: value.email_verified,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
  };
}

export function parseAccessSession(value: unknown): AccessSession | null {
  if (!isRecord(value)) return null;
  if (value.authenticated !== true || !isIsoTimestamp(value.expires_at)) return null;
  if (value.auth_method !== 'account' && value.auth_method !== 'access_code') return null;
  if (
    value.csrf_token !== undefined &&
    value.csrf_token !== null &&
    typeof value.csrf_token !== 'string'
  ) {
    return null;
  }
  const user =
    value.user === undefined || value.user === null ? undefined : parseAccountProfile(value.user);
  if (value.auth_method === 'account' && !user) return null;
  return {
    authenticated: true,
    expiresAt: value.expires_at,
    authMethod: value.auth_method,
    ...(typeof value.csrf_token === 'string' ? { csrfToken: value.csrf_token } : {}),
    ...(user ? { user } : {}),
  };
}

export function exchangeAccessCode(code: string): Promise<ApiResult<AccessSession>> {
  return request('/access/exchange-code', parseAccessSession, {
    method: 'POST',
    json: { code },
  });
}

export function getAccessSession(signal?: AbortSignal): Promise<ApiResult<AccessSession>> {
  return request('/access/session', parseAccessSession, { signal });
}

export function refreshCsrfToken(): Promise<ApiResult<AccessSession>> {
  return request('/access/csrf', parseAccessSession, { method: 'POST' });
}

export async function logoutAccessSession(csrfToken: string): Promise<ApiResult<true>> {
  return request('/access/logout', () => true, {
    method: 'POST',
    csrfToken,
  });
}

type CodeResponse = Readonly<{
  accepted: true;
  developmentCode?: string;
  expiresAt?: string;
}>;

function parseCodeResponse(value: unknown): CodeResponse | null {
  if (!isRecord(value) || value.accepted !== true) return null;
  if (
    value.development_code !== undefined &&
    value.development_code !== null &&
    typeof value.development_code !== 'string'
  )
    return null;
  if (
    value.expires_at !== undefined &&
    value.expires_at !== null &&
    !isIsoTimestamp(value.expires_at)
  )
    return null;
  return {
    accepted: true,
    ...(typeof value.development_code === 'string'
      ? { developmentCode: value.development_code }
      : {}),
    ...(typeof value.expires_at === 'string' ? { expiresAt: value.expires_at } : {}),
  };
}

export type RegistrationResponse = Readonly<{
  email: string;
  verificationExpiresAt: string;
  developmentCode?: string;
}>;

function parseRegistration(value: unknown): RegistrationResponse | null {
  if (
    !isRecord(value) ||
    typeof value.email !== 'string' ||
    !isIsoTimestamp(value.verification_expires_at)
  )
    return null;
  if (
    value.development_code !== undefined &&
    value.development_code !== null &&
    typeof value.development_code !== 'string'
  )
    return null;
  return {
    email: value.email,
    verificationExpiresAt: value.verification_expires_at,
    ...(typeof value.development_code === 'string'
      ? { developmentCode: value.development_code }
      : {}),
  };
}

export function registerAccount(
  email: string,
  name: string,
  password: string,
): Promise<ApiResult<RegistrationResponse>> {
  return request('/access/register', parseRegistration, {
    method: 'POST',
    json: { email, name, password },
  });
}

export function loginAccount(email: string, password: string): Promise<ApiResult<AccessSession>> {
  return request('/access/login', parseAccessSession, {
    method: 'POST',
    json: { email, password },
  });
}

export function verifyAccountEmail(email: string, code: string): Promise<ApiResult<CodeResponse>> {
  return request('/access/email/verify', parseCodeResponse, {
    method: 'POST',
    json: { email, code },
  });
}

export function resendAccountVerification(email: string): Promise<ApiResult<CodeResponse>> {
  return request('/access/email/resend', parseCodeResponse, {
    method: 'POST',
    json: { email },
  });
}

export function requestPasswordRecovery(email: string): Promise<ApiResult<CodeResponse>> {
  return request('/access/recovery/request', parseCodeResponse, {
    method: 'POST',
    json: { email },
  });
}

export function confirmPasswordRecovery(
  email: string,
  code: string,
  newPassword: string,
): Promise<ApiResult<CodeResponse>> {
  return request('/access/recovery/confirm', parseCodeResponse, {
    method: 'POST',
    json: { email, code, new_password: newPassword },
  });
}

export function parseHealthLive(value: unknown): HealthLive | null {
  if (!isRecord(value)) return null;
  return value.status === 'ok' && typeof value.request_id === 'string'
    ? { status: 'ok', requestId: value.request_id }
    : null;
}

export function getLiveHealth(signal?: AbortSignal): Promise<ApiResult<HealthLive>> {
  return request('/health/live', parseHealthLive, { signal });
}
