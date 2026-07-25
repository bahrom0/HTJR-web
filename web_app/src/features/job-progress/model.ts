import type { ApiError } from '../../shared/api/client';
import {
  applyJobEvent,
  isTerminalJobState,
  type JobEvent,
  type JobSnapshot,
  type JobStage,
} from '../../entities/job';

export type JobConnectionPhase =
  | 'loading'
  | 'live'
  | 'polling'
  | 'settled'
  | 'access-expired'
  | 'error';

export type JobStreamState = Readonly<{
  jobId: string;
  snapshot: JobSnapshot | null;
  lastSequence: number;
  connection: JobConnectionPhase;
  transportError: ApiError | null;
}>;

export type JobStreamAction =
  | Readonly<{ type: 'snapshot'; snapshot: JobSnapshot }>
  | Readonly<{ type: 'event'; event: JobEvent }>
  | Readonly<{ type: 'connection'; connection: JobConnectionPhase }>
  | Readonly<{ type: 'transport-error'; error: ApiError; connection: JobConnectionPhase }>;

export type JobProgressProjection = Readonly<{
  stage: JobStage;
  stageLabel: string;
  processedCount: number;
  totalCount: number;
  counterLabel: string | null;
  progressRatio: number | null;
  progressPercent: number | null;
  error: Readonly<{ code: string; retryable: boolean }> | null;
  canCancel: boolean;
  cancellationRequested: boolean;
  canRetry: boolean;
  isPartial: boolean;
  isTerminal: boolean;
}>;

const stageLabels: Readonly<Record<JobStage, string>> = {
  queued: 'В очереди',
  uploading: 'Загрузка',
  validating: 'Проверка файла',
  preprocessing: 'Подготовка изображения',
  detecting_regions: 'Поиск строк',
  awaiting_region_review: 'Проверка областей',
  recognizing_lines: 'Распознавание строк',
  assembling: 'Сборка страницы',
  suggesting: 'Подготовка подсказок',
  ready_for_review: 'Готово к проверке',
  completed: 'Завершено',
};

export function createInitialJobStreamState(jobId: string): JobStreamState {
  return {
    jobId,
    snapshot: null,
    lastSequence: 0,
    connection: 'loading',
    transportError: null,
  };
}

function shouldAcceptSnapshot(current: JobSnapshot | null, next: JobSnapshot): boolean {
  if (current === null) return true;
  if (next.revision !== current.revision) return next.revision > current.revision;
  return Date.parse(next.updatedAt) >= Date.parse(current.updatedAt);
}

export function reduceJobStream(state: JobStreamState, action: JobStreamAction): JobStreamState {
  switch (action.type) {
    case 'snapshot': {
      if (
        action.snapshot.id !== state.jobId ||
        !shouldAcceptSnapshot(state.snapshot, action.snapshot)
      ) {
        return state;
      }
      return { ...state, snapshot: action.snapshot, transportError: null };
    }
    case 'event': {
      if (action.event.jobId !== state.jobId || action.event.sequence <= state.lastSequence) {
        return state;
      }
      if (state.snapshot === null) {
        return { ...state, lastSequence: action.event.sequence };
      }

      // A fresh tab first reads the latest snapshot and then resumes the append-only
      // stream. Replayed events older than that snapshot advance the cursor without
      // temporarily rolling truthful server state backwards.
      const snapshot =
        Date.parse(action.event.createdAt) < Date.parse(state.snapshot.updatedAt)
          ? state.snapshot
          : applyJobEvent(state.snapshot, action.event);
      return {
        ...state,
        snapshot,
        lastSequence: action.event.sequence,
        transportError: null,
      };
    }
    case 'connection':
      return state.connection === action.connection && state.transportError === null
        ? state
        : { ...state, connection: action.connection, transportError: null };
    case 'transport-error':
      return { ...state, connection: action.connection, transportError: action.error };
  }
}

export function projectJobProgress(snapshot: JobSnapshot): JobProgressProjection {
  const hasMeasuredTotal = snapshot.totalCount > 0;
  const progressRatio = hasMeasuredTotal ? snapshot.processedCount / snapshot.totalCount : null;

  return {
    stage: snapshot.stage,
    stageLabel: stageLabels[snapshot.stage],
    processedCount: snapshot.processedCount,
    totalCount: snapshot.totalCount,
    counterLabel: hasMeasuredTotal ? `${snapshot.processedCount} из ${snapshot.totalCount}` : null,
    progressRatio,
    progressPercent: progressRatio === null ? null : Math.round(progressRatio * 100),
    error:
      snapshot.errorCode === null
        ? null
        : { code: snapshot.errorCode, retryable: snapshot.errorRetryable },
    canCancel: snapshot.canCancel,
    cancellationRequested: snapshot.cancellationRequested,
    canRetry: snapshot.canRetry,
    isPartial: snapshot.state === 'partial',
    isTerminal: isTerminalJobState(snapshot.state),
  };
}
