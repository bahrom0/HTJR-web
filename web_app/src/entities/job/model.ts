import { isIsoTimestamp, isUuid } from '../../shared/api/client';

export const jobStates = [
  'queued',
  'running',
  'awaiting_region_review',
  'completed',
  'partial',
  'failed_retryable',
  'failed_terminal',
  'cancelled',
] as const;

export type JobState = (typeof jobStates)[number];

export const jobStages = [
  'queued',
  'uploading',
  'validating',
  'preprocessing',
  'detecting_regions',
  'awaiting_region_review',
  'recognizing_lines',
  'assembling',
  'suggesting',
  'ready_for_review',
  'completed',
] as const;

export type JobStage = (typeof jobStages)[number];

export type JobSnapshot = Readonly<{
  id: string;
  documentId: string;
  pageId: string;
  state: JobState;
  stage: JobStage;
  priority: number;
  processedCount: number;
  totalCount: number;
  attempt: number;
  maxAttempts: number;
  cancellationRequested: boolean;
  errorCode: string | null;
  errorRetryable: boolean;
  canCancel: boolean;
  canRetry: boolean;
  revision: number;
  createdAt: string;
  updatedAt: string;
  duplicate: boolean;
}>;

export type JobEvent = Readonly<{
  jobId: string;
  sequence: number;
  eventType: string;
  state: JobState;
  stage: JobStage;
  processedCount: number;
  totalCount: number;
  attempt: number;
  maxAttempts: number;
  cancellationRequested: boolean;
  errorCode: string | null;
  errorRetryable: boolean;
  canCancel: boolean;
  canRetry: boolean;
  createdAt: string;
}>;

const jobStateSet = new Set<string>(jobStates);
const jobStageSet = new Set<string>(jobStages);

const snapshotRequiredKeys = [
  'id',
  'document_id',
  'page_id',
  'state',
  'stage',
  'priority',
  'processed_count',
  'total_count',
  'attempt',
  'max_attempts',
  'cancellation_requested',
  'error_code',
  'error_retryable',
  'revision',
  'created_at',
  'updated_at',
] as const;

const snapshotOptionalKeys = ['duplicate', 'can_cancel', 'can_retry'] as const;

const eventKeys = [
  'job_id',
  'sequence',
  'event_type',
  'state',
  'stage',
  'processed_count',
  'total_count',
  'attempt',
  'max_attempts',
  'cancellation_requested',
  'error_code',
  'error_retryable',
  'can_cancel',
  'can_retry',
  'created_at',
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasContractKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const allowed = new Set([...required, ...optional]);
  return (
    required.every((key) => key in value) && Object.keys(value).every((key) => allowed.has(key))
  );
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0;
}

function isJobState(value: unknown): value is JobState {
  return typeof value === 'string' && jobStateSet.has(value);
}

function isJobStage(value: unknown): value is JobStage {
  return typeof value === 'string' && jobStageSet.has(value);
}

function isErrorCode(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && value.length > 0);
}

function deriveCanCancel(state: JobState, cancellationRequested: boolean): boolean {
  return (
    (state === 'queued' || state === 'running' || state === 'awaiting_region_review') &&
    !cancellationRequested
  );
}

function deriveCanRetry(
  state: JobState,
  errorRetryable: boolean,
  attempt: number,
  maxAttempts: number,
): boolean {
  return state === 'failed_retryable' && errorRetryable && attempt < maxAttempts;
}

export function parseJobSnapshot(value: unknown): JobSnapshot | null {
  if (!isRecord(value) || !hasContractKeys(value, snapshotRequiredKeys, snapshotOptionalKeys)) {
    return null;
  }

  if (
    !isUuid(value.id) ||
    !isUuid(value.document_id) ||
    !isUuid(value.page_id) ||
    !isJobState(value.state) ||
    !isJobStage(value.stage) ||
    typeof value.priority !== 'number' ||
    !Number.isInteger(value.priority) ||
    !isNonNegativeInteger(value.processed_count) ||
    !isNonNegativeInteger(value.total_count) ||
    value.processed_count > value.total_count ||
    !isNonNegativeInteger(value.attempt) ||
    !isPositiveInteger(value.max_attempts) ||
    value.attempt > value.max_attempts ||
    typeof value.cancellation_requested !== 'boolean' ||
    !isErrorCode(value.error_code) ||
    typeof value.error_retryable !== 'boolean' ||
    !isNonNegativeInteger(value.revision) ||
    !isIsoTimestamp(value.created_at) ||
    !isIsoTimestamp(value.updated_at) ||
    (value.duplicate !== undefined && typeof value.duplicate !== 'boolean') ||
    (value.can_cancel !== undefined && typeof value.can_cancel !== 'boolean') ||
    (value.can_retry !== undefined && typeof value.can_retry !== 'boolean')
  ) {
    return null;
  }

  return {
    id: value.id,
    documentId: value.document_id,
    pageId: value.page_id,
    state: value.state,
    stage: value.stage,
    priority: value.priority,
    processedCount: value.processed_count,
    totalCount: value.total_count,
    attempt: value.attempt,
    maxAttempts: value.max_attempts,
    cancellationRequested: value.cancellation_requested,
    errorCode: value.error_code,
    errorRetryable: value.error_retryable,
    canCancel: value.can_cancel ?? deriveCanCancel(value.state, value.cancellation_requested),
    canRetry:
      value.can_retry ??
      deriveCanRetry(value.state, value.error_retryable, value.attempt, value.max_attempts),
    revision: value.revision,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    duplicate: value.duplicate ?? false,
  };
}

export function parseJobEvent(value: unknown): JobEvent | null {
  if (!isRecord(value) || !hasContractKeys(value, eventKeys)) return null;

  if (
    !isUuid(value.job_id) ||
    !isPositiveInteger(value.sequence) ||
    typeof value.event_type !== 'string' ||
    value.event_type.length === 0 ||
    !isJobState(value.state) ||
    !isJobStage(value.stage) ||
    !isNonNegativeInteger(value.processed_count) ||
    !isNonNegativeInteger(value.total_count) ||
    value.processed_count > value.total_count ||
    !isNonNegativeInteger(value.attempt) ||
    !isPositiveInteger(value.max_attempts) ||
    value.attempt > value.max_attempts ||
    typeof value.cancellation_requested !== 'boolean' ||
    !isErrorCode(value.error_code) ||
    typeof value.error_retryable !== 'boolean' ||
    typeof value.can_cancel !== 'boolean' ||
    typeof value.can_retry !== 'boolean' ||
    !isIsoTimestamp(value.created_at)
  ) {
    return null;
  }

  return {
    jobId: value.job_id,
    sequence: value.sequence,
    eventType: value.event_type,
    state: value.state,
    stage: value.stage,
    processedCount: value.processed_count,
    totalCount: value.total_count,
    attempt: value.attempt,
    maxAttempts: value.max_attempts,
    cancellationRequested: value.cancellation_requested,
    errorCode: value.error_code,
    errorRetryable: value.error_retryable,
    canCancel: value.can_cancel,
    canRetry: value.can_retry,
    createdAt: value.created_at,
  };
}

export function parseJobEventJson(value: string): JobEvent | null {
  try {
    return parseJobEvent(JSON.parse(value) as unknown);
  } catch {
    return null;
  }
}

export function isTerminalJobState(state: JobState): boolean {
  return (
    state === 'completed' ||
    state === 'partial' ||
    state === 'failed_retryable' ||
    state === 'failed_terminal' ||
    state === 'cancelled'
  );
}

export function applyJobEvent(snapshot: JobSnapshot, event: JobEvent): JobSnapshot {
  if (event.jobId !== snapshot.id) return snapshot;

  return {
    ...snapshot,
    state: event.state,
    stage: event.stage,
    processedCount: event.processedCount,
    totalCount: event.totalCount,
    attempt: event.attempt,
    maxAttempts: event.maxAttempts,
    cancellationRequested: event.cancellationRequested,
    errorCode: event.errorCode,
    errorRetryable: event.errorRetryable,
    canCancel: event.canCancel,
    canRetry: event.canRetry,
    updatedAt: event.createdAt,
  };
}
