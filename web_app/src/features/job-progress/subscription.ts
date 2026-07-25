import { getJobSnapshot, isTerminalJobState, parseJobEventJson } from '../../entities/job';
import type { JobSnapshot } from '../../entities/job';
import type { ApiError, ApiResult } from '../../shared/api/client';

import {
  createInitialJobStreamState,
  reduceJobStream,
  type JobConnectionPhase,
  type JobStreamAction,
  type JobStreamState,
} from './model';

export type JobEventSource = Pick<
  EventSource,
  'addEventListener' | 'removeEventListener' | 'close' | 'onopen' | 'onerror'
>;

export type JobEventSourceFactory = (url: string) => JobEventSource;
export type JobSnapshotLoader = (
  jobId: string,
  signal: AbortSignal,
) => Promise<ApiResult<JobSnapshot>>;

export type JobSubscriptionScheduler = Readonly<{
  schedule: (callback: () => void, delayMs: number) => unknown;
  cancel: (handle: unknown) => void;
}>;

export type JobSubscription = Readonly<{
  start: () => Promise<void>;
  refresh: () => Promise<void>;
  getState: () => JobStreamState;
  dispose: () => void;
}>;

export type JobSubscriptionOptions = Readonly<{
  jobId: string;
  onState: (state: JobStreamState) => void;
  loadSnapshot?: JobSnapshotLoader;
  eventSourceFactory?: JobEventSourceFactory;
  scheduler?: JobSubscriptionScheduler;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  pollingIntervalMs?: number;
}>;

const browserScheduler: JobSubscriptionScheduler = {
  schedule: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  cancel: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

const accessErrorCodes = new Set([
  'access_required',
  'access_expired',
  'session_expired',
  'invalid_session',
]);

export function exponentialBackoffMs(attempt: number, baseMs = 1_000, maximumMs = 30_000): number {
  const safeAttempt = Math.max(0, Math.floor(attempt));
  const safeBase = Math.max(1, Math.floor(baseMs));
  const safeMaximum = Math.max(safeBase, Math.floor(maximumMs));
  return Math.min(safeMaximum, safeBase * 2 ** Math.min(safeAttempt, 30));
}

function defaultEventSourceFactory(url: string): JobEventSource {
  return new EventSource(url, { withCredentials: true });
}

function eventsUrl(jobId: string, lastSequence: number): string {
  const path = `/events/jobs/${encodeURIComponent(jobId)}`;
  return lastSequence > 0 ? `${path}?after=${lastSequence}` : path;
}

function localTransportError(code: string, message: string): ApiError {
  return {
    code,
    message,
    retryable: true,
    requestId: crypto.randomUUID(),
  };
}

function connectionForError(error: ApiError): JobConnectionPhase {
  return accessErrorCodes.has(error.code) ? 'access-expired' : 'error';
}

export function createJobSubscription(options: JobSubscriptionOptions): JobSubscription {
  const loadSnapshot = options.loadSnapshot ?? getJobSnapshot;
  const eventSourceFactory = options.eventSourceFactory ?? defaultEventSourceFactory;
  const scheduler = options.scheduler ?? browserScheduler;
  const baseBackoffMs = options.baseBackoffMs ?? 1_000;
  const maxBackoffMs = options.maxBackoffMs ?? 30_000;
  const pollingIntervalMs = options.pollingIntervalMs ?? 5_000;

  let state = createInitialJobStreamState(options.jobId);
  let source: JobEventSource | null = null;
  let sourceListener: EventListener | null = null;
  let requestController: AbortController | null = null;
  let scheduledPoll: unknown | null = null;
  let failureAttempt = 0;
  let started = false;
  let disposed = false;
  let pollingOnly = false;

  function dispatch(action: JobStreamAction): void {
    if (disposed) return;
    const next = reduceJobStream(state, action);
    if (next === state) return;
    state = next;
    options.onState(state);
  }

  function clearScheduledPoll(): void {
    if (scheduledPoll === null) return;
    scheduler.cancel(scheduledPoll);
    scheduledPoll = null;
  }

  function closeSource(): void {
    if (source === null) return;
    if (sourceListener !== null) source.removeEventListener('job', sourceListener);
    sourceListener = null;
    source.onopen = null;
    source.onerror = null;
    source.close();
    source = null;
  }

  function settleIfTerminal(): boolean {
    if (state.snapshot === null || !isTerminalJobState(state.snapshot.state)) return false;
    closeSource();
    clearScheduledPoll();
    dispatch({ type: 'connection', connection: 'settled' });
    return true;
  }

  function schedulePoll(delayMs: number): void {
    if (disposed || settleIfTerminal()) return;
    clearScheduledPoll();
    scheduledPoll = scheduler.schedule(() => {
      scheduledPoll = null;
      void pollAndReconnect();
    }, delayMs);
  }

  function enterPolling(error: ApiError, disableSse = false): void {
    if (disposed) return;
    closeSource();
    pollingOnly ||= disableSse;
    dispatch({ type: 'transport-error', error, connection: 'polling' });
    const delay = exponentialBackoffMs(failureAttempt, baseBackoffMs, maxBackoffMs);
    failureAttempt += 1;
    schedulePoll(delay);
  }

  function connectEventSource(): void {
    if (disposed || pollingOnly || settleIfTerminal()) return;
    closeSource();

    try {
      const nextSource = eventSourceFactory(eventsUrl(options.jobId, state.lastSequence));
      source = nextSource;
      nextSource.onopen = () => {
        if (disposed || source !== nextSource) return;
        failureAttempt = 0;
        dispatch({ type: 'connection', connection: 'live' });
      };
      nextSource.onerror = () => {
        if (disposed || source !== nextSource) return;
        enterPolling(
          localTransportError('event_stream_disconnected', 'The live job stream was disconnected.'),
        );
      };
      const onJobEvent: EventListener = (event) => {
        if (disposed || source !== nextSource || !(event instanceof MessageEvent)) return;
        const parsed = parseJobEventJson(String(event.data));
        if (parsed === null) {
          enterPolling(
            localTransportError('invalid_job_event', 'The server returned an invalid job event.'),
            true,
          );
          return;
        }
        dispatch({ type: 'event', event: parsed });
        settleIfTerminal();
      };
      sourceListener = onJobEvent;
      nextSource.addEventListener('job', onJobEvent);
    } catch {
      enterPolling(
        localTransportError('event_stream_unavailable', 'The live job stream is unavailable.'),
      );
    }
  }

  async function readSnapshot(): Promise<ApiResult<JobSnapshot> | null> {
    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    const result = await loadSnapshot(options.jobId, controller.signal);
    if (disposed || controller.signal.aborted || requestController !== controller) return null;
    requestController = null;
    return result;
  }

  async function pollAndReconnect(): Promise<void> {
    const result = await readSnapshot();
    if (result === null) return;
    if (!result.ok) {
      const connection = connectionForError(result.error);
      dispatch({ type: 'transport-error', error: result.error, connection });
      if (connection === 'access-expired' || !result.error.retryable) return;
      schedulePoll(exponentialBackoffMs(failureAttempt++, baseBackoffMs, maxBackoffMs));
      return;
    }

    dispatch({ type: 'snapshot', snapshot: result.value });
    if (settleIfTerminal()) return;
    dispatch({ type: 'connection', connection: 'polling' });
    if (pollingOnly) {
      schedulePoll(pollingIntervalMs);
    } else {
      connectEventSource();
    }
  }

  async function refresh(): Promise<void> {
    if (disposed) return;
    clearScheduledPoll();
    const result = await readSnapshot();
    if (result === null) return;
    if (!result.ok) {
      const connection = connectionForError(result.error);
      dispatch({ type: 'transport-error', error: result.error, connection });
      if (result.error.retryable && connection !== 'access-expired') {
        schedulePoll(exponentialBackoffMs(failureAttempt++, baseBackoffMs, maxBackoffMs));
      }
      return;
    }

    dispatch({ type: 'snapshot', snapshot: result.value });
    if (!settleIfTerminal()) connectEventSource();
  }

  async function start(): Promise<void> {
    if (disposed || started) return;
    started = true;
    options.onState(state);
    await refresh();
  }

  function dispose(): void {
    if (disposed) return;
    disposed = true;
    requestController?.abort();
    requestController = null;
    clearScheduledPoll();
    closeSource();
  }

  return { start, refresh, getState: () => state, dispose };
}
