import { request, type ApiResult } from '@shared/api/client';
import type { NormalizedPoint } from '@features/regions/model';

export type DemoRegion = Readonly<{
  id: string;
  polygon: readonly NormalizedPoint[];
  reading_order: number;
  text: string;
}>;

export type DemoPreset = Readonly<{
  image_sha256: string;
  text: string;
  original_filename: string | null;
  regions: readonly DemoRegion[];
}>;

function point(value: unknown): value is NormalizedPoint {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.x === 'number' && typeof item.y === 'number';
}

function region(value: unknown): value is DemoRegion {
  if (typeof value !== 'object' || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === 'string' && Array.isArray(item.polygon) && item.polygon.length === 4 &&
    item.polygon.every(point) && typeof item.reading_order === 'number' && typeof item.text === 'string';
}

function parsePreset(value: unknown): DemoPreset | null {
  if (typeof value !== 'object' || value === null) return null;
  const data = value as Record<string, unknown>;
  if (typeof data.image_sha256 !== 'string' || typeof data.text !== 'string' || !Array.isArray(data.regions) || !data.regions.every(region)) return null;
  if (data.original_filename !== null && typeof data.original_filename !== 'string') return null;
  return data as unknown as DemoPreset;
}

function parseDetection(value: unknown): { detector_version: string; regions: readonly DemoRegion[] } | null {
  if (typeof value !== 'object' || value === null) return null;
  const data = value as Record<string, unknown>;
  if (typeof data.detector_version !== 'string' || !Array.isArray(data.regions) || !data.regions.every(region)) return null;
  return data as { detector_version: string; regions: readonly DemoRegion[] };
}

export async function imageSha256(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function getDemoPreset(sha256: string): Promise<ApiResult<DemoPreset>> {
  return request(`/demo/presets/${sha256}`, parsePreset);
}

export function detectDemoRegions(file: File): Promise<ApiResult<{ detector_version: string; regions: readonly DemoRegion[] }>> {
  return request('/demo/detect-regions', parseDetection, {
    method: 'POST', body: file, timeoutMs: 240_000, headers: { 'Content-Type': file.type },
  });
}

export function saveDemoPreset(sha256: string, regions: readonly DemoRegion[], filename: string): Promise<ApiResult<DemoPreset>> {
  return request(`/demo/presets/${sha256}`, parsePreset, {
    method: 'PUT', json: { original_filename: filename, regions },
  });
}
