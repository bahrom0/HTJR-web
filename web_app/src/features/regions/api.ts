import { isUuid, request, type ApiResult } from '@shared/api/client';

import {
  clampUnit,
  withContiguousOrder,
  type NormalizedPoint,
  type Region,
  type RegionSnapshot,
  type RegionSource,
} from './model';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isSource(value: unknown): value is RegionSource {
  return value === 'craft' || value === 'kraken' || value === 'manual' || value === 'adjusted';
}

function hasOnlyKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function parsePoint(value: unknown): NormalizedPoint | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['x', 'y'])) return null;
  if (!isFiniteNumber(value.x) || !isFiniteNumber(value.y)) return null;
  if (value.x < 0 || value.x > 1 || value.y < 0 || value.y > 1) return null;
  return { x: value.x, y: value.y };
}

function parseRegion(value: unknown): Region | null {
  if (!isRecord(value)) return null;
  const keys = [
    'id',
    'polygon',
    'reading_order',
    'revision',
    'source',
    'flags',
    'detector_version',
    'detector_score',
  ] as const;
  const id = value.id;
  const polygonValue = value.polygon;
  const readingOrder = value.reading_order;
  const revision = value.revision;
  const source = value.source;
  const flags = value.flags;
  const detectorVersion = value.detector_version;
  const detectorScore = value.detector_score;
  if (!hasOnlyKeys(value, keys) || !isUuid(id) || !Array.isArray(polygonValue)) return null;
  if (polygonValue.length !== 4 || !isInteger(readingOrder) || readingOrder < 0) return null;
  if (!isInteger(revision) || revision < 1 || !isSource(source)) return null;
  if (!Array.isArray(flags) || !flags.every((flag) => typeof flag === 'string')) return null;
  const polygon = polygonValue.map(parsePoint);
  if (polygon.some((point) => point === null)) return null;
  const [first, second, third, fourth] = polygon;
  if (!first || !second || !third || !fourth) return null;
  if (
    (detectorVersion !== null && typeof detectorVersion !== 'string') ||
    (detectorScore !== null &&
      (!isFiniteNumber(detectorScore) || detectorScore < 0 || detectorScore > 1))
  ) {
    return null;
  }
  if (source === 'craft' && (detectorVersion === null || detectorScore === null)) {
    return null;
  }
  if (source === 'kraken' && detectorVersion === null) {
    return null;
  }
  return {
    id,
    polygon: [first, second, third, fourth],
    readingOrder,
    revision,
    source,
    flags,
    detectorVersion,
    detectorScore,
  };
}

export function parseRegionSnapshot(value: unknown): RegionSnapshot | null {
  if (!isRecord(value)) return null;
  const keys = ['page_id', 'revision', 'confirmed', 'regions', 'resumed_job_id'] as const;
  const pageId = value.page_id;
  const revision = value.revision;
  const confirmed = value.confirmed;
  const regionsValue = value.regions;
  const resumedJobId = value.resumed_job_id;
  if (!hasOnlyKeys(value, keys) || !isUuid(pageId) || !isInteger(revision)) return null;
  if (revision < 1 || typeof confirmed !== 'boolean' || !Array.isArray(regionsValue)) return null;
  if (resumedJobId !== undefined && resumedJobId !== null && !isUuid(resumedJobId)) {
    return null;
  }
  const regions = regionsValue.map(parseRegion);
  if (regions.some((region) => region === null)) return null;
  const parsed = regions.filter((region): region is Region => region !== null);
  const ordered = [...parsed].sort((left, right) => left.readingOrder - right.readingOrder);
  if (
    new Set(ordered.map((region) => region.id)).size !== ordered.length ||
    ordered.some((region, index) => region.readingOrder !== index)
  ) {
    return null;
  }
  return {
    pageId,
    revision,
    confirmed,
    regions: withContiguousOrder(ordered),
    resumedJobId: typeof resumedJobId === 'string' ? resumedJobId : null,
  };
}

function toWireRegion(region: Region) {
  return {
    id: region.id,
    polygon: region.polygon.map((point) => ({ x: clampUnit(point.x), y: clampUnit(point.y) })),
    reading_order: region.readingOrder,
    source: region.source,
    flags: [...region.flags],
    detector_version: region.detectorVersion,
    detector_score: region.detectorScore,
  };
}

export function getRegions(
  pageId: string,
  signal?: AbortSignal,
): Promise<ApiResult<RegionSnapshot>> {
  return request(`/pages/${encodeURIComponent(pageId)}/regions`, parseRegionSnapshot, { signal });
}

export function replaceRegions(
  pageId: string,
  revision: number,
  regions: readonly Region[],
  csrfToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<RegionSnapshot>> {
  return request(`/pages/${encodeURIComponent(pageId)}/regions`, parseRegionSnapshot, {
    method: 'PUT',
    json: { revision, regions: withContiguousOrder(regions).map(toWireRegion) },
    csrfToken,
    signal,
  });
}

export function confirmRegions(
  pageId: string,
  revision: number,
  csrfToken: string,
  job?: Readonly<{ id: string; revision: number }>,
  signal?: AbortSignal,
): Promise<ApiResult<RegionSnapshot>> {
  return request(`/pages/${encodeURIComponent(pageId)}/regions/confirm`, parseRegionSnapshot, {
    method: 'POST',
    json: {
      revision,
      ...(job ? { job_id: job.id, job_revision: job.revision } : {}),
    },
    csrfToken,
    signal,
  });
}
