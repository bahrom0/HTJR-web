import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { cancelJob, type JobSnapshot, type JobStage } from '@entities/job';
import {
  createJobSubscription,
  projectJobProgress,
  type JobStreamState,
} from '@features/job-progress';
import { useAccess } from '@shared/access/AccessProvider';
import { Badge, Button, Card, Icon, Status } from '@shared/ui';

export type PipelineStep = Readonly<{
  id: number;
  title: string;
  description: string;
  stages: readonly JobStage[];
}>;

export const PROCESSING_STEPS: readonly PipelineStep[] = [
  {
    id: 1,
    title: 'Подготовка',
    description: 'Загрузка, валидация и очередь',
    stages: ['queued', 'uploading', 'validating', 'preprocessing'],
  },
  {
    id: 2,
    title: 'Поиск строк',
    description: 'Детекция текстовых областей',
    stages: ['detecting_regions'],
  },
  {
    id: 3,
    title: 'Распознавание',
    description: 'Распознавание рукописных строк',
    stages: ['recognizing_lines', 'awaiting_region_review'],
  },
  {
    id: 4,
    title: 'Проверка символов',
    description: 'Анализ и подготовка подсказок',
    stages: ['suggesting', 'ready_for_review'],
  },
  {
    id: 5,
    title: 'Сборка',
    description: 'Сборка структуры страницы',
    stages: ['assembling'],
  },
  {
    id: 6,
    title: 'Сохранение',
    description: 'Финализация результатов',
    stages: ['completed'],
  },
] as const;

function getActiveStepIndex(stage: JobStage | undefined): number {
  if (!stage) return 0;
  for (let i = 0; i < PROCESSING_STEPS.length; i++) {
    if ((PROCESSING_STEPS[i].stages as readonly string[]).includes(stage)) {
      return i;
    }
  }
  return 0;
}

const MOCK_TIMELINE: Array<{ stage: JobStage; processed: number; total: number }> = [
  { stage: 'preprocessing', processed: 0, total: 24 },
  { stage: 'detecting_regions', processed: 5, total: 24 },
  { stage: 'recognizing_lines', processed: 12, total: 24 },
  { stage: 'suggesting', processed: 18, total: 24 },
  { stage: 'assembling', processed: 22, total: 24 },
  { stage: 'completed', processed: 24, total: 24 },
];

function createInitialMockSnapshot(): JobSnapshot {
  return {
    id: 'demo-job-123',
    documentId: 'doc-demo-1',
    pageId: 'page-demo-1',
    state: 'running',
    stage: 'preprocessing',
    priority: 1,
    processedCount: 0,
    totalCount: 24,
    attempt: 1,
    maxAttempts: 3,
    cancellationRequested: false,
    errorCode: null,
    errorRetryable: false,
    canCancel: true,
    canRetry: false,
    revision: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    duplicate: false,
  };
}

export default function ProcessingRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { csrfToken, reconnect } = useAccess();
  const jobId = searchParams.get('jobId');

  const [streamState, setStreamState] = useState<JobStreamState | null>(null);
  const [mockSnapshot, setMockSnapshot] = useState<JobSnapshot | null>(
    jobId ? null : createInitialMockSnapshot(),
  );
  const [mockIndex, setMockIndex] = useState(0);
  const [isCanceling, setIsCanceling] = useState(false);
  const [cancelMessage, setCancelMessage] = useState<string | null>(null);

  // Real server subscription when jobId is present
  useEffect(() => {
    if (!jobId) return;

    const sub = createJobSubscription({
      jobId,
      onState: (nextState) => {
        setStreamState(nextState);
      },
    });

    void sub.start();

    return () => {
      sub.dispose();
    };
  }, [jobId]);

  // Emulation interval when jobId is missing
  useEffect(() => {
    if (jobId) return;

    const interval = window.setInterval(() => {
      setMockIndex((current) => {
        const nextIndex = current + 1;
        if (nextIndex >= MOCK_TIMELINE.length) {
          window.clearInterval(interval);
          return current;
        }
        const step = MOCK_TIMELINE[nextIndex];
        const isDone = step.stage === 'completed';
        setMockSnapshot({
          id: 'demo-job-123',
          documentId: 'doc-demo-1',
          pageId: 'page-demo-1',
          state: isDone ? 'completed' : 'running',
          stage: step.stage,
          priority: 1,
          processedCount: step.processed,
          totalCount: step.total,
          attempt: 1,
          maxAttempts: 3,
          cancellationRequested: false,
          errorCode: null,
          errorRetryable: false,
          canCancel: !isDone,
          canRetry: false,
          revision: nextIndex + 1,
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          duplicate: false,
        });
        return nextIndex;
      });
    }, 2000);

    return () => window.clearInterval(interval);
  }, [jobId]);

  const activeSnapshot: JobSnapshot | null = jobId ? (streamState?.snapshot ?? null) : mockSnapshot;

  const projection = useMemo(() => {
    return activeSnapshot ? projectJobProgress(activeSnapshot) : null;
  }, [activeSnapshot]);

  // Auto-redirect on completion
  useEffect(() => {
    if (!activeSnapshot) return;

    const isFinished =
      activeSnapshot.state === 'completed' ||
      activeSnapshot.state === 'ready_for_review' ||
      activeSnapshot.stage === 'completed' ||
      activeSnapshot.stage === 'ready_for_review';

    if (isFinished) {
      const redirectJobId = jobId || activeSnapshot.id;
      const timer = window.setTimeout(() => {
        navigate(`/result?jobId=${encodeURIComponent(redirectJobId)}`);
      }, 1200);
      return () => window.clearTimeout(timer);
    }
  }, [activeSnapshot, jobId, navigate]);

  const activeStepIndex = getActiveStepIndex(activeSnapshot?.stage);
  const isCompletedState =
    activeSnapshot?.state === 'completed' || activeSnapshot?.stage === 'completed';

  const progressPercent = useMemo(() => {
    if (projection?.progressPercent !== null && projection?.progressPercent !== undefined) {
      return projection.progressPercent;
    }
    if (isCompletedState) return 100;
    if (!activeSnapshot) return 0;
    return Math.round(((activeStepIndex + 0.5) / PROCESSING_STEPS.length) * 100);
  }, [projection, activeSnapshot, isCompletedState, activeStepIndex]);

  const counterText =
    projection?.counterLabel ??
    (activeSnapshot?.totalCount
      ? `${activeSnapshot.processedCount} из ${activeSnapshot.totalCount}`
      : null);

  async function handleCancel() {
    if (!jobId) {
      // In emulation mode, update mock snapshot to cancelled state
      if (mockSnapshot) {
        setMockSnapshot({
          ...mockSnapshot,
          state: 'cancelled',
          canCancel: false,
        });
      }
      return;
    }

    if (!csrfToken) {
      await reconnect();
      setCancelMessage('Сессия обновляется. Попробуйте ещё раз.');
      return;
    }

    setIsCanceling(true);
    setCancelMessage(null);

    const res = await cancelJob(jobId, csrfToken);
    setIsCanceling(false);

    if (!res.ok) {
      setCancelMessage(res.error.message);
    }
  }

  function handleRestartEmulation() {
    setMockIndex(0);
    setMockSnapshot(createInitialMockSnapshot());
  }

  const connectionBadgeTone = useMemo(() => {
    if (!jobId) return 'info';
    if (streamState?.connection === 'live') return 'success';
    if (streamState?.connection === 'polling') return 'warning';
    if (streamState?.connection === 'error' || streamState?.connection === 'access-expired')
      return 'danger';
    return 'neutral';
  }, [jobId, streamState?.connection]);

  const connectionLabel = useMemo(() => {
    if (!jobId) return 'Режим эмуляции UI';
    if (streamState?.connection === 'live') return 'SSE Live';
    if (streamState?.connection === 'polling') return 'Polling';
    if (streamState?.connection === 'settled') return 'Завершено';
    if (streamState?.connection === 'access-expired') return 'Сессия истекла';
    if (streamState?.connection === 'error') return 'Ошибка подключения';
    return 'Загрузка…';
  }, [jobId, streamState?.connection]);

  return (
    <main className="processing-page" id="main-content" tabIndex={-1}>
      <header className="page-heading processing-heading">
        <div>
          <p className="eyebrow">Автоматическая обработка</p>
          <h1>Распознавание документа Tajik HTR</h1>
          <p>
            Выполняются этапы сегментации, HTR распознавания строк и контекстного анализа символов.
          </p>
        </div>
        <Badge tone={connectionBadgeTone}>{connectionLabel}</Badge>
      </header>

      <Card className="processing-card">
        <div className="processing-status-header">
          <div className="processing-status-header__info">
            <Icon name="sparkles" />
            <Status tone={isCompletedState ? 'success' : 'info'}>
              {projection?.stageLabel ?? 'Инициализация пайплайна…'}
            </Status>
          </div>
          {counterText ? (
            <span className="processing-progress-counter">{counterText}</span>
          ) : null}
        </div>

        <div className="processing-progress-section">
          <div className="processing-progress-header">
            <span>Прогресс выполнения</span>
            <span className="processing-progress-percent">{progressPercent}%</span>
          </div>
          <div
            className="processing-progress-track"
            role="progressbar"
            aria-valuenow={progressPercent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Прогресс обработки документа"
          >
            <div
              className="processing-progress-fill"
              style={{ width: `${Math.min(100, Math.max(0, progressPercent))}%` }}
            />
          </div>
        </div>

        <div className="processing-steps-grid">
          {PROCESSING_STEPS.map((step, index) => {
            const isDone = isCompletedState || index < activeStepIndex;
            const isActive = !isCompletedState && index === activeStepIndex;
            const isPending = !isCompletedState && index > activeStepIndex;

            let cardStateClass = 'processing-step-card--pending';
            if (isDone) cardStateClass = 'processing-step-card--completed';
            if (isActive) cardStateClass = 'processing-step-card--active';

            return (
              <div key={step.id} className={`processing-step-card ${cardStateClass}`}>
                <div className="processing-step-icon">
                  {isDone ? (
                    '✓'
                  ) : isActive ? (
                    <span className="ui-spinner" aria-hidden="true" />
                  ) : (
                    step.id
                  )}
                </div>
                <div className="processing-step-content">
                  <span className="processing-step-title">{step.title}</span>
                  <span className="processing-step-desc">{step.description}</span>
                </div>
              </div>
            );
          })}
        </div>

        {cancelMessage ? (
          <p className="ui-field__error" role="alert">
            {cancelMessage}
          </p>
        ) : null}

        {activeSnapshot?.state === 'cancelled' ? (
          <p className="ui-status ui-status--warning" role="status">
            Обработка была отменена пользователем.
          </p>
        ) : null}

        <div className="processing-actions">
          <Link className="ui-button ui-button--secondary" to="/">
            Работать в фоне
          </Link>

          {(projection?.canCancel ?? activeSnapshot?.canCancel ?? false) &&
          activeSnapshot?.state !== 'cancelled' ? (
            <Button
              variant="danger"
              isLoading={isCanceling}
              onClick={() => void handleCancel()}
            >
              Отменить
            </Button>
          ) : null}

          {!jobId && (isCompletedState || activeSnapshot?.state === 'cancelled') ? (
            <Button variant="quiet" onClick={handleRestartEmulation}>
              Перезапустить эмуляцию UI
            </Button>
          ) : null}
        </div>
      </Card>
    </main>
  );
}
