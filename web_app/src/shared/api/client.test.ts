import { afterEach, describe, expect, it, vi } from 'vitest';

import healthFixture from '../../../contracts/health-live.json';
import { isIsoTimestamp, isUuid, parseAccessSession, parseHealthLive, request } from './client';

afterEach(() => vi.restoreAllMocks());

describe('parseHealthLive', () => {
  it('maps the API snake_case contract to the Web projection', () => {
    expect(parseHealthLive(healthFixture)).toEqual({ status: 'ok', requestId: 'contract-test' });
  });

  it('rejects malformed contract payloads', () => {
    expect(parseHealthLive({ status: 'ok' })).toBeNull();
  });
});

describe('contract primitives', () => {
  it('accepts canonical UUIDs and rejects arbitrary IDs', () => {
    expect(isUuid('2ea62ed2-cbe8-4ad6-a448-2e17db982ea2')).toBe(true);
    expect(isUuid('document-1')).toBe(false);
  });

  it('accepts timezone-qualified ISO timestamps only', () => {
    expect(isIsoTimestamp('2026-07-18T09:45:30.123+00:00')).toBe(true);
    expect(isIsoTimestamp('2026-07-18T09:45:30Z')).toBe(true);
    expect(isIsoTimestamp('2026-07-18 09:45:30')).toBe(false);
  });

  it('rejects an access session with a malformed expiry', () => {
    expect(
      parseAccessSession({ authenticated: true, expires_at: 'tomorrow', csrf_token: null }),
    ).toBeNull();
  });
});

describe('request transport', () => {
  it('sends one same-origin request and preserves the server request ID', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', request_id: 'server-id' }), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': 'server-id',
        },
      }),
    );

    const result = await request('/health/live', parseHealthLive, { method: 'GET' });

    expect(result).toEqual({
      ok: true,
      value: { status: 'ok', requestId: 'server-id' },
      requestId: 'server-id',
    });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/health/live');
    expect(init).toMatchObject({ method: 'GET', credentials: 'include' });
  });

  it('normalizes a typed server error without exposing a FastAPI detail body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'request_validation_failed',
          message: 'The request is invalid.',
          retryable: false,
          request_id: 'request-1',
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const result = await request('/access/login', parseAccessSession, {
      method: 'POST',
      json: { email: 'user@example.test', password: 'not-logged-by-client' },
    });

    expect(result).toEqual({
      ok: false,
      error: {
        code: 'request_validation_failed',
        message: 'The request is invalid.',
        retryable: false,
        requestId: 'request-1',
      },
    });
  });

  it('rejects ambiguous JSON and raw request bodies before fetch', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');

    const result = await request('/documents', () => true, {
      method: 'POST',
      json: {},
      body: new Blob(['image']),
    });

    expect(result).toMatchObject({ ok: false, error: { code: 'invalid_request' } });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('logs safe response shape and request ID when contract parsing fails', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ page_id: 'bad-region-id', regions: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-Request-ID': 'server-shape-id' },
      }),
    );

    const result = await request('/pages/page-id/regions', () => null);

    expect(result).toMatchObject({
      ok: false,
      error: { code: 'invalid_response', requestId: 'server-shape-id' },
    });
    expect(consoleError).toHaveBeenCalledWith('api_invalid_response', {
      path: '/pages/page-id/regions',
      method: 'GET',
      status: 200,
      requestId: 'server-shape-id',
      bodyType: 'object',
      bodyKeys: ['page_id', 'regions'],
    });
  });
});
