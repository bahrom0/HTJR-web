import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from 'react';

import { detectDemoRegions, getDemoPreset, imageSha256, saveDemoPreset, type DemoRegion } from '@features/demo/api';
import { createManualRegion, regionBounds, type NormalizedPoint, type Region, type ResizeCorner } from '@features/regions/model';

const TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
type EditMode = 'move' | ResizeCorner | 'rotate';
type Action = { mode: EditMode; start: NormalizedPoint; originals: Map<string, DemoRegion> };
type Marquee = { start: NormalizedPoint; current: NormalizedPoint };

function editable(region: DemoRegion): Region {
  return { id: region.id, polygon: region.polygon, readingOrder: region.reading_order, revision: 1, source: 'adjusted', flags: [], detectorVersion: null, detectorScore: null };
}
function ordered(regions: readonly DemoRegion[]): DemoRegion[] { return regions.map((region, reading_order) => ({ ...region, reading_order })); }
function boundsOf(points: readonly NormalizedPoint[]) {
  return { minX: Math.min(...points.map((point) => point.x)), minY: Math.min(...points.map((point) => point.y)), maxX: Math.max(...points.map((point) => point.x)), maxY: Math.max(...points.map((point) => point.y)) };
}
function movePolygon(polygon: readonly NormalizedPoint[], delta: NormalizedPoint): readonly NormalizedPoint[] {
  const bounds = boundsOf(polygon); const dx = Math.max(-bounds.minX, Math.min(1 - bounds.maxX, delta.x)); const dy = Math.max(-bounds.minY, Math.min(1 - bounds.maxY, delta.y));
  return polygon.map((point) => ({ x: point.x + dx, y: point.y + dy }));
}
function rotatePolygon(polygon: readonly NormalizedPoint[], center: NormalizedPoint, radians: number): readonly NormalizedPoint[] {
  const cosine = Math.cos(radians); const sine = Math.sin(radians);
  return polygon.map((point) => { const x = point.x - center.x; const y = point.y - center.y; return { x: Math.max(0, Math.min(1, center.x + x * cosine - y * sine)), y: Math.max(0, Math.min(1, center.y + x * sine + y * cosine)) }; });
}
function isInside(item: ReturnType<typeof boundsOf>, area: ReturnType<typeof boundsOf>) {
  return item.minX >= area.minX && item.maxX <= area.maxX && item.minY >= area.minY && item.maxY <= area.maxY;
}

export default function DemoRoute() {
  const input = useRef<HTMLInputElement>(null); const action = useRef<Action | null>(null);
  const panAction = useRef<{ x: number; y: number; origin: NormalizedPoint } | null>(null);
  const [file, setFile] = useState<File | null>(null); const [preview, setPreview] = useState<string | null>(null); const [sha, setSha] = useState('');
  const [regions, setRegions] = useState<DemoRegion[]>([]); const [selectedIds, setSelectedIds] = useState<string[]>([]); const [marquee, setMarquee] = useState<Marquee | null>(null);
  const [zoom, setZoom] = useState(1); const [pan, setPan] = useState<NormalizedPoint>({ x: 0, y: 0 }); const [message, setMessage] = useState('Выберите изображение.'); const [busy, setBusy] = useState(false);
  const selectedId = selectedIds[0] ?? null; const selected = useMemo(() => regions.find((item) => item.id === selectedId) ?? null, [regions, selectedId]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => { const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Delete' && selectedIds.length && !busy && !(event.target instanceof HTMLTextAreaElement)) { event.preventDefault(); setRegions((items) => ordered(items.filter((item) => !selectedIds.includes(item.id)))); setSelectedIds([]); } }; window.addEventListener('keydown', onKeyDown); return () => window.removeEventListener('keydown', onKeyDown); }, [busy, selectedIds]);

  async function choose(next: File | undefined) {
    if (!next) return; if (!TYPES.has(next.type) || next.size === 0 || next.size > 10 * 1024 * 1024) return setMessage('Нужен JPEG, PNG или WebP до 10 МБ.');
    if (preview) URL.revokeObjectURL(preview); setFile(next); setPreview(URL.createObjectURL(next)); setRegions([]); setSelectedIds([]); setZoom(1); setPan({ x: 0, y: 0 }); setBusy(true);
    const digest = await imageSha256(next); setSha(digest); const existing = await getDemoPreset(digest);
    if (existing.ok) { setRegions(ordered(existing.value.regions)); setSelectedIds(existing.value.regions[0] ? [existing.value.regions[0].id] : []); setMessage('Шаблон загружен. Области и тексты можно изменить.'); } else setMessage(existing.error.code === 'demo_preset_not_found' ? 'Нажмите «Найти строки».' : existing.error.message); setBusy(false);
  }
  async function findLines() { if (!file) return; setBusy(true); setMessage('Kraken ищет строки…'); const result = await detectDemoRegions(file); if (result.ok) { const next = ordered(result.value.regions); setRegions(next); setSelectedIds(next[0] ? [next[0].id] : []); setMessage(`Найдено строк: ${next.length}. Проверьте области и заполните текст.`); } else setMessage(result.error.message); setBusy(false); }
  function point(event: PointerEvent<SVGSVGElement>): NormalizedPoint { const bounds = event.currentTarget.getBoundingClientRect(); return { x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)) }; }
  function finish() { action.current = null; panAction.current = null; setMarquee(null); }
  function beginRegion(event: PointerEvent<SVGElement>, item: DemoRegion, mode: EditMode) {
    event.stopPropagation(); const next = event.shiftKey ? (selectedIds.includes(item.id) ? selectedIds.filter((id) => id !== item.id) : [...selectedIds, item.id]) : selectedIds.includes(item.id) ? selectedIds : [item.id]; setSelectedIds(next); if (mode !== 'move' && next.length !== 1) return;
    const svg = event.currentTarget.ownerSVGElement; if (!svg) return; const bounds = svg.getBoundingClientRect(); action.current = { mode, originals: new Map(regions.filter((region) => next.includes(region.id)).map((region) => [region.id, region])), start: { x: (event.clientX - bounds.left) / bounds.width, y: (event.clientY - bounds.top) / bounds.height } }; svg.setPointerCapture(event.pointerId);
  }
  function beginCanvas(event: PointerEvent<SVGSVGElement>) {
    if (event.target !== event.currentTarget || busy) return;
    if (event.button === 1) { panAction.current = { x: event.clientX, y: event.clientY, origin: pan }; event.currentTarget.setPointerCapture(event.pointerId); return; }
    const start = point(event); if (!event.shiftKey) setSelectedIds([]); setMarquee({ start, current: start }); event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    if (panAction.current) { setPan({ x: panAction.current.origin.x + event.clientX - panAction.current.x, y: panAction.current.origin.y + event.clientY - panAction.current.y }); return; }
    const current = action.current; if (!current) { if (marquee) setMarquee({ ...marquee, current: point(event) }); return; } const nextPoint = point(event); const dx = nextPoint.x - current.start.x; const dy = nextPoint.y - current.start.y;
    setRegions((items) => items.map((item) => { const original = current.originals.get(item.id); if (!original) return item; const base = editable(original); let polygon = base.polygon;
      if (current.mode === 'move') polygon = movePolygon(base.polygon, { x: dx, y: dy });
      else if (current.mode === 'rotate') { const bounds = regionBounds(base); const center = { x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 }; polygon = rotatePolygon(base.polygon, center, Math.atan2(nextPoint.y - center.y, nextPoint.x - center.x) - Math.atan2(current.start.y - center.y, current.start.x - center.x)); }
      else { const bounds = regionBounds(base); const next = { ...bounds }; if (current.mode.includes('west')) next.minX = Math.min(nextPoint.x, bounds.maxX - 0.01); if (current.mode.includes('east')) next.maxX = Math.max(nextPoint.x, bounds.minX + 0.01); if (current.mode.includes('north')) next.minY = Math.min(nextPoint.y, bounds.maxY - 0.01); if (current.mode.includes('south')) next.maxY = Math.max(nextPoint.y, bounds.minY + 0.01); polygon = [{ x: next.minX, y: next.minY }, { x: next.maxX, y: next.minY }, { x: next.maxX, y: next.maxY }, { x: next.minX, y: next.maxY }]; }
      return { ...item, polygon }; }));
  }
  function endPointer(event: PointerEvent<SVGSVGElement>) { if (marquee) { const area = boundsOf([{ x: marquee.start.x, y: marquee.start.y }, { x: marquee.current.x, y: marquee.start.y }, { x: marquee.current.x, y: marquee.current.y }, { x: marquee.start.x, y: marquee.current.y }]); const found = regions.filter((item) => isInside(boundsOf(item.polygon), area)).map((item) => item.id); setSelectedIds((ids) => event.shiftKey ? [...new Set([...ids, ...found])] : found); } finish(); }
  function addRegion() { const base = createManualRegion({ minX: 0.15, minY: 0.45, maxX: 0.85, maxY: 0.55 }); const item: DemoRegion = { id: base.id, polygon: base.polygon, reading_order: regions.length, text: '' }; setRegions((items) => [...items, item]); setSelectedIds([item.id]); }
  function removeSelected() { setRegions((items) => ordered(items.filter((item) => !selectedIds.includes(item.id)))); setSelectedIds([]); }
  async function save() { if (!file || !sha || regions.length === 0) return; if (regions.some((item) => !item.text.trim())) return setMessage('Введите текст для каждой области.'); setBusy(true); const result = await saveDemoPreset(sha, ordered(regions), file.name); setMessage(result.ok ? 'Сохранено. Шаблон готов для обычного интерфейса.' : result.error.message); setBusy(false); }
  function drop(event: DragEvent<HTMLDivElement>) { event.preventDefault(); void choose(event.dataTransfer.files[0]); }
  const marqueeBounds = marquee ? boundsOf([{ x: marquee.start.x, y: marquee.start.y }, { x: marquee.current.x, y: marquee.start.y }, { x: marquee.current.x, y: marquee.current.y }, { x: marquee.start.x, y: marquee.current.y }]) : null;

  return <div className="demo-page demo-page--regions">
    <header className="demo-page__header"><p className="demo-page__eyebrow">Tajik HTR Studio · demo preset</p><h1>Шаблон областей и текста</h1><p>Настройте области, масштаб и готовый текст. Сохранённый шаблон используется для имитации генерации.</p></header>
    <section className="demo-page__grid demo-page__grid--three">
      <article className="demo-card demo-upload-card"><div className="demo-card__heading"><div><span className="demo-card__kicker">01 · файл</span><h2>Фотография</h2></div></div><div className={`demo-dropzone ${preview ? 'has-preview' : ''}`} role="button" tabIndex={0} onClick={() => input.current?.click()} onDragOver={(e) => e.preventDefault()} onDrop={drop}>{preview && file ? <div className="demo-dropzone__preview"><img src={preview} alt="Предпросмотр"/><div><strong>{file.name}</strong><span>{sha ? `${sha.slice(0, 12)}…` : 'SHA-256…'}</span></div></div> : <div className="demo-dropzone__empty"><span className="demo-dropzone__icon">↑</span><strong>Добавьте фотографию</strong></div>}<input ref={input} className="visually-hidden" type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => void choose(e.target.files?.[0])}/></div><button className="ui-button" type="button" disabled={!file || busy} onClick={() => void findLines()}>{busy ? 'Подождите…' : 'Найти строки'}</button></article>
      <article className="demo-card demo-regions-card"><div className="demo-card__heading"><div><span className="demo-card__kicker">02 · области</span><h2>Разметка строк</h2></div><span className="demo-card__status">{regions.length}</span></div><div className="demo-editor-toolbar"><button type="button" onClick={() => setZoom((value) => Math.min(4, value + 0.25))}>＋</button><span>{Math.round(zoom * 100)}%</span><button type="button" onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))}>−</button><button type="button" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }}>Сбросить</button></div><div className="demo-region-canvas" onWheel={(event) => { event.preventDefault(); setZoom((value) => Math.max(0.5, Math.min(4, value - event.deltaY * 0.001))); }}>{preview ? <div className="demo-editor-viewport"><div className="demo-editor-stage" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}><img src={preview} alt="Страница с областями"/><svg viewBox="0 0 1 1" preserveAspectRatio="none" onPointerDown={beginCanvas} onPointerMove={move} onPointerUp={endPointer} onPointerCancel={finish}>{regions.map((item) => { const bounds = regionBounds(editable(item)); const active = selectedIds.includes(item.id); const center = { x: (bounds.minX + bounds.maxX) / 2, y: (bounds.minY + bounds.maxY) / 2 }; const corners: [ResizeCorner, number, number][] = [['northwest', bounds.minX, bounds.minY], ['northeast', bounds.maxX, bounds.minY], ['southeast', bounds.maxX, bounds.maxY], ['southwest', bounds.minX, bounds.maxY]]; return <g key={item.id}><polygon points={item.polygon.map((p) => `${p.x},${p.y}`).join(' ')} className={active ? 'is-selected' : ''} onPointerDown={(e) => beginRegion(e, item, 'move')}/><g className="demo-region-label" transform={`translate(${bounds.minX} ${Math.max(0.025, bounds.minY - 0.006)})`}><rect x="-.004" y="-.021" width=".035" height=".028" rx=".006"/><text x=".004" y="-.002">{item.reading_order + 1}</text></g>{active && selectedIds.length === 1 ? <><circle className="demo-rotate-handle" cx={center.x} cy={Math.max(0.035, bounds.minY - 0.055)} r="0.012" onPointerDown={(e) => beginRegion(e, item, 'rotate')}/>{corners.map(([corner, x, y]) => <circle key={corner} cx={x} cy={y} r="0.009" onPointerDown={(e) => beginRegion(e, item, corner)}/>)}</> : null}</g>; })}{marqueeBounds ? <rect className="demo-selection-marquee" x={marqueeBounds.minX} y={marqueeBounds.minY} width={marqueeBounds.maxX - marqueeBounds.minX} height={marqueeBounds.maxY - marqueeBounds.minY}/> : null}</svg></div></div> : <span>Сначала выберите фотографию.</span>}</div><p className="demo-editor-hint">ЛКМ по свободному месту — рамочное выделение · Shift — добавить к выделению · Delete — удалить · кружок сверху — повернуть · средняя кнопка — переместить</p><div className="demo-region-actions"><button className="ui-button ui-button--secondary" type="button" disabled={!preview} onClick={addRegion}>Добавить область</button><button className="ui-button ui-button--quiet" type="button" disabled={selectedIds.length === 0} onClick={removeSelected}>Удалить выбранные</button></div></article>
      <article className="demo-card demo-result-card"><div className="demo-card__heading"><div><span className="demo-card__kicker">03 · текст</span><h2>{selected ? `Строка ${selected.reading_order + 1}` : 'Выберите область'}</h2></div></div><textarea className="demo-result-text" value={selected?.text ?? ''} disabled={!selected || busy || selectedIds.length !== 1} onChange={(e) => setRegions((items) => items.map((item) => item.id === selectedId ? { ...item, text: e.target.value } : item))} placeholder="Текст выбранной строки"/><div className="demo-line-list">{regions.map((item) => <button type="button" className={selectedIds.includes(item.id) ? 'is-selected' : ''} key={item.id} onClick={() => setSelectedIds([item.id])}><b>{item.reading_order + 1}</b><span>{item.text || 'Текст не заполнен'}</span></button>)}</div><div className="demo-result-footer"><span>{message}</span><button className="ui-button" type="button" disabled={busy || !sha || regions.length === 0} onClick={() => void save()}>Сохранить шаблон</button></div></article>
    </section>
  </div>;
}
