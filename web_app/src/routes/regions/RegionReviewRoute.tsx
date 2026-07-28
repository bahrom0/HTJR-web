import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'motion/react';

import { getJobSnapshot, type JobSnapshot } from '@entities/job';
import { getPreparation } from '@features/preparation/api';
import type { PreparationAsset } from '@features/preparation/model';
import {
  canvasToNormalized,
  fitTransform,
  normalizedToCanvas,
  zoomTransform,
  type Transform,
} from '@features/regions/geometry';
import {
  confirmRegions,
  getRegions,
  replaceRegions,
  type Region,
  type RegionBounds,
  type RegionDraft,
  type RegionSnapshot,
} from '@features/regions';
import {
  clampUnit,
  cloneRegions,
  createManualRegion,
  mergeRegions,
  moveReadingOrder,
  moveRegion,
  polygonPath,
  regionBounds,
  replaceRegionBounds,
  replaceOne,
  resizeRegion,
  sameRegions,
  splitRegion,
  withContiguousOrder,
  type NormalizedPoint,
  type ResizeCorner,
  type SplitDirection,
} from '@features/regions/model';
import { loadRegionDraft, removeRegionDraft, saveRegionDraft } from '@features/regions/persistence';
import { useAccess } from '@shared/access/AccessProvider';
import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { Badge, Button, Card } from '@shared/ui';

type CanvasPoint = Readonly<{ x: number; y: number }>;
type BusyAction = 'save' | 'confirm' | null;

type RegionDrag =
  | Readonly<{
      kind: 'move';
      pointerId: number;
      regionId: string;
      start: NormalizedPoint;
      baseline: readonly Region[];
    }>
  | Readonly<{
      kind: 'resize';
      pointerId: number;
      regionId: string;
      corner: ResizeCorner;
      baseline: readonly Region[];
    }>
  | Readonly<{
      kind: 'add';
      pointerId: number;
      start: NormalizedPoint;
      baseline: readonly Region[];
    }>;

type PanDrag = Readonly<{ pointerId: number; start: CanvasPoint; view: Transform }>;
type Pinch = Readonly<{ distance: number; center: CanvasPoint; view: Transform }>;

function hasTextInputFocus(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  );
}

function toCanvasPoint(
  event: PointerEvent<Element>,
  viewport: HTMLElement | null,
): CanvasPoint | null {
  if (!viewport) return null;
  const box = viewport.getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top };
}

function regionLabel(region: Region, position: number): string {
  const source =
    region.source === 'craft'
      ? 'CRAFT'
      : region.source === 'manual'
        ? 'ручная область'
        : 'исправленная область';
  return `Регион ${position + 1}: ${source}`;
}

function sourceLabel(source: Region['source']): string {
  if (source === 'craft') return 'CRAFT';
  if (source === 'manual') return 'ручной';
  return 'исправлен';
}

function defaultManualBounds(regionCount: number): RegionBounds {
  const minY = Math.min(0.78, 0.08 + (regionCount % 6) * 0.13);
  return { minX: 0.14, minY, maxX: 0.86, maxY: Math.min(0.96, minY + 0.1) };
}

function boundsFromPoints(first: NormalizedPoint, second: NormalizedPoint): RegionBounds {
  return {
    minX: clampUnit(Math.min(first.x, second.x)),
    minY: clampUnit(Math.min(first.y, second.y)),
    maxX: clampUnit(Math.max(first.x, second.x)),
    maxY: clampUnit(Math.max(first.y, second.y)),
  };
}

function isUsableBounds(bounds: RegionBounds): boolean {
  return bounds.maxX - bounds.minX >= 0.01 && bounds.maxY - bounds.minY >= 0.01;
}

function cloneHistory(items: readonly (readonly Region[])[]): Region[][] {
  return items.map((regions) => cloneRegions(regions));
}

export default function RegionReviewRoute() {
  const { csrfToken, reconnect } = useAccess();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const pageId = params.get('pageId');
  const jobId = params.get('jobId');
  const canAnimate = useAccessibleMotion();
  const viewport = useRef<HTMLDivElement>(null);
  const assetRef = useRef<PreparationAsset | null>(null);
  const snapshotRef = useRef<RegionSnapshot | null>(null);
  const selectedIdsRef = useRef<string[]>([]);
  const regionsRef = useRef<Region[]>([]);
  const historyRef = useRef<Region[][]>([]);
  const redoRef = useRef<Region[][]>([]);
  const activePointers = useRef(new Map<number, CanvasPoint>());
  const regionDrag = useRef<RegionDrag | null>(null);
  const pan = useRef<PanDrag | null>(null);
  const pinch = useRef<Pinch | null>(null);
  const viewHasBeenFit = useRef(false);
  const [asset, setAsset] = useState<PreparationAsset | null>(null);
  const [snapshot, setSnapshot] = useState<RegionSnapshot | null>(null);
  const [job, setJob] = useState<JobSnapshot | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [history, setHistory] = useState<Region[][]>([]);
  const [redo, setRedo] = useState<Region[][]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [view, setView] = useState<Transform>({ scale: 1, offsetX: 0, offsetY: 0 });
  const [drawMode, setDrawMode] = useState(false);
  const [drawPreview, setDrawPreview] = useState<RegionBounds | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [recoveredDraft, setRecoveredDraft] = useState<RegionDraft | null>(null);

  const replaceLocalRegions = useCallback((next: readonly Region[]) => {
    const normalized = withContiguousOrder(next);
    regionsRef.current = normalized;
    setRegions(normalized);
  }, []);

  const replaceAsset = useCallback((next: PreparationAsset | null) => {
    assetRef.current = next;
    setAsset(next);
  }, []);

  const replaceSnapshot = useCallback((next: RegionSnapshot | null) => {
    snapshotRef.current = next;
    setSnapshot(next);
  }, []);

  const replaceHistory = useCallback((next: readonly (readonly Region[])[]) => {
    const cloned = cloneHistory(next);
    historyRef.current = cloned;
    setHistory(cloned);
  }, []);

  const replaceRedo = useCallback((next: readonly (readonly Region[])[]) => {
    const cloned = cloneHistory(next);
    redoRef.current = cloned;
    setRedo(cloned);
  }, []);

  const imageSize = asset ? { width: asset.width, height: asset.height } : null;
  const selectedRegions = useMemo(
    () => regions.filter((region) => selectedIds.includes(region.id)),
    [regions, selectedIds],
  );
  const selectedRegion = selectedRegions[0] ?? null;
  const isDirty = snapshot ? !sameRegions(regions, snapshot.regions) : false;

  const resetView = useCallback(() => {
    const element = viewport.current;
    if (!element || !asset) return;
    setView(
      fitTransform(
        { width: asset.width, height: asset.height },
        { width: element.clientWidth, height: element.clientHeight },
      ),
    );
    viewHasBeenFit.current = true;
  }, [asset]);

  const load = useCallback(
    async (options: Readonly<{ consultDraft?: boolean; preserveCurrentDraft?: boolean }> = {}) => {
      if (!pageId) return;
      const currentAsset = assetRef.current;
      const currentSnapshot = snapshotRef.current;
      const hasUnsavedLocalChanges =
        currentSnapshot !== null && !sameRegions(regionsRef.current, currentSnapshot.regions);
      if (
        options.preserveCurrentDraft &&
        currentAsset &&
        currentSnapshot &&
        hasUnsavedLocalChanges
      ) {
        await saveRegionDraft({
          pageId,
          preparedAssetId: currentAsset.id,
          baseRevision: currentSnapshot.revision,
          regions: cloneRegions(regionsRef.current),
          history: cloneHistory(historyRef.current),
          redo: cloneHistory(redoRef.current),
          selectedIds: selectedIdsRef.current,
          updatedAt: new Date().toISOString(),
        }).catch(() => undefined);
      }
      setLoading(true);
      setMessage(null);
      const [regionsResponse, preparationResponse, jobResponse] = await Promise.all([
        getRegions(pageId),
        getPreparation(pageId),
        jobId ? getJobSnapshot(jobId) : Promise.resolve(null),
      ]);
      setLoading(false);
      if (!regionsResponse.ok) {
        setMessage(regionsResponse.error.message);
        return;
      }
      if (!preparationResponse.ok) {
        setMessage(preparationResponse.error.message);
        return;
      }
      const preparedAsset = preparationResponse.value.preparedAsset;
      if (!preparedAsset) {
        setMessage('Подготовленный сервером снимок ещё не готов для проверки областей.');
        return;
      }
      if (jobResponse && !jobResponse.ok) {
        setMessage(jobResponse.error.message);
      }
      const nextSnapshot = regionsResponse.value;
      const savedDraft =
        options.consultDraft === false ? null : await loadRegionDraft(pageId).catch(() => null);
      const canRestore =
        savedDraft !== null &&
        savedDraft.preparedAssetId === preparedAsset.id &&
        savedDraft.baseRevision === nextSnapshot.revision;
      replaceAsset(preparedAsset);
      replaceSnapshot(nextSnapshot);
      setJob(jobResponse !== null && jobResponse.ok ? jobResponse.value : null);
      replaceLocalRegions(canRestore ? savedDraft.regions : nextSnapshot.regions);
      replaceHistory(canRestore ? savedDraft.history : []);
      replaceRedo(canRestore ? savedDraft.redo : []);
      const nextSelectedIds = canRestore
        ? savedDraft.selectedIds.filter((id) =>
            savedDraft.regions.some((region) => region.id === id),
          )
        : nextSnapshot.regions.slice(0, 1).map((region) => region.id);
      selectedIdsRef.current = nextSelectedIds;
      setSelectedIds(nextSelectedIds);
      setRecoveredDraft(canRestore ? null : savedDraft);
      viewHasBeenFit.current = false;
      if (canRestore) setMessage('Восстановлены несохранённые правки областей из этого браузера.');
    },
    [
      jobId,
      pageId,
      replaceAsset,
      replaceHistory,
      replaceLocalRegions,
      replaceRedo,
      replaceSnapshot,
    ],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useLayoutEffect(() => {
    if (!asset || !viewport.current) return;
    const element = viewport.current;
    const observer = new ResizeObserver(() => {
      if (!viewHasBeenFit.current) resetView();
    });
    observer.observe(element);
    resetView();
    return () => observer.disconnect();
  }, [asset, resetView]);

  useEffect(() => {
    if (!pageId || !asset || !snapshot || !isDirty) return;
    void saveRegionDraft({
      pageId,
      preparedAssetId: asset.id,
      baseRevision: snapshot.revision,
      regions: cloneRegions(regions),
      history: cloneHistory(history),
      redo: cloneHistory(redo),
      selectedIds,
      updatedAt: new Date().toISOString(),
    }).catch(() =>
      setMessage('Локальное сохранение черновика областей недоступно в этом браузере.'),
    );
  }, [asset, history, isDirty, pageId, redo, regions, selectedIds, snapshot]);

  useEffect(() => {
    if (!jobId || !job || job.state === 'awaiting_region_review' || isDirty) return;
    if (job.state === 'completed' || job.state === 'cancelled' || job.state.startsWith('failed'))
      return;
    const timer = window.setTimeout(() => void load({ consultDraft: false }), 2_000);
    return () => window.clearTimeout(timer);
  }, [isDirty, job, jobId, load]);

  function applyEdit(next: readonly Region[]) {
    const current = cloneRegions(regionsRef.current);
    const normalized = withContiguousOrder(next);
    if (sameRegions(current, normalized)) return;
    replaceHistory([...historyRef.current.slice(-49), current]);
    replaceRedo([]);
    replaceLocalRegions(normalized);
    setRecoveredDraft(null);
  }

  function commitPointerEdit(baseline: readonly Region[], cancelled = false) {
    regionDrag.current = null;
    setDrawPreview(null);
    if (cancelled) {
      replaceLocalRegions(baseline);
      return;
    }
    if (sameRegions(baseline, regionsRef.current)) return;
    replaceHistory([...historyRef.current.slice(-49), cloneRegions(baseline)]);
    replaceRedo([]);
    setRecoveredDraft(null);
  }

  function undo() {
    const previous = historyRef.current.at(-1);
    if (!previous) return;
    replaceRedo([...redoRef.current.slice(-49), cloneRegions(regionsRef.current)]);
    replaceHistory(historyRef.current.slice(0, -1));
    replaceLocalRegions(previous);
  }

  function redoEdit() {
    const next = redoRef.current.at(-1);
    if (!next) return;
    replaceHistory([...historyRef.current.slice(-49), cloneRegions(regionsRef.current)]);
    replaceRedo(redoRef.current.slice(0, -1));
    replaceLocalRegions(next);
  }

  function selectOnly(id: string) {
    selectedIdsRef.current = [id];
    setSelectedIds([id]);
  }

  function toggleSelection(id: string) {
    const next = selectedIdsRef.current.includes(id)
      ? selectedIdsRef.current.filter((selectedId) => selectedId !== id)
      : [...selectedIdsRef.current, id];
    selectedIdsRef.current = next;
    setSelectedIds(next);
  }

  function normalizedEventPoint(event: PointerEvent<Element>): NormalizedPoint | null {
    if (!imageSize) return null;
    const point = toCanvasPoint(event, viewport.current);
    if (!point) return null;
    return canvasToNormalized(point, imageSize, view);
  }

  function startRegionMove(event: PointerEvent<SVGPolygonElement>, region: Region) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.shiftKey) {
      toggleSelection(region.id);
      return;
    }
    const start = normalizedEventPoint(event);
    if (!start) return;
    selectOnly(region.id);
    event.currentTarget.setPointerCapture(event.pointerId);
    regionDrag.current = {
      kind: 'move',
      pointerId: event.pointerId,
      regionId: region.id,
      start,
      baseline: cloneRegions(regionsRef.current),
    };
  }

  function moveRegionPointer(event: PointerEvent<SVGPolygonElement>) {
    const drag = regionDrag.current;
    if (!drag || drag.kind !== 'move' || drag.pointerId !== event.pointerId) return;
    const current = normalizedEventPoint(event);
    if (!current) return;
    const delta = { x: current.x - drag.start.x, y: current.y - drag.start.y };
    replaceLocalRegions(
      drag.baseline.map((region) =>
        region.id === drag.regionId ? moveRegion(region, delta) : { ...region },
      ),
    );
  }

  function endRegionPointer(event: PointerEvent<SVGPolygonElement>, cancelled = false) {
    const drag = regionDrag.current;
    if (!drag || drag.kind !== 'move' || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    commitPointerEdit(drag.baseline, cancelled);
  }

  function startResize(event: PointerEvent<HTMLButtonElement>, corner: ResizeCorner) {
    if (!selectedRegion || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    regionDrag.current = {
      kind: 'resize',
      pointerId: event.pointerId,
      regionId: selectedRegion.id,
      corner,
      baseline: cloneRegions(regionsRef.current),
    };
  }

  function moveResize(event: PointerEvent<HTMLButtonElement>) {
    const drag = regionDrag.current;
    if (!drag || drag.kind !== 'resize' || drag.pointerId !== event.pointerId) return;
    const point = normalizedEventPoint(event);
    if (!point) return;
    replaceLocalRegions(
      drag.baseline.map((region) =>
        region.id === drag.regionId ? resizeRegion(region, drag.corner, point) : { ...region },
      ),
    );
  }

  function endResize(event: PointerEvent<HTMLButtonElement>, cancelled = false) {
    const drag = regionDrag.current;
    if (!drag || drag.kind !== 'resize' || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    commitPointerEdit(drag.baseline, cancelled);
  }

  function startCanvasPointer(event: PointerEvent<HTMLDivElement>) {
    if (!asset) return;
    const point = toCanvasPoint(event, viewport.current);
    if (!point) return;
    if (drawMode) {
      const normalized = canvasToNormalized(point, imageSize ?? { width: 1, height: 1 }, view);
      event.currentTarget.setPointerCapture(event.pointerId);
      regionDrag.current = {
        kind: 'add',
        pointerId: event.pointerId,
        start: normalized,
        baseline: cloneRegions(regionsRef.current),
      };
      setDrawPreview(null);
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    activePointers.current.set(event.pointerId, point);
    if (activePointers.current.size === 1) {
      pan.current = { pointerId: event.pointerId, start: point, view };
      return;
    }
    const points = [...activePointers.current.values()];
    const first = points[0];
    const second = points[1];
    if (!first || !second) return;
    pinch.current = {
      distance: Math.max(1, Math.hypot(first.x - second.x, first.y - second.y)),
      center: { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 },
      view,
    };
    pan.current = null;
  }

  function moveCanvasPointer(event: PointerEvent<HTMLDivElement>) {
    const activeDrag = regionDrag.current;
    if (activeDrag?.kind === 'add' && activeDrag.pointerId === event.pointerId) {
      const current = normalizedEventPoint(event);
      if (current) setDrawPreview(boundsFromPoints(activeDrag.start, current));
      return;
    }
    const point = toCanvasPoint(event, viewport.current);
    if (!point) return;
    activePointers.current.set(event.pointerId, point);
    const points = [...activePointers.current.values()];
    const first = points[0];
    const second = points[1];
    if (pinch.current && first && second) {
      const distance = Math.max(1, Math.hypot(first.x - second.x, first.y - second.y));
      const center = { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
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
    if (!pan.current || pan.current.pointerId !== event.pointerId) return;
    setView({
      ...pan.current.view,
      offsetX: pan.current.view.offsetX + point.x - pan.current.start.x,
      offsetY: pan.current.view.offsetY + point.y - pan.current.start.y,
    });
  }

  function endCanvasPointer(event: PointerEvent<HTMLDivElement>, cancelled = false) {
    const activeDrag = regionDrag.current;
    if (activeDrag?.kind === 'add' && activeDrag.pointerId === event.pointerId) {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      const current = normalizedEventPoint(event);
      const nextBounds = current ? boundsFromPoints(activeDrag.start, current) : null;
      if (!cancelled && nextBounds && isUsableBounds(nextBounds)) {
        const created = createManualRegion(nextBounds);
        applyEdit([...activeDrag.baseline, created]);
        selectOnly(created.id);
        setDrawMode(false);
      } else if (!cancelled) {
        setMessage('Проведите область не меньше 1% ширины и высоты изображения.');
      }
      regionDrag.current = null;
      setDrawPreview(null);
      return;
    }
    activePointers.current.delete(event.pointerId);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (activePointers.current.size < 2) pinch.current = null;
    if (activePointers.current.size === 0) pan.current = null;
  }

  function deleteSelected() {
    if (!selectedIdsRef.current.length) return;
    applyEdit(regionsRef.current.filter((region) => !selectedIdsRef.current.includes(region.id)));
    selectedIdsRef.current = [];
    setSelectedIds([]);
  }

  function addCenteredRegion() {
    const created = createManualRegion(defaultManualBounds(regions.length));
    applyEdit([...regionsRef.current, created]);
    selectOnly(created.id);
    setDrawMode(false);
  }

  function splitSelected(direction: SplitDirection) {
    if (!selectedRegion) return;
    const index = regionsRef.current.findIndex((region) => region.id === selectedRegion.id);
    if (index < 0) return;
    const split = splitRegion(selectedRegion, direction);
    applyEdit([
      ...regionsRef.current.slice(0, index),
      split[0],
      split[1],
      ...regionsRef.current.slice(index + 1),
    ]);
    const nextSelectedIds = [split[0].id, split[1].id];
    selectedIdsRef.current = nextSelectedIds;
    setSelectedIds(nextSelectedIds);
  }

  function mergeSelected() {
    if (selectedRegions.length < 2) return;
    const merged = mergeRegions(selectedRegions);
    if (!merged) return;
    const selected = new Set(selectedIds);
    const firstIndex = regionsRef.current.findIndex((region) => selected.has(region.id));
    const remaining = regionsRef.current.filter((region) => !selected.has(region.id));
    const insertAt = Math.max(
      0,
      firstIndex -
        regionsRef.current.slice(0, firstIndex).filter((region) => selected.has(region.id)).length,
    );
    applyEdit([...remaining.slice(0, insertAt), merged, ...remaining.slice(insertAt)]);
    selectOnly(merged.id);
  }

  function updateSelectedBounds(key: keyof RegionBounds, rawValue: string) {
    if (!selectedRegion) return;
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    const bounds = { ...regionBounds(selectedRegion), [key]: clampUnit(value) };
    applyEdit(replaceOne(regionsRef.current, replaceRegionBounds(selectedRegion, bounds)));
  }

  function handleShortcuts(event: KeyboardEvent<HTMLElement>) {
    if (hasTextInputFocus(event.target)) return;
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === 'z') {
      event.preventDefault();
      if (event.shiftKey) redoEdit();
      else undo();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && key === 'y') {
      event.preventDefault();
      redoEdit();
      return;
    }
    if (key === 'delete' || key === 'backspace') {
      event.preventDefault();
      deleteSelected();
      return;
    }
    if (!selectedRegion) return;
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
    const current = regionsRef.current.find((region) => region.id === selectedRegion.id);
    if (current) applyEdit(replaceOne(regionsRef.current, moveRegion(current, delta)));
  }

  async function persistChanges(): Promise<boolean> {
    if (!pageId || !snapshot || !asset || !csrfToken) {
      await reconnect();
      setMessage('Сессия обновляется. Повторите сохранение областей.');
      return false;
    }
    if (!isDirty) return true;
    setBusy('save');
    setMessage(null);
    const response = await replaceRegions(pageId, snapshot.revision, regionsRef.current, csrfToken);
    setBusy(null);
    if (!response.ok) {
      if (response.error.code === 'revision_conflict') {
        void saveRegionDraft({
          pageId,
          preparedAssetId: asset.id,
          baseRevision: snapshot.revision,
          regions: cloneRegions(regionsRef.current),
          history: cloneHistory(historyRef.current),
          redo: cloneHistory(redoRef.current),
          selectedIds: selectedIdsRef.current,
          updatedAt: new Date().toISOString(),
        }).catch(() => undefined);
        setMessage(
          'Версия страницы изменилась на сервере. Локальные правки сохранены в этом браузере; обновите серверную версию и решите конфликт явно.',
        );
      } else {
        setMessage(response.error.message);
      }
      return false;
    }
    replaceSnapshot(response.value);
    replaceLocalRegions(response.value.regions);
    replaceHistory([]);
    replaceRedo([]);
    const nextSelectedIds = response.value.regions.slice(0, 1).map((region) => region.id);
    selectedIdsRef.current = nextSelectedIds;
    setSelectedIds(nextSelectedIds);
    setRecoveredDraft(null);
    await removeRegionDraft(pageId).catch(() => undefined);
    setMessage('Области сохранены на сервере.');
    return true;
  }

  async function saveAndConfirm() {
    if (!pageId || !snapshot || !csrfToken) {
      await reconnect();
      setMessage('Сессия обновляется. Повторите подтверждение областей.');
      return;
    }
    if (jobId && (!job || job.state !== 'awaiting_region_review')) {
      setMessage(
        'CRAFT-задача ещё не перешла к проверке областей. Обновите состояние перед подтверждением.',
      );
      return;
    }
    if (!(await persistChanges())) return;
    const saved = await getRegions(pageId);
    if (!saved.ok) {
      setMessage('Не удалось прочитать сохранённую версию областей перед подтверждением.');
      return;
    }
    const confirmedSnapshot = saved.value;
    setBusy('confirm');
    setMessage(null);
    const response = await confirmRegions(
      pageId,
      confirmedSnapshot.revision,
      csrfToken,
      jobId && job ? { id: jobId, revision: job.revision } : undefined,
    );
    setBusy(null);
    if (!response.ok) {
      setMessage(
        response.error.code === 'revision_conflict' ||
          response.error.code === 'job_not_awaiting_region_review'
          ? 'Состояние страницы или задачи изменилось. Обновите данные, прежде чем подтверждать области.'
          : response.error.message,
      );
      return;
    }
    replaceSnapshot(response.value);
    replaceLocalRegions(response.value.regions);
    replaceHistory([]);
    replaceRedo([]);
    setRecoveredDraft(null);
    await removeRegionDraft(pageId).catch(() => undefined);
    setMessage(
      response.value.resumedJobId
        ? 'Области подтверждены: durable-задача продолжила распознавание строк.'
        : 'Области подтверждены на сервере.',
    );
    if (jobId) {
      const refreshedJob = await getJobSnapshot(jobId);
      if (refreshedJob.ok) setJob(refreshedJob.value);
      navigate(`/result?jobId=${encodeURIComponent(jobId)}`, { replace: true });
    }
  }

  async function reloadServerVersion() {
    await load({ consultDraft: false, preserveCurrentDraft: true });
    setMessage('Серверная версия загружена. Локальный черновик можно восстановить явно.');
  }

  function restoreRecoveredDraft() {
    if (!recoveredDraft) return;
    replaceLocalRegions(recoveredDraft.regions);
    replaceHistory(recoveredDraft.history);
    replaceRedo(recoveredDraft.redo);
    selectedIdsRef.current = [...recoveredDraft.selectedIds];
    setSelectedIds([...recoveredDraft.selectedIds]);
    setRecoveredDraft(null);
    setMessage(
      'Локальные правки восстановлены поверх текущей серверной версии. Перед сохранением проверьте области.',
    );
  }

  if (!pageId) {
    return (
      <section className="regions-page regions-page--empty" tabIndex={-1}>
        <Card>
          <h1>Выберите страницу для проверки областей</h1>
          <p>Сначала подготовьте изображение и поставьте CRAFT-задачу в очередь.</p>
          <Link className="ui-button ui-button--primary" to="/capture">
            Добавить страницу
          </Link>
        </Card>
      </section>
    );
  }

  if (!asset || !snapshot) {
    return (
      <section className="regions-page regions-page--empty" tabIndex={-1}>
        <p role="status">
          {loading ? 'Загружаем области CRAFT…' : 'Подготавливаем проверку областей…'}
        </p>
        {message ? <p role="alert">{message}</p> : null}
        {!loading && message ? (
          <Button variant="secondary" onClick={() => void load()}>
            Повторить
          </Button>
        ) : null}
      </section>
    );
  }

  const selectedBounds = selectedRegion ? regionBounds(selectedRegion) : null;
  const previewBox =
    drawPreview && imageSize
      ? {
          start: normalizedToCanvas({ x: drawPreview.minX, y: drawPreview.minY }, imageSize, view),
          end: normalizedToCanvas({ x: drawPreview.maxX, y: drawPreview.maxY }, imageSize, view),
        }
      : null;
  const jobStatus = job
    ? job.state === 'awaiting_region_review'
      ? 'CRAFT завершил поиск строк: подтвердите области, чтобы продолжить распознавание.'
      : `Задача: ${job.stage}. Серверное состояние будет обновлено автоматически.`
    : 'Проверяйте реальные области, возвращённые сервером CRAFT.';

  return (
    <section className="regions-page" tabIndex={-1} onKeyDown={handleShortcuts}>
      <header className="page-heading regions-heading">
        <div>
          <h1>Проверка строк</h1>
          <p>Исправьте области CRAFT перед распознаванием текста.</p>
        </div>
        <div className="preparation-heading__actions">
          <Link
            className="ui-button ui-button--secondary"
            to={`/preparation?pageId=${encodeURIComponent(pageId)}`}
          >
            Назад
          </Link>
          <Button
            isLoading={busy === 'confirm'}
            disabled={busy !== null || (Boolean(jobId) && job?.state !== 'awaiting_region_review')}
            onClick={() => void saveAndConfirm()}
          >
            Распознать текст
          </Button>
        </div>
      </header>

      <motion.p
        className={`regions-job-status ${job?.state === 'awaiting_region_review' ? 'regions-job-status--ready' : ''}`}
        role="status"
        aria-live="polite"
        initial={canAnimate ? { opacity: 0, y: 6 } : false}
        animate={{ opacity: 1, y: 0 }}
        transition={motionTransition.enter}
      >
        {jobStatus}
      </motion.p>

      {recoveredDraft ? (
        <aside className="regions-conflict" role="status">
          <div>
            <strong>Найден локальный черновик областей.</strong>
            <p>Он основан на другой версии страницы и не будет применён автоматически.</p>
          </div>
          <div className="regions-inline-actions">
            <Button variant="secondary" onClick={restoreRecoveredDraft}>
              Восстановить локальные правки
            </Button>
            <Button
              variant="quiet"
              onClick={() => {
                setRecoveredDraft(null);
                void removeRegionDraft(pageId);
              }}
            >
              Удалить черновик
            </Button>
          </div>
        </aside>
      ) : null}

      <div className="regions-layout">
        <section className="regions-workspace" aria-label="Изображение и области CRAFT">
          <div
            className={`regions-canvas ${drawMode ? 'regions-canvas--drawing' : ''}`}
            ref={viewport}
            onPointerDown={startCanvasPointer}
            onPointerMove={moveCanvasPointer}
            onPointerUp={endCanvasPointer}
            onPointerCancel={(event) => endCanvasPointer(event, true)}
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
              className="regions-canvas__image"
              draggable={false}
              src={asset.previewUrl}
              alt="Подготовленная страница для проверки областей распознавания"
              style={{
                width: asset.width,
                height: asset.height,
                transform: `translate(${view.offsetX}px, ${view.offsetY}px) scale(${view.scale})`,
              }}
            />
            <svg
              className="regions-canvas__overlay"
              width={asset.width}
              height={asset.height}
              viewBox="0 0 1 1"
              preserveAspectRatio="none"
              aria-hidden="true"
              style={{
                transform: `translate(${view.offsetX}px, ${view.offsetY}px) scale(${view.scale})`,
              }}
            >
              {regions.map((region, index) => {
                const bounds = regionBounds(region);
                const selected = selectedIds.includes(region.id);
                return (
                  <g
                    key={region.id}
                    className={
                      selected ? 'regions-region regions-region--selected' : 'regions-region'
                    }
                  >
                    <polygon
                      className={`regions-region__shape regions-region__shape--${region.source}`}
                      points={polygonPath(region)}
                      vectorEffect="non-scaling-stroke"
                      onPointerDown={(event) => startRegionMove(event, region)}
                      onPointerMove={moveRegionPointer}
                      onPointerUp={endRegionPointer}
                      onPointerCancel={(event) => endRegionPointer(event, true)}
                    />
                    <g
                      className="regions-region__number"
                      transform={`translate(${bounds.minX} ${bounds.minY})`}
                    >
                      <circle r="0.022" vectorEffect="non-scaling-stroke" />
                      <text x="0" y="0.007" textAnchor="middle" fontSize="0.022">
                        {index + 1}
                      </text>
                    </g>
                  </g>
                );
              })}
            </svg>
            {previewBox ? (
              <span
                className="regions-draw-preview"
                aria-hidden="true"
                style={{
                  left: previewBox.start.x,
                  top: previewBox.start.y,
                  width: previewBox.end.x - previewBox.start.x,
                  height: previewBox.end.y - previewBox.start.y,
                }}
              />
            ) : null}
            {selectedBounds && imageSize
              ? (
                  [
                    ['northwest', selectedBounds.minX, selectedBounds.minY],
                    ['northeast', selectedBounds.maxX, selectedBounds.minY],
                    ['southeast', selectedBounds.maxX, selectedBounds.maxY],
                    ['southwest', selectedBounds.minX, selectedBounds.maxY],
                  ] as const
                ).map(([corner, x, y]) => {
                  const position = normalizedToCanvas({ x, y }, imageSize, view);
                  return (
                    <button
                      key={corner}
                      className="regions-handle"
                      aria-label={`Изменить размер выбранной области: ${corner}`}
                      style={{ left: position.x, top: position.y }}
                      onPointerDown={(event) => startResize(event, corner)}
                      onPointerMove={moveResize}
                      onPointerUp={endResize}
                      onPointerCancel={(event) => endResize(event, true)}
                    />
                  );
                })
              : null}
          </div>
          <div
            className="regions-canvas-toolbar"
            aria-label="Вид изображения и действия с областями"
          >
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
            <Button variant="secondary" onClick={resetView}>
              По размеру
            </Button>
            <Button
              variant={drawMode ? 'primary' : 'secondary'}
              aria-pressed={drawMode}
              onClick={() => setDrawMode((current) => !current)}
            >
              {drawMode ? 'Отменить рисование' : 'Нарисовать область'}
            </Button>
          </div>
          <p className="regions-canvas-help">
            Потяните фон для перемещения, колесо/щипок — для масштаба. Для добавления включите
            рисование; у каждой области есть полноценная клавиатурная альтернатива справа.
          </p>
        </section>

        <aside className="regions-sidebar" aria-label="Список и управление областями">
          <Card className="regions-actions-card">
            <div>
              <p className="eyebrow">Области</p>
              <h2>
                {regions.length} {regions.length === 1 ? 'строка' : 'строк'}
              </h2>
            </div>
            <div className="regions-inline-actions">
              <Button variant="secondary" onClick={addCenteredRegion}>
                Добавить область
              </Button>
              <Button variant="quiet" disabled={!history.length} onClick={undo}>
                Отменить
              </Button>
              <Button variant="quiet" disabled={!redo.length} onClick={redoEdit}>
                Повторить
              </Button>
            </div>
          </Card>

          <Card className="regions-list-card">
            <h2 className="visually-hidden">Список областей</h2>
            {regions.length ? (
              <ol className="regions-list">
                {regions.map((region, index) => (
                  <li key={region.id}>
                    <button
                      className={
                        selectedIds.includes(region.id)
                          ? 'regions-list__item regions-list__item--selected'
                          : 'regions-list__item'
                      }
                      type="button"
                      aria-pressed={selectedIds.includes(region.id)}
                      onClick={(event) => {
                        if (event.shiftKey) toggleSelection(region.id);
                        else selectOnly(region.id);
                      }}
                    >
                      <span className="regions-list__number">{index + 1}</span>
                      <span className="regions-list__copy">
                        <strong>{regionLabel(region, index)}</strong>
                        <span>
                          {region.flags.length ? region.flags.join(', ') : 'Без review flags'}
                        </span>
                      </span>
                      <Badge tone={region.source === 'craft' ? 'info' : 'warning'}>
                        {sourceLabel(region.source)}
                      </Badge>
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="regions-empty-list">
                CRAFT ещё не вернул строк или области были удалены вручную.
              </p>
            )}
          </Card>

          <Card className="regions-properties-card">
            <p className="eyebrow">Выбранные области</p>
            {selectedRegion && selectedBounds ? (
              <>
                <h2>
                  {selectedRegions.length > 1
                    ? `Выбрано: ${selectedRegions.length}`
                    : 'Свойства строки'}
                </h2>
                {selectedRegions.length === 1 ? (
                  <div className="regions-fields">
                    {(
                      [
                        ['minX', 'Левый край'],
                        ['minY', 'Верхний край'],
                        ['maxX', 'Правый край'],
                        ['maxY', 'Нижний край'],
                      ] as const
                    ).map(([key, label]) => (
                      <label key={key}>
                        {label}
                        <input
                          type="number"
                          min="0"
                          max="1"
                          step="0.001"
                          value={selectedBounds[key]}
                          onChange={(event) => updateSelectedBounds(key, event.target.value)}
                        />
                      </label>
                    ))}
                  </div>
                ) : (
                  <p>Выберите две или больше областей с Shift, чтобы объединить их.</p>
                )}
                <p className="regions-properties__meta">
                  Источник: {sourceLabel(selectedRegion.source)}. Flags:{' '}
                  {selectedRegion.flags.length ? selectedRegion.flags.join(', ') : 'нет'}.
                </p>
                <div className="regions-button-grid">
                  <Button
                    variant="secondary"
                    onClick={() => splitSelected('horizontal')}
                    disabled={selectedRegions.length !== 1}
                  >
                    Разделить сверху/снизу
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => splitSelected('vertical')}
                    disabled={selectedRegions.length !== 1}
                  >
                    Разделить слева/справа
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={mergeSelected}
                    disabled={selectedRegions.length < 2}
                  >
                    Объединить выбранные
                  </Button>
                  <Button variant="danger" onClick={deleteSelected} disabled={!selectedIds.length}>
                    Удалить выбранные
                  </Button>
                </div>
                {selectedRegions.length === 1 ? (
                  <div className="regions-order-actions">
                    <Button
                      variant="quiet"
                      disabled={selectedRegion.readingOrder === 0}
                      onClick={() =>
                        applyEdit(moveReadingOrder(regionsRef.current, selectedRegion.id, -1))
                      }
                    >
                      Раньше в порядке
                    </Button>
                    <Button
                      variant="quiet"
                      disabled={selectedRegion.readingOrder === regions.length - 1}
                      onClick={() =>
                        applyEdit(moveReadingOrder(regionsRef.current, selectedRegion.id, 1))
                      }
                    >
                      Позже в порядке
                    </Button>
                  </div>
                ) : null}
              </>
            ) : (
              <p>Выберите область на изображении или в доступном списке.</p>
            )}
          </Card>

          <Card className="regions-save-card">
            <p className="eyebrow">Состояние</p>
            <h2>{isDirty ? 'Есть несохранённые правки' : 'Сохранено на сервере'}</h2>
            <div className="regions-save-actions">
              <Button
                variant="secondary"
                disabled={busy !== null}
                onClick={() => void reloadServerVersion()}
              >
                Версия сервера
              </Button>
            </div>
            {message ? (
              <p className="regions-message" role="alert">
                {message}
              </p>
            ) : null}
          </Card>
        </aside>
      </div>
    </section>
  );
}
