import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { cancelJob, retryJob, type JobStage } from '@entities/job';
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
    description: 'Проверка и нормализация изображения',
    stages: ['queued', 'uploading', 'validating', 'preprocessing'],
  },
  {
    id: 2,
    title: 'Поиск строк',
    description: 'CRAFT определяет текстовые области',
    stages: ['detecting_regions', 'awaiting_region_review'],
  },
  {
    id: 3,
    title: 'Распознавание',
    description: 'TrOCR обрабатывает подтверждённые строки',
    stages: ['recognizing_lines'],
  },
  {
    id: 4,
    title: 'Сборка текста',
    description: 'Строки объединяются в страницу',
    stages: ['assembling', 'suggesting'],
  },
  {
    id: 5,
    title: 'Результат',
    description: 'Текст готов к проверке',
    stages: ['ready_for_review', 'completed'],
  },
] as const;

function connectionPresentation(connection: JobStreamState['connection'] | undefined) {
  switch (connection) {
    case 'live':
      return { tone: 'success' as const, label: 'Обновляется в реальном времени' };
    case 'polling':
      return { tone: 'warning' as const, label: 'Резервное обновление' };
    case 'settled':
      return { tone: 'success' as const, label: 'Обработка завершена' };
    case 'access-expired':
      return { tone: 'danger' as const, label: 'Сессия истекла' };
    case 'error':
      return { tone: 'danger' as const, label: 'Нет связи с сервером' };
    default:
      return { tone: 'neutral' as const, label: 'Получаем состояние…' };
  }
}

export default function ProcessingRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { csrfToken, reconnect } = useAccess();
  const jobId = searchParams.get('jobId');
  const [streamState, setStreamState] = useState<JobStreamState | null>(null);
  const [action, setAction] = useState<'cancel' | 'retry' | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    const subscription = createJobSubscription({ jobId, onState: setStreamState });
    void subscription.start();
    return () => subscription.dispose();
  }, [jobId]);

  const snapshot = streamState?.snapshot ?? null;
  const projection = useMemo(
    () => (snapshot ? projectJobProgress(snapshot) : null),
    [snapshot],
  );

  useEffect(() => {
    if (!jobId || !snapshot) return;
    const hasResult =
      snapshot.state === 'completed' ||
      snapshot.stage === 'completed' ||
      snapshot.stage === 'ready_for_review';
    if (!hasResult) return;
    const timer = window.setTimeout(() => {
      navigate(`/result?jobId=${encodeURIComponent(jobId)}`, { replace: true });
    }, 900);
    return () => window.clearTimeout(timer);
  }, [jobId, navigate, snapshot]);

  async function ensureCsrf(): Promise<string | null> {
    if (csrfToken) return csrfToken;
    await reconnect();
    setMessage('Сессия обновляется. Повторите действие через несколько секунд.');
    return null;
  }

  async function handleCancel() {
    if (!jobId) return;
    const token = await ensureCsrf();
    if (!token) return;
    setAction('cancel');
    setMessage(null);
    const response = await cancelJob(jobId, token);
    setAction(null);
    if (!response.ok) setMessage(response.error.message);
  }

  async function handleRetry() {
    if (!jobId) return;
    const token = await ensureCsrf();
    if (!token) return;
    setAction('retry');
    setMessage(null);
    const response = await retryJob(jobId, token);
    setAction(null);
    if (!response.ok) setMessage(response.error.message);
  }

  if (!jobId) {
    return (
      <main className="processing-page processing-page--missing" id="main-content" tabIndex={-1}>
        <Card className="processing-card processing-card--empty">
          <span className="processing-hero-icon" aria-hidden="true">
            <Icon name="sparkles" />
          </span>
          <p className="eyebrow">Обработка</p>
          <h1>Не указана задача распознавания</h1>
          <p>
            Этот экран не запускает демонстрацию. Создайте документ и подтвердите области,
            чтобы сервер вернул настоящий идентификатор задачи.
          </p>
          <Link className="ui-button ui-button--primary" to="/capture">
            Добавить страницу
          </Link>
        </Card>
      </main>
    );
  }

  const isCompleted =
    snapshot?.state === 'completed' ||
    snapshot?.stage === 'completed' ||
    snapshot?.stage === 'ready_for_review';
  const progressPercent = projection?.progressPercent ?? (isCompleted ? 100 : null);
  const connection = connectionPresentation(streamState?.connection);

  return (
    <main className="processing-page" id="main-content" tabIndex={-1}>
      <Card className="processing-card">
        <span className="processing-hero-icon" aria-hidden="true">
          {projection?.isTerminal ? <Icon name="shield" /> : <span className="ui-spinner" />}
        </span>
        <Badge tone={connection.tone}>{connection.label}</Badge>
        <h1>{projection?.stageLabel ?? 'Подключаемся к задаче…'}</h1>
        <p className="processing-card__lead">
          Можно уйти с этой страницы. Обработка продолжится на сервере.
        </p>

        <div className="processing-progress-section">
          <div className="processing-progress-header">
            <span>Прогресс по данным сервера</span>
            <span className="processing-progress-percent">
              {progressPercent === null ? '—' : `${progressPercent}%`}
            </span>
          </div>
          <div
            className={`processing-progress-track ${
              progressPercent === null ? 'processing-progress-track--indeterminate' : ''
            }`}
            role="progressbar"
            aria-valuenow={progressPercent ?? undefined}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Прогресс обработки документа"
          >
            <div
              className="processing-progress-fill"
              style={progressPercent === null ? undefined : { width: `${progressPercent}%` }}
            />
          </div>
        </div>

        <Status
          tone={
            projection?.error
              ? 'danger'
              : projection?.isPartial
                ? 'warning'
                : isCompleted
                  ? 'success'
                  : 'info'
          }
        >
          {projection?.error
            ? `Сервер сообщил об ошибке: ${projection.error.code}`
            : projection?.counterLabel ?? 'Ожидаем данные сервера'}
        </Status>

        {projection?.isPartial ? (
          <p className="ui-status ui-status--warning" role="status">
            Часть результата уже сохранена. Сервер отмечает задачу как частично выполненную.
          </p>
        ) : null}
        {snapshot?.state === 'cancelled' ? (
          <p className="ui-status ui-status--warning" role="status">
            Обработка отменена. Загруженная страница осталась в документе.
          </p>
        ) : null}
        {streamState?.transportError ? (
          <p className="ui-field__error" role="alert">
            {streamState.transportError.message}
          </p>
        ) : null}
        {message ? (
          <p className="ui-field__error" role="alert">
            {message}
          </p>
        ) : null}

        <div className="processing-actions">
          <Link className="ui-button ui-button--secondary" to="/documents">
            Вернуться к документам
          </Link>
          {projection?.canCancel ? (
            <Button
              variant="danger"
              isLoading={action === 'cancel'}
              disabled={action !== null}
              onClick={() => void handleCancel()}
            >
              Отменить обработку
            </Button>
          ) : null}
          {projection?.canRetry ? (
            <Button
              variant="primary"
              isLoading={action === 'retry'}
              disabled={action !== null}
              onClick={() => void handleRetry()}
            >
              Повторить задачу
            </Button>
          ) : null}
        </div>
      </Card>
    </main>
  );
}
