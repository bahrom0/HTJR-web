import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { cancelJob, retryJob } from '@entities/job';
import { getPreparation } from '@features/preparation/api';
import type { PreparationAsset } from '@features/preparation/model';
import { getRegions } from '@features/regions/api';
import type { Region } from '@features/regions/model';
import {
  createJobSubscription,
  projectJobProgress,
  type JobStreamState,
} from '@features/job-progress';
import { useAccess } from '@shared/access/AccessProvider';
import { Button, Card, Icon } from '@shared/ui';

type ProcessingVisual = Readonly<{
  pageId: string;
  asset: PreparationAsset;
  regions: readonly Region[];
}>;

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

function regionBounds(region: Region) {
  const xs = region.polygon.map((point) => point.x);
  const ys = region.polygon.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    x: minX,
    y: minY,
    width: Math.max(0.000001, maxX - minX),
    height: Math.max(0.000001, maxY - minY),
  };
}

export default function ProcessingRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { csrfToken, reconnect } = useAccess();
  const jobId = searchParams.get('jobId');
  const [streamState, setStreamState] = useState<JobStreamState | null>(null);
  const [visual, setVisual] = useState<ProcessingVisual | null>(null);
  const [visualError, setVisualError] = useState<string | null>(null);
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
    if (!snapshot?.pageId) return;
    const controller = new AbortController();
    void Promise.all([
      getPreparation(snapshot.pageId, controller.signal),
      getRegions(snapshot.pageId, controller.signal),
    ]).then(([preparation, regions]) => {
      if (controller.signal.aborted) return;
      if (!preparation.ok || !regions.ok) {
        setVisual(null);
        setVisualError('Не удалось загрузить фрагмент страницы для этого шага.');
        return;
      }
      setVisual({
        pageId: snapshot.pageId,
        asset: preparation.value.preparedAsset ?? preparation.value.sourceAsset,
        regions: regions.value.regions,
      });
      setVisualError(null);
    });
    return () => controller.abort();
  }, [snapshot?.pageId]);

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
            Этот экран показывает только настоящую серверную задачу. Создайте документ и
            подтвердите области, чтобы перейти к распознаванию.
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
  const currentVisual = visual?.pageId === snapshot?.pageId ? visual : null;
  const activeRegionIndex =
    currentVisual && currentVisual.regions.length > 0
      ? Math.min(Math.max(snapshot?.processedCount ?? 0, 0), currentVisual.regions.length - 1)
      : null;
  const activeRegion = activeRegionIndex === null ? null : currentVisual?.regions[activeRegionIndex] ?? null;
  const crop = activeRegion ? regionBounds(activeRegion) : null;
  const cropAspectRatio =
    currentVisual && crop
      ? (crop.width * currentVisual.asset.width) /
        (crop.height * currentVisual.asset.height)
      : null;
  const currentLine = activeRegionIndex === null ? null : activeRegionIndex + 1;
  const totalLines = currentVisual?.regions.length ?? snapshot?.totalCount ?? 0;
  const visualKey = activeRegion ? `${activeRegion.id}:${snapshot?.processedCount ?? 0}` : 'pending';
  const progressStyle =
    progressPercent === null
      ? undefined
      : ({ '--processing-progress': `${progressPercent * 3.6}deg` } as CSSProperties);
  const isRecognizing = projection?.stage === 'recognizing_lines';

  return (
    <main className="processing-page processing-page--lens" id="main-content" tabIndex={-1}>
      <header className="processing-lens-heading">
        <p className="processing-lens-kicker">РАСПОЗНАВАНИЕ РУКОПИСНОГО ТАДЖИКСКОГО ТЕКСТА</p>
        <h1>{isRecognizing ? 'Обрабатываем рукописный текст' : projection?.stageLabel ?? 'Подключаемся к задаче'}</h1>
        <p>Искусственный интеллект распознаёт символы и сохраняет структуру оригинала.</p>
      </header>

      <section className="processing-lens-stage" aria-label="Ход распознавания">
        <div className="processing-lens-step">
          {currentLine && totalLines > 0 ? `СТРОКА ${currentLine} ИЗ ${totalLines}` : projection?.stageLabel ?? 'ПОДГОТОВКА'}
        </div>
        <span className="processing-lens-live-dot" aria-hidden="true" />

        <div className="processing-lens-source" aria-live="polite">
          {currentVisual && crop ? (
            <div
              className="processing-lens-crop"
              style={{ aspectRatio: cropAspectRatio ?? undefined }}
            >
              <img
                key={visualKey}
                className="processing-lens-crop__image"
                src={currentVisual.asset.previewUrl}
                alt={`Фрагмент строки ${currentLine ?? ''} из обрабатываемого документа`}
                draggable={false}
                style={{
                  width: `${100 / crop.width}%`,
                  left: `-${(crop.x / crop.width) * 100}%`,
                  top: `-${(crop.y / crop.height) * 100}%`,
                }}
              />
              <span className="processing-lens-scanline" aria-hidden="true" />
            </div>
          ) : (
            <div className="processing-lens-crop processing-lens-crop--loading" aria-label="Загружаем фрагмент документа">
              <span className="processing-lens-scanline" aria-hidden="true" />
            </div>
          )}
        </div>

        <span className="processing-lens-transfer" aria-hidden="true" />

        <div className="processing-lens-text" aria-live="polite">
          <span className="processing-lens-text__cursor" aria-hidden="true" />
          {isRecognizing && currentLine
            ? `Распознаём символы строки ${currentLine}…`
            : projection?.error
              ? `Сервер сообщил об ошибке: ${projection.error.code}`
              : projection?.stageLabel ?? 'Получаем состояние задачи…'}
        </div>

        <div
          className={`processing-lens-progress ${
            progressPercent === null ? 'processing-lens-progress--indeterminate' : ''
          }`}
          style={progressStyle}
          role="progressbar"
          aria-valuenow={progressPercent ?? undefined}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Прогресс распознавания документа"
        >
          <div className="processing-lens-progress__inner">
            <strong>{progressPercent === null ? '—' : `${progressPercent}%`}</strong>
            <span>{projection?.counterLabel ?? 'Считаем строки…'}</span>
          </div>
        </div>

        <p className="processing-lens-status">
          {projection?.error
            ? 'Распознавание остановлено: ознакомьтесь с сообщением ниже.'
            : isCompleted
              ? 'Результат готов. Открываем текст…'
              : isRecognizing
                ? 'Распознаём текст…'
                : `${projection?.stageLabel ?? 'Получаем состояние'}…`}
        </p>

        <footer className="processing-lens-footer">
          <Icon name="clock" />
          <span>{connectionLabel(streamState?.connection)}. Можно закрыть страницу и вернуться позже.</span>
        </footer>
      </section>

      {visualError || streamState?.transportError || message || projection?.isPartial || snapshot?.state === 'cancelled' ? (
        <section className="processing-lens-notice" aria-live="polite">
          {visualError ??
            streamState?.transportError?.message ??
            message ??
            (projection?.isPartial
              ? 'Часть результата уже сохранена на сервере.'
              : 'Обработка отменена. Загруженная страница сохранена в документе.')}
        </section>
      ) : null}

      <nav className="processing-actions processing-actions--lens" aria-label="Действия с задачей">
        <Link className="ui-button ui-button--secondary" to="/documents">
          К документам
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
      </nav>
    </main>
  );
}
