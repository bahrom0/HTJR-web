import { describe, expect, it } from 'vitest';

import {
  parseJobEvent,
  parseJobSnapshot,
  type JobEvent,
  type JobSnapshot,
} from '../../entities/job';

import { createInitialJobStreamState, projectJobProgress, reduceJobStream } from './model';

const jobId = '2ea62ed2-cbe8-4ad6-a448-2e17db982ea2';

function snapshot(overrides: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: jobId,
    documentId: 'ef91cb45-d9a8-4d6b-8770-dccfc496f056',
    pageId: '09e30d72-8e44-4263-9a72-1b662ee48712',
    state: 'running',
    stage: 'recognizing_lines',
    priority: 0,
    processedCount: 0,
    totalCount: 0,
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

function jobEvent(overrides: Partial<JobEvent> = {}): JobEvent {
  return {
    jobId,
    sequence: 1,
    eventType: 'stage_completed',
    state: 'running',
    stage: 'recognizing_lines',
    processedCount: 1,
    totalCount: 4,
    attempt: 1,
    maxAttempts: 3,
    cancellationRequested: false,
    errorCode: null,
    errorRetryable: false,
    canCancel: true,
    canRetry: false,
    createdAt: '2026-07-18T09:11:00Z',
    ...overrides,
  };
}

describe('job runtime contract', () => {
  it('accepts a persisted revision zero snapshot and derives action availability', () => {
    const parsed = parseJobSnapshot({
      id: jobId,
      document_id: 'ef91cb45-d9a8-4d6b-8770-dccfc496f056',
      page_id: '09e30d72-8e44-4263-9a72-1b662ee48712',
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
      created_at: '2026-07-18T09:00:00Z',
      updated_at: '2026-07-18T09:00:00Z',
      duplicate: false,
    });

    expect(parsed).toMatchObject({ revision: 0, canCancel: true, canRetry: false });
  });

  it('rejects unknown event fields and impossible server counters', () => {
    const wireEvent = {
      job_id: jobId,
      sequence: 2,
      event_type: 'stage_completed',
      state: 'running',
      stage: 'recognizing_lines',
      processed_count: 3,
      total_count: 2,
      attempt: 1,
      max_attempts: 3,
      cancellation_requested: false,
      error_code: null,
      error_retryable: false,
      can_cancel: true,
      can_retry: false,
      created_at: '2026-07-18T09:11:00Z',
    };

    expect(parseJobEvent(wireEvent)).toBeNull();
    expect(parseJobEvent({ ...wireEvent, processed_count: 2, unversioned: true })).toBeNull();
  });
});

describe('truthful job projection', () => {
  it('does not invent a percentage while the server total is unknown', () => {
    expect(projectJobProgress(snapshot())).toMatchObject({
      counterLabel: null,
      progressRatio: null,
      progressPercent: null,
    });
  });

  it('uses only persisted processed and total counters for measured progress', () => {
    expect(projectJobProgress(snapshot({ processedCount: 3, totalCount: 4 }))).toMatchObject({
      counterLabel: '3 из 4',
      progressRatio: 0.75,
      progressPercent: 75,
    });
  });

  it('projects a retryable failure as settled with an explicit retry action', () => {
    const projection = projectJobProgress(
      snapshot({
        state: 'failed_retryable',
        errorCode: 'worker_lease_expired',
        errorRetryable: true,
        canCancel: false,
        canRetry: true,
      }),
    );

    expect(projection).toMatchObject({
      isTerminal: true,
      canRetry: true,
      error: { code: 'worker_lease_expired', retryable: true },
    });
  });
});

describe('job event reducer', () => {
  it('deduplicates and rejects out-of-order sequence IDs', () => {
    const initial = reduceJobStream(createInitialJobStreamState(jobId), {
      type: 'snapshot',
      snapshot: snapshot(),
    });
    const sequenceThree = reduceJobStream(initial, {
      type: 'event',
      event: jobEvent({ sequence: 3, processedCount: 3 }),
    });

    expect(sequenceThree.snapshot?.processedCount).toBe(3);
    expect(
      reduceJobStream(sequenceThree, {
        type: 'event',
        event: jobEvent({ sequence: 2, processedCount: 2 }),
      }),
    ).toBe(sequenceThree);
    expect(
      reduceJobStream(sequenceThree, {
        type: 'event',
        event: jobEvent({ sequence: 3, processedCount: 4 }),
      }),
    ).toBe(sequenceThree);
  });

  it('advances a replay cursor without rolling a refresh snapshot backwards', () => {
    const initial = reduceJobStream(createInitialJobStreamState(jobId), {
      type: 'snapshot',
      snapshot: snapshot({ processedCount: 4, totalCount: 4 }),
    });
    const replayed = reduceJobStream(initial, {
      type: 'event',
      event: jobEvent({
        sequence: 1,
        processedCount: 1,
        createdAt: '2026-07-18T09:05:00Z',
      }),
    });

    expect(replayed.lastSequence).toBe(1);
    expect(replayed.snapshot?.processedCount).toBe(4);
  });

  it('does not replace a newer server revision with a stale polling response', () => {
    const current = reduceJobStream(createInitialJobStreamState(jobId), {
      type: 'snapshot',
      snapshot: snapshot({ revision: 4 }),
    });
    const afterStalePoll = reduceJobStream(current, {
      type: 'snapshot',
      snapshot: snapshot({ revision: 3, processedCount: 0 }),
    });

    expect(afterStalePoll).toBe(current);
  });
});
