export type NormalizedPoint = Readonly<{ x: number; y: number }>;

export type RegionSource = 'craft' | 'kraken' | 'manual' | 'adjusted';
export type ResizeCorner = 'northwest' | 'northeast' | 'southeast' | 'southwest';
export type SplitDirection = 'horizontal' | 'vertical';

export type Region = Readonly<{
  id: string;
  polygon: readonly NormalizedPoint[];
  readingOrder: number;
  revision: number;
  source: RegionSource;
  flags: readonly string[];
  detectorVersion: string | null;
  detectorScore: number | null;
}>;

export type RegionSnapshot = Readonly<{
  pageId: string;
  revision: number;
  confirmed: boolean;
  regions: readonly Region[];
  resumedJobId: string | null;
}>;

export type RegionDraft = Readonly<{
  pageId: string;
  preparedAssetId: string;
  baseRevision: number;
  regions: readonly Region[];
  history: readonly (readonly Region[])[];
  redo: readonly (readonly Region[])[];
  selectedIds: readonly string[];
  updatedAt: string;
}>;

export type RegionBounds = Readonly<{
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}>;

const MIN_REGION_EDGE = 0.01;

export function clampUnit(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

export function cloneRegion(region: Region): Region {
  return {
    ...region,
    polygon: region.polygon.map((point) => ({ ...point })),
    flags: [...region.flags],
  };
}

export function cloneRegions(regions: readonly Region[]): Region[] {
  return regions.map(cloneRegion);
}

export function regionBounds(region: Region): RegionBounds {
  const xs = region.polygon.map((point) => point.x);
  const ys = region.polygon.map((point) => point.y);
  return {
    minX: Math.min(...xs),
    minY: Math.min(...ys),
    maxX: Math.max(...xs),
    maxY: Math.max(...ys),
  };
}

export function normalizeBounds(bounds: RegionBounds): RegionBounds {
  const minX = clampUnit(Math.min(bounds.minX, bounds.maxX));
  const minY = clampUnit(Math.min(bounds.minY, bounds.maxY));
  const maxX = clampUnit(Math.max(bounds.minX, bounds.maxX));
  const maxY = clampUnit(Math.max(bounds.minY, bounds.maxY));
  const constrainedMaxX = Math.max(minX + MIN_REGION_EDGE, maxX);
  const constrainedMaxY = Math.max(minY + MIN_REGION_EDGE, maxY);
  return {
    minX: Math.min(minX, 1 - MIN_REGION_EDGE),
    minY: Math.min(minY, 1 - MIN_REGION_EDGE),
    maxX: Math.min(1, constrainedMaxX),
    maxY: Math.min(1, constrainedMaxY),
  };
}

export function rectanglePolygon(bounds: RegionBounds): readonly NormalizedPoint[] {
  const normalized = normalizeBounds(bounds);
  return [
    { x: normalized.minX, y: normalized.minY },
    { x: normalized.maxX, y: normalized.minY },
    { x: normalized.maxX, y: normalized.maxY },
    { x: normalized.minX, y: normalized.maxY },
  ];
}

function uniqueFlags(flags: readonly string[]): readonly string[] {
  return [...new Set(flags.filter((flag) => flag.trim().length > 0))].slice(0, 32);
}

function adjusted(
  region: Region,
  polygon: readonly NormalizedPoint[],
  flags = region.flags,
): Region {
  return {
    ...region,
    polygon,
    source: region.source === 'manual' ? 'manual' : 'adjusted',
    flags: uniqueFlags(flags),
  };
}

export function withContiguousOrder(regions: readonly Region[]): Region[] {
  return regions.map((region, readingOrder) => ({ ...cloneRegion(region), readingOrder }));
}

export function moveRegion(region: Region, delta: NormalizedPoint): Region {
  const bounds = regionBounds(region);
  const width = bounds.maxX - bounds.minX;
  const height = bounds.maxY - bounds.minY;
  const minX = Math.max(0, Math.min(1 - width, bounds.minX + delta.x));
  const minY = Math.max(0, Math.min(1 - height, bounds.minY + delta.y));
  return adjusted(
    region,
    rectanglePolygon({ minX, minY, maxX: minX + width, maxY: minY + height }),
  );
}

export function resizeRegion(region: Region, corner: ResizeCorner, point: NormalizedPoint): Region {
  const bounds = regionBounds(region);
  const next = { ...bounds };
  const x = clampUnit(point.x);
  const y = clampUnit(point.y);
  if (corner === 'northwest' || corner === 'southwest')
    next.minX = Math.min(x, bounds.maxX - MIN_REGION_EDGE);
  if (corner === 'northeast' || corner === 'southeast')
    next.maxX = Math.max(x, bounds.minX + MIN_REGION_EDGE);
  if (corner === 'northwest' || corner === 'northeast')
    next.minY = Math.min(y, bounds.maxY - MIN_REGION_EDGE);
  if (corner === 'southwest' || corner === 'southeast')
    next.maxY = Math.max(y, bounds.minY + MIN_REGION_EDGE);
  return adjusted(region, rectanglePolygon(next));
}

export function replaceRegionBounds(region: Region, bounds: RegionBounds): Region {
  return adjusted(region, rectanglePolygon(bounds));
}

export function createManualRegion(bounds: RegionBounds, id = createRegionId()): Region {
  return {
    id,
    polygon: rectanglePolygon(bounds),
    readingOrder: 0,
    revision: 0,
    source: 'manual',
    flags: [],
    detectorVersion: null,
    detectorScore: null,
  };
}

export function createRegionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `manual-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function splitRegion(region: Region, direction: SplitDirection): readonly [Region, Region] {
  const bounds = regionBounds(region);
  const first = cloneRegion(region);
  const second = cloneRegion(region);
  const flags = uniqueFlags([...region.flags, 'manual_split']);
  if (direction === 'horizontal') {
    const midpoint = (bounds.minY + bounds.maxY) / 2;
    return [
      adjusted(first, rectanglePolygon({ ...bounds, maxY: midpoint }), flags),
      {
        ...adjusted(second, rectanglePolygon({ ...bounds, minY: midpoint }), flags),
        id: createRegionId(),
      },
    ];
  }
  const midpoint = (bounds.minX + bounds.maxX) / 2;
  return [
    adjusted(first, rectanglePolygon({ ...bounds, maxX: midpoint }), flags),
    {
      ...adjusted(second, rectanglePolygon({ ...bounds, minX: midpoint }), flags),
      id: createRegionId(),
    },
  ];
}

export function mergeRegions(regions: readonly Region[], id = createRegionId()): Region | null {
  if (regions.length < 2) return null;
  const bounds = regions.map(regionBounds).reduce<RegionBounds>(
    (combined, current) => ({
      minX: Math.min(combined.minX, current.minX),
      minY: Math.min(combined.minY, current.minY),
      maxX: Math.max(combined.maxX, current.maxX),
      maxY: Math.max(combined.maxY, current.maxY),
    }),
    { minX: 1, minY: 1, maxX: 0, maxY: 0 },
  );
  return {
    id,
    polygon: rectanglePolygon(bounds),
    readingOrder: 0,
    revision: 0,
    source: 'adjusted',
    flags: uniqueFlags([...regions.flatMap((region) => region.flags), 'manual_merge']),
    detectorVersion: null,
    detectorScore: null,
  };
}

export function replaceOne(regions: readonly Region[], replacement: Region): Region[] {
  return withContiguousOrder(
    regions.map((region) =>
      region.id === replacement.id ? cloneRegion(replacement) : cloneRegion(region),
    ),
  );
}

export function moveReadingOrder(
  regions: readonly Region[],
  id: string,
  direction: -1 | 1,
): Region[] {
  const currentIndex = regions.findIndex((region) => region.id === id);
  const nextIndex = currentIndex + direction;
  if (currentIndex < 0 || nextIndex < 0 || nextIndex >= regions.length)
    return cloneRegions(regions);
  const next = cloneRegions(regions);
  const [item] = next.splice(currentIndex, 1);
  if (!item) return next;
  next.splice(nextIndex, 0, item);
  return withContiguousOrder(next);
}

export function sameRegions(left: readonly Region[], right: readonly Region[]): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function polygonPath(region: Region): string {
  return region.polygon.map((point) => `${point.x},${point.y}`).join(' ');
}
