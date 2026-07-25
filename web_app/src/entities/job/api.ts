import { request, type ApiResult } from '../../shared/api/client';

import { parseJobSnapshot, type JobSnapshot } from './model';

function jobPath(jobId: string): string {
  return `/jobs/${encodeURIComponent(jobId)}`;
}

/**
 * Starts the durable, server-owned recognition pipeline for one prepared page.
 * The caller owns a stable idempotency key for the current page revision so an
 * uncertain network response can be retried without creating another job.
 */
export function createRecognitionJob(
  pageId: string,
  idempotencyKey: string,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<JobSnapshot>> {
  return request(`/pages/${encodeURIComponent(pageId)}/recognition-jobs`, parseJobSnapshot, {
    method: 'POST',
    json: { priority: 0 },
    csrfToken,
    signal,
    timeoutMs: 15_000,
    headers: { 'Idempotency-Key': idempotencyKey },
  });
}

export function getJobSnapshot(
  jobId: string,
  signal?: AbortSignal,
): Promise<ApiResult<JobSnapshot>> {
  return request(jobPath(jobId), parseJobSnapshot, { signal });
}

export function cancelJob(
  jobId: string,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<JobSnapshot>> {
  return request(`${jobPath(jobId)}/cancel`, parseJobSnapshot, {
    method: 'POST',
    csrfToken,
    signal,
  });
}

export function retryJob(
  jobId: string,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<JobSnapshot>> {
  return request(`${jobPath(jobId)}/retry`, parseJobSnapshot, {
    method: 'POST',
    csrfToken,
    signal,
  });
}
