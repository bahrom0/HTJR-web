import { describe, expect, it, vi } from 'vitest';

import type { JobSnapshot } from '../../entities/job';
import type { ApiResult } from '../../shared/api/client';

import {
  createJobSubscription,
  exponentialBackoffMs,
  type JobEventSource,
  type JobSnapshotLoader,
  type JobSubscriptionScheduler,
} from './subscription';

const jobId = '2ea62ed2-cbe8-4ad6-a448-2e17db982ea2';

function snapshot(overrides: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: jobId,
    documentId: 'ef91cb45-d9a8-4d6b-8770-dccfc496f056',
    pageId: '09e30d72-8e44-4263-9a72-1b662ee48712',
    state: 'running',
    stage: 'recognizing_lines',
    priority: 0,
    processedCount: 1,
    totalCount: 4,
    attempt: 1,
    maxAttempts: 3,
    cancellationRequested: false,
    errorCode: null,
    errorRetryable: false,
    canCancel: true,
    canRetry: false,
    revision: 2,
    createdAt: '2026-07-18T09:00:00Z',
    updatedAt: '2026-07-18T09:10:00Z',
    duplicate: false,
    ...overrides,
  };
}

function successfulSnapshot(value = snapshot()): ApiResult<JobSnapshot> {
  return { ok: true, value, requestId: 'request-id' };
}

function fakeSource(): JobEventSource {
  return {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    close: vi.fn(),
    onopen: null,
    onerror: null,
  } as unknown as JobEventSource;
}

describe('exponentialBackoffMs', () => {
  it('grows exponentially and remains bounded', () => {
    expect([0, 1, 2, 3, 10].map((attempt) => exponentialBackoffMs(attempt, 100, 800))).toEqual([
      100, 200, 400, 800, 800,
    ]);
  });
});

describe('job subscription lifecycle', () => {
  it('closes the stream, removes its listener, and cancels reconnect work on dispose', async () => {
    const source = fakeSource();
    const scheduled = Symbol('scheduled');
    const scheduler: JobSubscriptionScheduler = {
      schedule: vi.fn(() => scheduled),
      cancel: vi.fn(),
    };
    const subscription = createJobSubscription({
      jobId,
      onState: vi.fn(),
      loadSnapshot: vi.fn(async () => successfulSnapshot()),
      eventSourceFactory: vi.fn(() => source),
      scheduler,
    });

    await subscription.start();
    expect(source.addEventListener).toHaveBeenCalledWith('job', expect.any(Function));
    const onError = source.onerror;
    onError?.call(source as unknown as EventSource, new Event('error'));
    subscription.dispose();

    expect(source.removeEventListener).toHaveBeenCalledWith('job', expect.any(Function));
    expect(source.close).toHaveBeenCalledOnce();
    expect(scheduler.cancel).toHaveBeenCalledWith(scheduled);
  });

  it('aborts an in-flight snapshot and emits no later state after route disposal', async () => {
    let observedAbort = false;
    const loadSnapshot: JobSnapshotLoader = (_jobId, signal) =>
      new Promise((resolve) => {
        signal.addEventListener(
          'abort',
          () => {
            observedAbort = signal.aborted;
            resolve({
              ok: false,
              error: {
                code: 'request_aborted',
                message: 'cancelled',
                retryable: true,
                requestId: 'request-id',
              },
            });
          },
          { once: true },
        );
      });
    const onState = vi.fn();
    const subscription = createJobSubscription({ jobId, onState, loadSnapshot });

    const starting = subscription.start();
    await Promise.resolve();
    subscription.dispose();
    await starting;

    expect(observedAbort).toBe(true);
    expect(onState).toHaveBeenCalledTimes(1);
  });

  it('does not open a stream for a retryable failure awaiting a user retry', async () => {
    const eventSourceFactory = vi.fn(() => fakeSource());
    const onState = vi.fn();
    const subscription = createJobSubscription({
      jobId,
      onState,
      loadSnapshot: vi.fn(async () =>
        successfulSnapshot(
          snapshot({
            state: 'failed_retryable',
            errorCode: 'worker_lease_expired',
            errorRetryable: true,
            canCancel: false,
            canRetry: true,
          }),
        ),
      ),
      eventSourceFactory,
    });

    await subscription.start();

    expect(eventSourceFactory).not.toHaveBeenCalled();
    expect(subscription.getState().connection).toBe('settled');
    subscription.dispose();
  });
});
