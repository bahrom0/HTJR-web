import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { cancelJob, retryJob } from '@entities/job';
import {
  startAutomaticRecognition,
  type AutomaticPreparationPhase,
} from '@features/preparation/automatic';
import {
  createJobSubscription,
  projectJobProgress,
  type JobStreamState,
} from '@features/job-progress';
import { useAccess } from '@shared/access/AccessProvider';
import { Button, Card, Icon } from '@shared/ui';

function connectionLabel(connection: JobStreamState['connection'] | undefined) {
  switch (connection) {
    case 'live':
      return 'Задача работает на сервере';
    case 'polling':
      return 'Получаем обновления с сервера';
    case 'settled':
      return 'Результат подготовлен';
    case 'access-expired':
      return 'Сессия требует обновления';
    case 'error':
      return 'Проверяем соединение с сервером';
    default:
      return 'Подключаемся к задаче';
  }
}

function automaticPhaseLabel(phase: AutomaticPreparationPhase) {
  switch (phase) {
    case 'quality':
      return 'Проверяем качество изображения';
    case 'confirming':
      return 'Подготавливаем страницу';
    case 'detecting':
      return 'Запускаем поиск строк Kraken';
  }
}

export default function ProcessingRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { csrfToken, reconnect } = useAccess();
  const jobId = searchParams.get('jobId');
  const pageId = searchParams.get('pageId');
  const shouldStartAutomatically = searchParams.get('auto') === '1';
  const [streamState, setStreamState] = useState<JobStreamState | null>(null);
  const [action, setAction] = useState<'cancel' | 'retry' | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [bootstrapPhase, setBootstrapPhase] = useState<AutomaticPreparationPhase>('quality');
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);

  useEffect(() => {
    if (jobId || !pageId || !shouldStartAutomatically) return;
    if (!csrfToken) {
      void reconnect();
      return;
    }
    const controller = new AbortController();
    void startAutomaticRecognition(pageId, csrfToken, {
      signal: controller.signal,
      onPhase: setBootstrapPhase,
    }).then((response) => {
      if (controller.signal.aborted) return;
      if (!response.ok) {
        setBootstrapError(response.error.message);
        return;
      }
      navigate(
        `/processing?pageId=${encodeURIComponent(pageId)}&jobId=${encodeURIComponent(response.value.id)}`,
        { replace: true },
      );
    });
    return () => controller.abort();
  }, [bootstrapAttempt, csrfToken, jobId, navigate, pageId, reconnect, shouldStartAutomatically]);

  useEffect(() => {
    if (!jobId) return;
    const subscription = createJobSubscription({ jobId, onState: setStreamState });
    void subscription.start();
    return () => subscription.dispose();
  }, [jobId]);

  const snapshot = streamState?.snapshot ?? null;
  const projection = useMemo(() => (snapshot ? projectJobProgress(snapshot) : null), [snapshot]);

  useEffect(() => {
    if (!jobId || !snapshot) return;
    const awaitsRegionReview =
      snapshot.state === 'awaiting_region_review' || snapshot.stage === 'awaiting_region_review';
    if (awaitsRegionReview) {
      const timer = window.setTimeout(() => {
        navigate(
          `/regions?pageId=${encodeURIComponent(snapshot.pageId)}&jobId=${encodeURIComponent(jobId)}`,
          { replace: true },
        );
      }, 650);
      return () => window.clearTimeout(timer);
    }
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

  const isCompleted =
    snapshot?.state === 'completed' ||
    snapshot?.stage === 'completed' ||
    snapshot?.stage === 'ready_for_review';
  const activePhase: AutomaticPreparationPhase =
    projection?.stage === 'preprocessing'
      ? 'confirming'
      : projection && ['queued', 'uploading', 'validating'].includes(projection.stage)
        ? 'quality'
        : projection
          ? 'detecting'
          : bootstrapPhase;
  const activeLabel = projection?.stageLabel ?? automaticPhaseLabel(activePhase);
  const processingMessage = projection?.error
    ? `Сервер сообщил об ошибке: ${projection.error.code}`
    : isCompleted
      ? 'Результат готов. Открываем редактор…'
      : projection?.counterLabel
        ? `${activeLabel}. ${projection.counterLabel}`
        : jobId
          ? `${activeLabel}… ${connectionLabel(streamState?.connection)}`
          : 'Редактор откроется, когда Kraken завершит поиск строк.';
  const processingError =
    bootstrapError ??
    streamState?.transportError?.message ??
    message ??
    (projection?.isPartial
      ? 'Часть результата уже сохранена на сервере.'
      : snapshot?.state === 'cancelled'
        ? 'Обработка отменена. Загруженная страница сохранена в документе.'
        : null);

  if ((pageId && shouldStartAutomatically) || jobId) {
    return (
      <main className="processing-page processing-page--bootstrap" id="main-content" tabIndex={-1}>
        <section className="processing-bootstrap" aria-live="polite">
          <div className="processing-bootstrap__spinner" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <p className="eyebrow">Автоматическая подготовка</p>
          <h1>{activeLabel}</h1>
          <p>
            Качество страницы и расположение строк проверяются автоматически. Редактор откроется,
            когда Kraken завершит поиск.
          </p>
          <ol className="processing-bootstrap__steps" aria-label="Этапы подготовки">
            <li className={activePhase === 'quality' ? 'is-active' : 'is-done'}>Качество</li>
            <li
              className={
                activePhase === 'confirming'
                  ? 'is-active'
                  : activePhase === 'detecting'
                    ? 'is-done'
                    : ''
              }
            >
              Подготовка
            </li>
            <li className={isCompleted ? 'is-done' : activePhase === 'detecting' ? 'is-active' : ''}>
              Поиск строк
            </li>
          </ol>
          <p className="processing-bootstrap__status" aria-live="polite">
            {processingMessage}
          </p>
          {processingError ? (
            <div className="processing-bootstrap__error" role="alert">
              <p>{processingError}</p>
              <div>
                {bootstrapError ? (
                  <>
                    <Button
                      variant="primary"
                      onClick={() => {
                        setBootstrapError(null);
                        setBootstrapAttempt((value) => value + 1);
                      }}
                    >
                      Повторить
                    </Button>
                    {pageId ? (
                      <Link
                        className="ui-button ui-button--secondary"
                        to={`/preparation?pageId=${encodeURIComponent(pageId)}`}
                      >
                        Открыть ручную подготовку
                      </Link>
                    ) : null}
                  </>
                ) : projection?.canRetry ? (
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
            </div>
          ) : null}
        </section>
        {jobId && projection?.canCancel ? (
          <nav className="processing-actions processing-actions--bootstrap" aria-label="Действия с задачей">
            <Link className="ui-button ui-button--secondary" to="/documents">
              К документам
            </Link>
            <Button
              variant="danger"
              isLoading={action === 'cancel'}
              disabled={action !== null}
              onClick={() => void handleCancel()}
            >
              Отменить обработку
            </Button>
          </nav>
        ) : null}
      </main>
    );
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
            Этот экран показывает только настоящую серверную задачу. Создайте документ и подтвердите
            области, чтобы перейти к распознаванию.
          </p>
          <Link className="ui-button ui-button--primary" to="/capture">
            Добавить страницу
          </Link>
        </Card>
      </main>
    );
  }

  return null;
}
