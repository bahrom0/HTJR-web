import { afterEach, describe, expect, it, vi } from 'vitest';

import { createRecognitionJob } from './api';
import { parseJobSnapshot } from './model';

const pageId = '09e30d72-8e44-4263-9a72-1b662ee48712';
const jobId = '2ea62ed2-cbe8-4ad6-a448-2e17db982ea2';

afterEach(() => vi.restoreAllMocks());

describe('createRecognitionJob', () => {
  it('uses the durable page-job endpoint with a stable caller-provided idempotency key', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          id: jobId,
          document_id: 'ef91cb45-d9a8-4d6b-8770-dccfc496f056',
          page_id: pageId,
          state: 'queued',
          stage: 'queued',
          priority: 0,
          processed_count: 0,
          total_count: 0,
          attempt: 0,
          max_attempts: 3,
          cancellation_requested: false,
          error_code: null,
          error_retryable: false,
          revision: 0,
          created_at: '2026-07-20T09:00:00Z',
          updated_at: '2026-07-20T09:00:00Z',
          duplicate: false,
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    const result = await createRecognitionJob(pageId, `recognition:${pageId}:4`, 'csrf-token');

    expect(result).toMatchObject({ ok: true, value: { id: jobId, state: 'queued' } });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/pages/${pageId}/recognition-jobs`);
    expect(init).toMatchObject({
      method: 'POST',
      headers: expect.objectContaining({
        'Idempotency-Key': `recognition:${pageId}:4`,
        'X-CSRF-Token': 'csrf-token',
      }),
    });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ priority: 0 });
  });

  it('accepts the persisted pause that waits for a region review', () => {
    expect(
      parseJobSnapshot({
        id: jobId,
        document_id: 'ef91cb45-d9a8-4d6b-8770-dccfc496f056',
        page_id: pageId,
        state: 'awaiting_region_review',
        stage: 'awaiting_region_review',
        priority: 0,
        processed_count: 1,
        total_count: 1,
        attempt: 1,
        max_attempts: 3,
        cancellation_requested: false,
        error_code: null,
        error_retryable: false,
        revision: 2,
        created_at: '2026-07-20T09:00:00Z',
        updated_at: '2026-07-20T09:00:01Z',
        duplicate: false,
      }),
    ).toMatchObject({ state: 'awaiting_region_review', canCancel: true });
  });
});
