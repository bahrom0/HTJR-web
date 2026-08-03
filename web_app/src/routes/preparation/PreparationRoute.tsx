import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { createRecognitionJob } from '@entities/job';
import { confirmPreparation, getPreparation, previewPreparation } from '@features/preparation/api';
import {
  canvasToNormalized,
  fitTransform,
  normalizedToCanvas,
  zoomTransform,
  type Transform,
} from '@features/preparation/geometry';
import {
  cloneRecipe,
  defaultPreparationRecipe,
  normalizeCrop,
  normalizePoint,
  recipeEquals,
  rotateRecipe,
  type NormalizedPoint,
  type PreparationRecipe,
  type PreparationState,
} from '@features/preparation/model';
import {
  loadPreparationDraft,
  removePreparationDraft,
  savePreparationDraft,
} from '@features/preparation/persistence';
import { useAccess } from '@shared/access/AccessProvider';
import { Button, Card } from '@shared/ui';

const initialCorners: NonNullable<PreparationRecipe['perspective']> = [
  { x: 0.04, y: 0.04 },
  { x: 0.96, y: 0.04 },
  { x: 0.96, y: 0.96 },
  { x: 0.04, y: 0.96 },
];

type CanvasPoint = Readonly<{ x: number; y: number }>;

function canvasPoint(event: React.PointerEvent<HTMLElement>): CanvasPoint {
  const box = event.currentTarget.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}

function isSameRecipe(left: PreparationRecipe, right: PreparationRecipe): boolean {
  return recipeEquals(left, right);
}

function initialView(state: PreparationState, element: HTMLElement | null): Transform {
  if (!element) return { scale: 1, offsetX: 0, offsetY: 0 };
  return fitTransform(
    { width: state.sourceAsset.width, height: state.sourceAsset.height },
    { width: element.clientWidth, height: element.clientHeight },
  );
}

function recognitionIdempotencyKey(pageId: string, revision: number): string {
  return `recognition:${pageId}:${revision}`;
}

export default function PreparationRoute() {
  const { csrfToken, reconnect } = useAccess();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const pageId = params.get('pageId');
  const viewport = useRef<HTMLDivElement>(null);
  const activePointers = useRef(new Map<number, CanvasPoint>());
  const cornerBaseline = useRef<PreparationRecipe | null>(null);
  const pan = useRef<{ start: CanvasPoint; view: Transform } | null>(null);
  const pinch = useRef<{ distance: number; center: CanvasPoint; view: Transform } | null>(null);
  const [state, setState] = useState<PreparationState | null>(null);
  const [recipe, setRecipe] = useState<PreparationRecipe>(defaultPreparationRecipe);
  const [history, setHistory] = useState<PreparationRecipe[]>([]);
  const [view, setView] = useState<Transform>({ scale: 1, offsetX: 0, offsetY: 0 });
  const [showOriginal, setShowOriginal] = useState(true);
  const [busy, setBusy] = useState<'preview' | 'confirm' | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const resetView = useCallback(
    (current: PreparationState) => {
      setView(initialView(current, viewport.current));
    },
    [setView],
  );

  const load = useCallback(async () => {
    if (!pageId) return;
    const response = await getPreparation(pageId);
    if (!response.ok) {
      setMessage(response.error.message);
      return;
    }
    const saved = await loadPreparationDraft(response.value.pageId).catch(() => null);
    const validSaved = saved?.sourceAssetId === response.value.sourceAsset.id ? saved : null;
    setState(response.value);
    setRecipe(cloneRecipe(validSaved?.recipe ?? response.value.recipe ?? defaultPreparationRecipe));
    setHistory((validSaved?.history ?? []).map(cloneRecipe));
    resetView(response.value);
  }, [pageId, resetView, setHistory, setMessage, setRecipe, setState]);

  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);

  useLayoutEffect(() => {
    if (!state || !viewport.current) return;
    const element = viewport.current;
    const observer = new ResizeObserver(() => resetView(state));
    observer.observe(element);
    return () => observer.disconnect();
  }, [resetView, state]);

  useEffect(() => {
    if (!state) return;
    void savePreparationDraft({
      pageId: state.pageId,
      sourceAssetId: state.sourceAsset.id,
      recipe,
      history,
      updatedAt: new Date().toISOString(),
    }).catch(() => setMessage('Локальное сохранение черновика недоступно в этом браузере.'));
  }, [history, recipe, state]);

  function change(next: PreparationRecipe, keepUndo = true) {
    setRecipe((current) => {
      if (isSameRecipe(current, next)) return current;
      if (keepUndo) setHistory((items) => [...items.slice(-29), cloneRecipe(current)]);
      return cloneRecipe(next);
    });
  }

  function resetRecipe() {
    change(defaultPreparationRecipe);
    if (state) resetView(state);
  }

  function removePerspective() {
    change({ ...recipe, perspective: null });
  }

  function moveCorner(index: number, location: NormalizedPoint, keepUndo: boolean) {
    const corners = recipe.perspective ?? initialCorners;
    const next: [NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint] = [
      corners[0],
      corners[1],
      corners[2],
      corners[3],
    ];
    const normalized = normalizePoint(location);
    if (index === 0) next[0] = normalized;
    if (index === 1) next[1] = normalized;
    if (index === 2) next[2] = normalized;
    if (index === 3) next[3] = normalized;
    change({ ...recipe, perspective: next }, keepUndo);
  }

  function beginPan(event: React.PointerEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = canvasPoint(event);
    activePointers.current.set(event.pointerId, point);
    if (activePointers.current.size === 1) {
      pan.current = { start: point, view };
      return;
    }
    const points = [...activePointers.current.values()];
    if (points[0] && points[1]) {
      const center = { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 };
      pinch.current = {
        distance: Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y),
        center,
        view,
      };
      pan.current = null;
    }
  }

  function movePan(event: React.PointerEvent<HTMLDivElement>) {
    const point = canvasPoint(event);
    activePointers.current.set(event.pointerId, point);
    const points = [...activePointers.current.values()];
    if (pinch.current && points[0] && points[1]) {
      const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      const center = { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 };
      const scaled = zoomTransform(
        pinch.current.view,
        distance / pinch.current.distance,
        pinch.current.center,
      );
      setView({
        ...scaled,
        offsetX: scaled.offsetX + center.x - pinch.current.center.x,
        offsetY: scaled.offsetY + center.y - pinch.current.center.y,
      });
      return;
    }
    if (!pan.current) return;
    setView({
      ...pan.current.view,
      offsetX: pan.current.view.offsetX + point.x - pan.current.start.x,
      offsetY: pan.current.view.offsetY + point.y - pan.current.start.y,
    });
  }

  function endPan(event: React.PointerEvent<HTMLDivElement>) {
    activePointers.current.delete(event.pointerId);
    if (activePointers.current.size < 2) pinch.current = null;
    if (activePointers.current.size === 0) pan.current = null;
  }

  async function preview() {
    if (!state || !csrfToken) {
      await reconnect();
      setMessage('Сессия обновляется. Повторите предпросмотр после её восстановления.');
      return;
    }
    setBusy('preview');
    setMessage(null);
    const response = await previewPreparation(state.pageId, recipe, csrfToken);
    setBusy(null);
    if (!response.ok) {
      setMessage(response.error.message);
      return;
    }
    setState(response.value);
    setRecipe(cloneRecipe(response.value.recipe ?? recipe));
    setHistory([]);
    await removePreparationDraft(response.value.pageId).catch(() => undefined);
  }

  async function confirm() {
    if (!state || !csrfToken) {
      await reconnect();
      setMessage('Сессия обновляется. Повторите подтверждение после её восстановления.');
      return;
    }
    if (!state.preparedAsset || !state.recipe || !isSameRecipe(recipe, state.recipe)) {
      setMessage('Сначала создайте серверный предпросмотр для текущего рецепта.');
      return;
    }
    setBusy('confirm');
    setMessage(null);
    const confirmation = state.confirmed
      ? { ok: true as const, value: state }
      : await confirmPreparation(state.pageId, state.revision, csrfToken);
    if (!confirmation.ok) {
      setBusy(null);
      setMessage(
        confirmation.error.code === 'revision_conflict'
          ? 'Страница была изменена. Обновите её состояние.'
          : confirmation.error.message,
      );
      return;
    }

    const confirmedState = confirmation.value;
    const job = await createRecognitionJob(
      confirmedState.pageId,
      recognitionIdempotencyKey(confirmedState.pageId, confirmedState.revision),
      csrfToken,
    );
    setBusy(null);
    if (!job.ok) {
      setState(confirmedState);
      setMessage(job.error.message);
      return;
    }

    setState(confirmedState);
    setHistory([]);
    await removePreparationDraft(confirmedState.pageId).catch(() => undefined);
    const query = new URLSearchParams({
      pageId: confirmedState.pageId,
      jobId: job.value.id,
    });
    navigate(`/regions?${query.toString()}`, { state: { recognitionJob: job.value } });
  }

  if (!pageId) {
    return (
      <main className="preparation-page" id="main-content" tabIndex={-1}>
        <Card>
          <h1>Выберите страницу</h1>
          <p>Сначала добавьте изображение в новый документ.</p>
          <Link className="ui-button ui-button--primary" to="/capture">
            Добавить страницу
          </Link>
        </Card>
      </main>
    );
  }
  if (!state) {
    return (
      <main className="preparation-page" id="main-content" tabIndex={-1}>
        <p role="status">Загружаем состояние подготовки…</p>
        {message ? <p role="alert">{message}</p> : null}
      </main>
    );
  }

  const asset = !showOriginal && state.preparedAsset ? state.preparedAsset : state.sourceAsset;
  const crop = recipe.crop;
  const cropBox = crop
    ? {
        left: view.offsetX + crop.x * asset.width * view.scale,
        top: view.offsetY + crop.y * asset.height * view.scale,
        width: crop.width * asset.width * view.scale,
        height: crop.height * asset.height * view.scale,
      }
    : null;

  return (
    <main className="preparation-page" id="main-content" tabIndex={-1}>
      <header className="page-heading preparation-heading">
        <div>
          <h1>Подготовка страницы</h1>
          <p>Проверьте поворот, края и читаемость изображения.</p>
        </div>
        <div className="preparation-heading__actions">
          <Link className="ui-button ui-button--secondary" to="/capture">
            Отмена
          </Link>
          {!state.preparedAsset || !state.recipe || !isSameRecipe(recipe, state.recipe) ? (
            <Button
              isLoading={busy === 'preview'}
              disabled={busy !== null}
              onClick={() => void preview()}
            >
              Подготовить
            </Button>
          ) : (
            <Button
              isLoading={busy === 'confirm'}
              disabled={busy !== null}
              onClick={() => void confirm()}
            >
              Найти строки
            </Button>
          )}
        </div>
      </header>
      <div className="preparation-layout">
        <section className="preparation-canvas-card" aria-label="Подготовка изображения">
          <div
            className="preparation-canvas"
            ref={viewport}
            onPointerDown={beginPan}
            onPointerMove={movePan}
            onPointerUp={endPan}
            onPointerCancel={endPan}
            onWheel={(event) => {
              event.preventDefault();
              const box = event.currentTarget.getBoundingClientRect();
              setView((current) =>
                zoomTransform(current, event.deltaY < 0 ? 1.15 : 1 / 1.15, {
                  x: event.clientX - box.left,
                  y: event.clientY - box.top,
                }),
              );
            }}
          >
            <img
              className="preparation-canvas__image"
              draggable={false}
              src={asset.previewUrl}
              alt={showOriginal ? 'Оригинальная страница' : 'Подготовленный предпросмотр'}
              style={{
                width: asset.width,
                height: asset.height,
                transform: `translate(${view.offsetX}px, ${view.offsetY}px) scale(${view.scale})`,
              }}
            />
            {cropBox ? (
              <span
                className="preparation-crop-box"
                aria-hidden="true"
                style={{
                  left: cropBox.left,
                  top: cropBox.top,
                  width: cropBox.width,
                  height: cropBox.height,
                }}
              />
            ) : null}
            {recipe.perspective?.map((corner, index) => {
              const position = normalizedToCanvas(
                corner,
                { width: asset.width, height: asset.height },
                view,
              );
              return (
                <button
                  key={index}
                  className="preparation-corner"
                  aria-label={`Угол перспективы ${index + 1}`}
                  style={{ left: position.x, top: position.y }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    cornerBaseline.current = cloneRecipe(recipe);
                    event.currentTarget.setPointerCapture(event.pointerId);
                  }}
                  onPointerMove={(event) => {
                    if (event.buttons !== 1) return;
                    const box = viewport.current?.getBoundingClientRect();
                    if (!box) return;
                    moveCorner(
                      index,
                      canvasToNormalized(
                        { x: event.clientX - box.left, y: event.clientY - box.top },
                        { width: asset.width, height: asset.height },
                        view,
                      ),
                      false,
                    );
                  }}
                  onPointerUp={() => {
                    const baseline = cornerBaseline.current;
                    cornerBaseline.current = null;
                    if (baseline && !isSameRecipe(baseline, recipe)) {
                      setHistory((items) => [...items.slice(-29), baseline]);
                    }
                  }}
                  onKeyDown={(event) => {
                    const step = event.shiftKey ? 0.02 : 0.01;
                    const delta =
                      event.key === 'ArrowLeft'
                        ? { x: -step, y: 0 }
                        : event.key === 'ArrowRight'
                          ? { x: step, y: 0 }
                          : event.key === 'ArrowUp'
                            ? { x: 0, y: -step }
                            : event.key === 'ArrowDown'
                              ? { x: 0, y: step }
                              : null;
                    if (!delta) return;
                    event.preventDefault();
                    moveCorner(index, { x: corner.x + delta.x, y: corner.y + delta.y }, true);
                  }}
                />
              );
            })}
          </div>
          <div className="preparation-toolbar" aria-label="Вид изображения">
            <Button
              variant="secondary"
              onClick={() => setView((current) => zoomTransform(current, 1.2, { x: 0, y: 0 }))}
            >
              Увеличить
            </Button>
            <Button
              variant="secondary"
              onClick={() => setView((current) => zoomTransform(current, 1 / 1.2, { x: 0, y: 0 }))}
            >
              Уменьшить
            </Button>
            <Button variant="secondary" onClick={() => resetView(state)}>
              По размеру
            </Button>
            <label>
              <input
                type="checkbox"
                checked={showOriginal}
                onChange={(event) => setShowOriginal(event.target.checked)}
              />{' '}
              Оригинал
            </label>
          </div>
        </section>
        <aside className="preparation-controls">
          <Card>
            <p className="eyebrow">Геометрия</p>
            <div className="preparation-button-grid">
              <Button variant="secondary" onClick={() => change(rotateRecipe(recipe, -90))}>
                Повернуть влево
              </Button>
              <Button variant="secondary" onClick={() => change(rotateRecipe(recipe, 90))}>
                Повернуть вправо
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  change({
                    ...recipe,
                    crop: crop ? null : { x: 0.05, y: 0.05, width: 0.9, height: 0.9 },
                  })
                }
              >
                {crop ? 'Убрать обрезку' : 'Обрезать края'}
              </Button>
              <Button
                variant="secondary"
                onClick={() =>
                  recipe.perspective
                    ? removePerspective()
                    : change({ ...recipe, perspective: initialCorners })
                }
              >
                {recipe.perspective ? 'Убрать перспективу' : 'Выровнять перспективу'}
              </Button>
            </div>
            {crop ? (
              <div className="preparation-fields">
                <label>
                  X
                  <input
                    aria-label="Обрезка X"
                    type="number"
                    min="0"
                    max="0.98"
                    step="0.01"
                    value={crop.x}
                    onChange={(event) =>
                      change({
                        ...recipe,
                        crop: normalizeCrop({ ...crop, x: Number(event.target.value) }),
                      })
                    }
                  />
                </label>
                <label>
                  Y
                  <input
                    aria-label="Обрезка Y"
                    type="number"
                    min="0"
                    max="0.98"
                    step="0.01"
                    value={crop.y}
                    onChange={(event) =>
                      change({
                        ...recipe,
                        crop: normalizeCrop({ ...crop, y: Number(event.target.value) }),
                      })
                    }
                  />
                </label>
                <label>
                  Ширина
                  <input
                    aria-label="Ширина обрезки"
                    type="number"
                    min="0.02"
                    max="1"
                    step="0.01"
                    value={crop.width}
                    onChange={(event) =>
                      change({
                        ...recipe,
                        crop: normalizeCrop({ ...crop, width: Number(event.target.value) }),
                      })
                    }
                  />
                </label>
                <label>
                  Высота
                  <input
                    aria-label="Высота обрезки"
                    type="number"
                    min="0.02"
                    max="1"
                    step="0.01"
                    value={crop.height}
                    onChange={(event) =>
                      change({
                        ...recipe,
                        crop: normalizeCrop({ ...crop, height: Number(event.target.value) }),
                      })
                    }
                  />
                </label>
              </div>
            ) : null}
            <div className="preparation-button-grid">
              <Button
                variant="quiet"
                disabled={!history.length}
                onClick={() => {
                  const previous = history.at(-1);
                  if (!previous) return;
                  setRecipe(previous);
                  setHistory((items) => items.slice(0, -1));
                }}
              >
                Отменить
              </Button>
              <Button variant="quiet" onClick={resetRecipe}>
                Сбросить
              </Button>
            </div>
          </Card>
          <Card>
            <p className="eyebrow">Предпросмотр сервера</p>
            {state.qualityWarnings.length ? (
              <ul className="preparation-warnings">
                {state.qualityWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : (
              <p>Оценка качества появится после реального серверного предпросмотра.</p>
            )}
            {state.qualityMetrics ? (
              <p className="preparation-metrics">
                Порог {state.qualityThresholdVersion}; получено метрик:{' '}
                {Object.keys(state.qualityMetrics).length}.
              </p>
            ) : null}
            {state.confirmed ? (
              <p className="preparation-confirmed" role="status">
                Рецепт подтверждён. Запустите задачу детектора, чтобы получить области строк для
                проверки.
              </p>
            ) : null}
            {message ? (
              <p className="preparation-message" role="alert">
                {message}
              </p>
            ) : null}
          </Card>
        </aside>
      </div>
    </main>
  );
}
