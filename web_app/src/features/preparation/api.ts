import { isUuid, request, type ApiResult } from '@shared/api/client';

import {
  normalizeCrop,
  normalizePoint,
  type PreparationAsset,
  type PreparationRecipe,
  type PreparationState,
} from './model';

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value);
}

function parseAsset(value: unknown): PreparationAsset | null {
  if (!record(value) || !isUuid(value.id) || typeof value.media_type !== 'string') return null;
  if (!integer(value.width) || !integer(value.height) || value.width < 1 || value.height < 1)
    return null;
  if (typeof value.preview_url !== 'string' || !value.preview_url.startsWith('/api/v1/assets/'))
    return null;
  return {
    id: value.id,
    mediaType: value.media_type,
    width: value.width,
    height: value.height,
    previewUrl: value.preview_url,
  };
}

function parseRecipe(value: unknown): PreparationRecipe | null {
  if (!record(value) || ![0, 90, 180, 270].includes(value.rotation_degrees as number)) return null;
  if (!integer(value.max_edge) || value.max_edge < 512 || value.max_edge > 4096) return null;
  let crop = null;
  if (value.crop !== null && value.crop !== undefined) {
    if (
      !record(value.crop) ||
      !finite(value.crop.x) ||
      !finite(value.crop.y) ||
      !finite(value.crop.width) ||
      !finite(value.crop.height)
    )
      return null;
    crop = normalizeCrop({
      x: value.crop.x,
      y: value.crop.y,
      width: value.crop.width,
      height: value.crop.height,
    });
  }
  let perspective: PreparationRecipe['perspective'] = null;
  if (value.perspective !== null && value.perspective !== undefined) {
    if (!Array.isArray(value.perspective) || value.perspective.length !== 4) return null;
    const points = value.perspective.map((point) => {
      if (!record(point) || !finite(point.x) || !finite(point.y)) return null;
      return normalizePoint({ x: point.x, y: point.y });
    });
    if (points.some((point) => point === null)) return null;
    const [first, second, third, fourth] = points;
    if (!first || !second || !third || !fourth) return null;
    perspective = [first, second, third, fourth];
  }
  return {
    rotationDegrees: value.rotation_degrees as PreparationRecipe['rotationDegrees'],
    crop,
    perspective,
    maxEdge: value.max_edge,
  };
}

function parseMetrics(value: unknown): Readonly<Record<string, number>> | null {
  if (!record(value) || !Object.values(value).every(finite)) return null;
  return value as Record<string, number>;
}

export function parsePreparationState(value: unknown): PreparationState | null {
  if (!record(value) || !isUuid(value.document_id) || !isUuid(value.page_id)) return null;
  if (!integer(value.revision) || value.revision < 1 || !Array.isArray(value.quality_warnings))
    return null;
  if (!value.quality_warnings.every((warning) => typeof warning === 'string')) return null;
  const sourceAsset = parseAsset(value.source_asset);
  if (!sourceAsset || typeof value.confirmed !== 'boolean') return null;
  const preparedAsset = value.prepared_asset === null ? null : parseAsset(value.prepared_asset);
  const recipe = value.recipe === null ? null : parseRecipe(value.recipe);
  if ((preparedAsset === null) !== (recipe === null)) return null;
  if (
    preparedAsset &&
    (typeof value.recipe_hash !== 'string' || typeof value.quality_threshold_version !== 'string')
  )
    return null;
  const metrics = value.quality_metrics === null ? null : parseMetrics(value.quality_metrics);
  if (preparedAsset && metrics === null) return null;
  return {
    documentId: value.document_id,
    pageId: value.page_id,
    revision: value.revision,
    sourceAsset,
    preparedAsset,
    recipe,
    recipeHash: typeof value.recipe_hash === 'string' ? value.recipe_hash : null,
    qualityThresholdVersion:
      typeof value.quality_threshold_version === 'string' ? value.quality_threshold_version : null,
    qualityMetrics: metrics,
    qualityWarnings: value.quality_warnings,
    confirmed: value.confirmed,
  };
}

function toWire(recipe: PreparationRecipe) {
  return {
    rotation_degrees: recipe.rotationDegrees,
    crop: recipe.crop,
    perspective: recipe.perspective,
    max_edge: recipe.maxEdge,
  };
}

export function getPreparation(
  pageId: string,
  signal?: AbortSignal,
): Promise<ApiResult<PreparationState>> {
  return request(`/pages/${pageId}/preparation`, parsePreparationState, { signal });
}

export async function previewPreparation(
  pageId: string,
  recipe: PreparationRecipe,
  csrfToken: string,
): Promise<ApiResult<PreparationState>> {
  const result = await request(`/pages/${pageId}/prepare`, () => true, {
    method: 'POST',
    json: toWire(recipe),
    csrfToken,
    timeoutMs: 30_000,
  });
  if (!result.ok) return result;
  return getPreparation(pageId);
}

export function confirmPreparation(
  pageId: string,
  revision: number,
  csrfToken: string,
): Promise<ApiResult<PreparationState>> {
  return request(`/pages/${pageId}/preparation/confirm`, () => true, {
    method: 'POST',
    json: { revision },
    csrfToken,
  }).then(async (result) => (result.ok ? getPreparation(pageId) : result));
}
