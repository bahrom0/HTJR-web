export type NormalizedPoint = Readonly<{ x: number; y: number }>;
export type Crop = Readonly<{ x: number; y: number; width: number; height: number }>;
export type PreparationRecipe = Readonly<{
  rotationDegrees: 0 | 90 | 180 | 270;
  crop: Crop | null;
  perspective: readonly [NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint] | null;
  maxEdge: number;
}>;

export const defaultPreparationRecipe: PreparationRecipe = {
  rotationDegrees: 0,
  crop: null,
  perspective: null,
  maxEdge: 3000,
};

export type PreparationAsset = Readonly<{
  id: string;
  mediaType: string;
  width: number;
  height: number;
  previewUrl: string;
}>;

export type PreparationState = Readonly<{
  documentId: string;
  pageId: string;
  revision: number;
  sourceAsset: PreparationAsset;
  preparedAsset: PreparationAsset | null;
  recipe: PreparationRecipe | null;
  recipeHash: string | null;
  qualityThresholdVersion: string | null;
  qualityMetrics: Readonly<Record<string, number>> | null;
  qualityWarnings: readonly string[];
  confirmed: boolean;
}>;

export type PreparationDraft = Readonly<{
  pageId: string;
  sourceAssetId: string;
  recipe: PreparationRecipe;
  history: readonly PreparationRecipe[];
  updatedAt: string;
}>;

export function cloneRecipe(recipe: PreparationRecipe): PreparationRecipe {
  return {
    rotationDegrees: recipe.rotationDegrees,
    crop: recipe.crop ? { ...recipe.crop } : null,
    perspective: recipe.perspective
      ? [
          { ...recipe.perspective[0] },
          { ...recipe.perspective[1] },
          { ...recipe.perspective[2] },
          { ...recipe.perspective[3] },
        ]
      : null,
    maxEdge: recipe.maxEdge,
  };
}

export function recipeEquals(left: PreparationRecipe, right: PreparationRecipe): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function normalizePoint(point: NormalizedPoint): NormalizedPoint {
  return {
    x: Math.min(1, Math.max(0, point.x)),
    y: Math.min(1, Math.max(0, point.y)),
  };
}

export function normalizeCrop(crop: Crop): Crop {
  const x = Math.min(0.98, Math.max(0, crop.x));
  const y = Math.min(0.98, Math.max(0, crop.y));
  return {
    x,
    y,
    width: Math.min(1 - x, Math.max(0.02, crop.width)),
    height: Math.min(1 - y, Math.max(0.02, crop.height)),
  };
}

export function rotateRecipe(recipe: PreparationRecipe, amount: 90 | -90): PreparationRecipe {
  const rotation = ((recipe.rotationDegrees + amount + 360) %
    360) as PreparationRecipe['rotationDegrees'];
  return { ...cloneRecipe(recipe), rotationDegrees: rotation };
}
