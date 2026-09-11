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
import { Button, Card, Icon, LoadingState } from '@shared/ui';

const initialCorners: NonNullable<PreparationRecipe['perspective']> = [
  { x: 0.04, y: 0.04 },
  { x: 0.96, y: 0.04 },
  { x: 0.96, y: 0.96 },
  { x: 0.04, y: 0.96 },
];

type CanvasPoint = Readonly<{ x: number; y: number }>;
type PreparationPanel = 'adjust' | 'view' | 'quality' | 'history';
type MobileSheetLevel = 0 | 1 | 2;

const preparationPanels = [
  { id: 'adjust', label: 'Правка', icon: 'settings' },
  { id: 'view', label: 'Вид', icon: 'image' },
  { id: 'quality', label: 'Качество', icon: 'sparkles' },
  { id: 'history', label: 'История', icon: 'clock' },
] as const;

function canvasPoint(event: React.PointerEvent<HTMLElement>): CanvasPoint {
  const box = event.currentTarget.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}

function isSameRecipe(left: PreparationRecipe, right: PreparationRecipe): boolean {
  return recipeEquals(left, right);
}

function visibleCanvasViewport(
  element: HTMLElement,
  sheetLevel: MobileSheetLevel,
): { width: number; height: number } {
  if (window.innerWidth > 900) {
    return { width: element.clientWidth, height: element.clientHeight };
  }
  const sheetHeight = Math.min(window.innerHeight * 0.72, 620);
  const visibleSheetHeight =
    sheetLevel === 0
      ? 116
      : sheetLevel === 1
        ? Math.min(window.innerHeight * 0.48, 390)
        : sheetHeight;
  return {
    width: element.clientWidth,
    height: Math.max(160, element.clientHeight - visibleSheetHeight),
  };
}

function initialView(state: PreparationState, element: HTMLElement | null): Transform {
  if (!element) return { scale: 1, offsetX: 0, offsetY: 0 };
  return fitTransform(
    { width: state.sourceAsset.width, height: state.sourceAsset.height },
    visibleCanvasViewport(element, 1),
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
  const sheetDrag = useRef<{
    startY: number;
    level: MobileSheetLevel;
    moved: boolean;
  } | null>(null);
  const [state, setState] = useState<PreparationState | null>(null);
  const [recipe, setRecipe] = useState<PreparationRecipe>(defaultPreparationRecipe);
  const [history, setHistory] = useState<PreparationRecipe[]>([]);
  const [future, setFuture] = useState<PreparationRecipe[]>([]);
  const [view, setView] = useState<Transform>({ scale: 1, offsetX: 0, offsetY: 0 });
  const [showOriginal, setShowOriginal] = useState(true);
  const [activePanel, setActivePanel] = useState<PreparationPanel>('adjust');
  const [mobileSheetLevel, setMobileSheetLevel] = useState<MobileSheetLevel>(1);
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
    setFuture([]);
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
    const element = viewport.current;
    if (!state || !element) return;

    const zoomWithWheel = (event: WheelEvent) => {
      event.preventDefault();
      const box = element.getBoundingClientRect();
      setView((current) =>
        zoomTransform(current, event.deltaY < 0 ? 1.15 : 1 / 1.15, {
          x: event.clientX - box.left,
          y: event.clientY - box.top,
        }),
      );
    };

    element.addEventListener('wheel', zoomWithWheel, { passive: false });
    return () => element.removeEventListener('wheel', zoomWithWheel);
  }, [state]);

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
      if (keepUndo) {
        setHistory((items) => [...items.slice(-29), cloneRecipe(current)]);
        setFuture([]);
      }
      return cloneRecipe(next);
    });
  }

  function undoChange() {
    const previous = history.at(-1);
    if (!previous) return;
    setFuture((items) => [...items.slice(-29), cloneRecipe(recipe)]);
    setRecipe(cloneRecipe(previous));
    setHistory((items) => items.slice(0, -1));
  }

  function redoChange() {
    const next = future.at(-1);
    if (!next) return;
    setHistory((items) => [...items.slice(-29), cloneRecipe(recipe)]);
    setRecipe(cloneRecipe(next));
    setFuture((items) => items.slice(0, -1));
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

  function zoomAtCenter(factor: number) {
    const element = viewport.current;
    const anchor = element
      ? { x: element.clientWidth / 2, y: element.clientHeight / 2 }
      : { x: 0, y: 0 };
    setView((current) => zoomTransform(current, factor, anchor));
  }

  function setZoomPercent(percent: number) {
    const element = viewport.current;
    const anchor = element
      ? { x: element.clientWidth / 2, y: element.clientHeight / 2 }
      : { x: 0, y: 0 };
    setView((current) => zoomTransform(current, percent / 100 / current.scale, anchor));
  }

  function fitCurrentAsset(assetSize: { width: number; height: number }) {
    const element = viewport.current;
    if (!element) return;
    setView(fitTransform(assetSize, visibleCanvasViewport(element, mobileSheetLevel)));
  }

  function selectAsset(original: boolean) {
    if (!state) return;
    const nextAsset = original ? state.sourceAsset : state.preparedAsset;
    if (!nextAsset) return;
    setShowOriginal(original);
    window.requestAnimationFrame(() => fitCurrentAsset(nextAsset));
  }

  function beginSheetDrag(event: React.PointerEvent<HTMLButtonElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    sheetDrag.current = { startY: event.clientY, level: mobileSheetLevel, moved: false };
  }

  function moveSheetDrag(event: React.PointerEvent<HTMLButtonElement>) {
    const drag = sheetDrag.current;
    if (!drag) return;
    const delta = drag.startY - event.clientY;
    if (Math.abs(delta) > 12) drag.moved = true;
    if (delta > 56) setMobileSheetLevel(Math.min(2, drag.level + 1) as MobileSheetLevel);
    if (delta < -56) setMobileSheetLevel(Math.max(0, drag.level - 1) as MobileSheetLevel);
  }

  function endSheetDrag() {
    const drag = sheetDrag.current;
    sheetDrag.current = null;
    if (drag && !drag.moved) {
      setMobileSheetLevel((current) => (current === 0 ? 1 : 0));
    }
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
    setFuture([]);
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
    setFuture([]);
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
        <LoadingState
          title="Загружаем подготовку"
          description="Получаем изображение и сохранённые параметры подготовки."
        />
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
  const needsPreview = !state.preparedAsset || !state.recipe || !isSameRecipe(recipe, state.recipe);
  const zoomPercent = Math.round(view.scale * 100);

  return (
    <main className="preparation-page preparation-editor" id="main-content" tabIndex={-1}>
      <header className="preparation-editor__header">
        <div className="preparation-editor__title">
          <p className="eyebrow">Редактор страницы</p>
          <div>
            <h1>Подготовка изображения</h1>
            <span>{needsPreview ? 'Есть несохранённые изменения' : 'Предпросмотр готов'}</span>
          </div>
        </div>
        <div className="preparation-editor__actions">
          <Link className="ui-button ui-button--secondary" to="/capture">
            Отмена
          </Link>
          {needsPreview ? (
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
      {message ? (
        <p className="preparation-editor__message" role="alert">
          {message}
        </p>
      ) : null}

      <div className="preparation-editor__layout">
        <section className="preparation-workspace" aria-label="Подготовка изображения">
          <div className="preparation-workspace__bar">
            <div className="preparation-workspace__asset">
              <span className="preparation-workspace__dot" />
              <span>{showOriginal ? 'Оригинал' : 'Предпросмотр'}</span>
            </div>
            <div className="preparation-quick-tools" aria-label="Быстрое управление видом">
              <button type="button" aria-label="Уменьшить" onClick={() => zoomAtCenter(1 / 1.2)}>
                <Icon name="zoom-out" />
              </button>
              <output aria-label="Текущий масштаб">{zoomPercent}%</output>
              <button type="button" aria-label="Увеличить" onClick={() => zoomAtCenter(1.2)}>
                <Icon name="zoom-in" />
              </button>
              <button
                type="button"
                aria-label="Вписать изображение"
                onClick={() => fitCurrentAsset(asset)}
              >
                <Icon name="fit" />
              </button>
              <button
                type="button"
                aria-label={showOriginal ? 'Показать предпросмотр' : 'Показать оригинал'}
                disabled={!state.preparedAsset}
                onClick={() => selectAsset(!showOriginal)}
              >
                <Icon name="eye" />
              </button>
            </div>
          </div>
          <div
            className="preparation-canvas"
            ref={viewport}
            onPointerDown={beginPan}
            onPointerMove={movePan}
            onPointerUp={endPan}
            onPointerCancel={endPan}
            onDoubleClick={() => fitCurrentAsset(asset)}
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
            <p className="preparation-canvas__hint">
              Перетаскивайте изображение · колесо или щипок меняют масштаб
            </p>
          </div>
        </section>

        <aside
          className="preparation-tools"
          data-sheet-level={mobileSheetLevel}
          aria-label="Инструменты подготовки"
        >
          <button
            className="preparation-tools__handle"
            type="button"
            aria-label={mobileSheetLevel === 0 ? 'Развернуть инструменты' : 'Свернуть инструменты'}
            aria-expanded={mobileSheetLevel !== 0}
            onPointerDown={beginSheetDrag}
            onPointerMove={moveSheetDrag}
            onPointerUp={endSheetDrag}
            onPointerCancel={() => {
              sheetDrag.current = null;
            }}
          >
            <span />
            <Icon name="chevron" />
          </button>

          <div className="preparation-tools__tabs" role="tablist" aria-label="Разделы инструментов">
            {preparationPanels.map((panel) => (
              <button
                key={panel.id}
                id={`preparation-tab-${panel.id}`}
                type="button"
                role="tab"
                aria-selected={activePanel === panel.id}
                aria-controls="preparation-tools-panel"
                onClick={() => {
                  setActivePanel(panel.id);
                  if (mobileSheetLevel === 0) setMobileSheetLevel(1);
                }}
              >
                <Icon name={panel.icon} />
                <span>{panel.label}</span>
              </button>
            ))}
          </div>

          <div
            className="preparation-tools__content"
            id="preparation-tools-panel"
            role="tabpanel"
            aria-labelledby={`preparation-tab-${activePanel}`}
          >
            {activePanel === 'adjust' ? (
              <section className="preparation-panel" aria-label="Правка геометрии">
                <div className="preparation-panel__heading">
                  <p className="eyebrow">Геометрия</p>
                  <h2>Выровняйте страницу</h2>
                  <p>Поворот, обрезка и перспектива собраны в одном месте.</p>
                </div>
                <div className="preparation-tool-grid">
                  <button type="button" onClick={() => change(rotateRecipe(recipe, -90))}>
                    <Icon name="rotate-left" />
                    <span>Влево</span>
                  </button>
                  <button type="button" onClick={() => change(rotateRecipe(recipe, 90))}>
                    <Icon name="rotate-right" />
                    <span>Вправо</span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={Boolean(crop)}
                    className={crop ? 'is-active' : ''}
                    onClick={() =>
                      change({
                        ...recipe,
                        crop: crop ? null : { x: 0.05, y: 0.05, width: 0.9, height: 0.9 },
                      })
                    }
                  >
                    <Icon name="crop" />
                    <span>{crop ? 'Без обрезки' : 'Обрезать'}</span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={Boolean(recipe.perspective)}
                    className={recipe.perspective ? 'is-active' : ''}
                    onClick={() =>
                      recipe.perspective
                        ? removePerspective()
                        : change({ ...recipe, perspective: initialCorners })
                    }
                  >
                    <Icon name="fit" />
                    <span>{recipe.perspective ? 'Без перспективы' : 'Перспектива'}</span>
                  </button>
                </div>

                {crop ? (
                  <fieldset className="preparation-fields">
                    <legend>Точные границы обрезки</legend>
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
                  </fieldset>
                ) : null}
                {recipe.perspective ? (
                  <p className="preparation-panel__note">
                    Перетащите четыре точки на изображении. Стрелки двигают выбранную точку точнее.
                  </p>
                ) : null}
              </section>
            ) : null}

            {activePanel === 'view' ? (
              <section className="preparation-panel" aria-label="Настройки вида">
                <div className="preparation-panel__heading">
                  <p className="eyebrow">Навигация</p>
                  <h2>Масштаб и просмотр</h2>
                  <p>Настройки вида не изменяют итоговое изображение.</p>
                </div>
                <div className="preparation-zoom-control">
                  <button
                    type="button"
                    aria-label="Уменьшить"
                    onClick={() => zoomAtCenter(1 / 1.2)}
                  >
                    <Icon name="zoom-out" />
                  </button>
                  <output>{zoomPercent}%</output>
                  <button type="button" aria-label="Увеличить" onClick={() => zoomAtCenter(1.2)}>
                    <Icon name="zoom-in" />
                  </button>
                </div>
                <input
                  className="preparation-zoom-range"
                  aria-label="Масштаб изображения"
                  type="range"
                  min="10"
                  max="800"
                  step="5"
                  value={Math.min(800, Math.max(10, zoomPercent))}
                  onChange={(event) => setZoomPercent(Number(event.target.value))}
                />
                <button
                  className="preparation-wide-action"
                  type="button"
                  onClick={() => fitCurrentAsset(asset)}
                >
                  <Icon name="fit" />
                  Вписать изображение
                </button>
                <div className="preparation-segmented" aria-label="Источник изображения">
                  <button
                    type="button"
                    aria-pressed={showOriginal}
                    className={showOriginal ? 'is-active' : ''}
                    onClick={() => selectAsset(true)}
                  >
                    Оригинал
                  </button>
                  <button
                    type="button"
                    aria-pressed={!showOriginal}
                    className={!showOriginal ? 'is-active' : ''}
                    disabled={!state.preparedAsset}
                    onClick={() => selectAsset(false)}
                  >
                    Предпросмотр
                  </button>
                </div>
              </section>
            ) : null}

            {activePanel === 'quality' ? (
              <section className="preparation-panel" aria-label="Качество предпросмотра">
                <div className="preparation-panel__heading">
                  <p className="eyebrow">Проверка сервера</p>
                  <h2>{needsPreview ? 'Нужен новый предпросмотр' : 'Страница готова'}</h2>
                  <p>
                    {needsPreview
                      ? 'Нажмите «Подготовить», чтобы сервер проверил текущие изменения.'
                      : 'Сервер проверил текущую версию изображения.'}
                  </p>
                </div>
                {state.qualityWarnings.length ? (
                  <ul className="preparation-warnings">
                    {state.qualityWarnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : (
                  <div className="preparation-quality-empty">
                    <Icon name="shield" />
                    <p>
                      {state.qualityMetrics
                        ? 'Критических предупреждений не найдено.'
                        : 'Оценка появится после серверного предпросмотра.'}
                    </p>
                  </div>
                )}
                {state.qualityMetrics ? (
                  <p className="preparation-metrics">
                    Версия порога: {state.qualityThresholdVersion}. Проверено метрик:{' '}
                    {Object.keys(state.qualityMetrics).length}.
                  </p>
                ) : null}
                {state.confirmed ? (
                  <p className="preparation-confirmed" role="status">
                    Рецепт подтверждён и готов к поиску строк.
                  </p>
                ) : null}
              </section>
            ) : null}

            {activePanel === 'history' ? (
              <section className="preparation-panel" aria-label="История изменений">
                <div className="preparation-panel__heading">
                  <p className="eyebrow">История</p>
                  <h2>{history.length ? `${history.length} изменений` : 'Нет изменений'}</h2>
                  <p>Можно отменить до 30 последних действий или вернуть отменённое действие.</p>
                </div>
                <div className="preparation-history-actions">
                  <button type="button" disabled={!history.length} onClick={undoChange}>
                    <Icon name="undo" />
                    <span>Отменить</span>
                  </button>
                  <button type="button" disabled={!future.length} onClick={redoChange}>
                    <Icon name="redo" />
                    <span>Вернуть</span>
                  </button>
                </div>
                <button className="preparation-wide-action" type="button" onClick={resetRecipe}>
                  <Icon name="rotate-left" />
                  Сбросить всю правку
                </button>
              </section>
            ) : null}
          </div>
        </aside>
      </div>
    </main>
  );
}
