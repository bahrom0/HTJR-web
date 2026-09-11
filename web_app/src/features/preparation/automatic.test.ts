import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createRecognitionJob } from '@entities/job';

import { confirmPreparation, getPreparation, previewPreparation } from './api';
import { startAutomaticRecognition } from './automatic';
import { defaultPreparationRecipe, type PreparationState } from './model';

vi.mock('@entities/job', () => ({ createRecognitionJob: vi.fn() }));
vi.mock('./api', () => ({
  getPreparation: vi.fn(),
  previewPreparation: vi.fn(),
  confirmPreparation: vi.fn(),
}));

const asset = {
  id: 'asset',
  mediaType: 'image/png',
  width: 1000,
  height: 1400,
  previewUrl: '/api/v1/assets/asset/preview',
};

function preparation(overrides: Partial<PreparationState> = {}): PreparationState {
  return {
    documentId: 'document',
    pageId: 'page',
    revision: 1,
    sourceAsset: asset,
    preparedAsset: null,
    recipe: null,
    recipeHash: null,
    qualityThresholdVersion: null,
    qualityMetrics: null,
    qualityWarnings: [],
    confirmed: false,
    ...overrides,
  };
}

describe('startAutomaticRecognition', () => {
  beforeEach(() => vi.clearAllMocks());

  it('evaluates quality, confirms preparation and starts Kraken with one stable key', async () => {
    const prepared = preparation({
      revision: 2,
      preparedAsset: asset,
      recipe: defaultPreparationRecipe,
      recipeHash: 'hash',
      qualityThresholdVersion: 'quality-v1',
      qualityMetrics: { contrast: 0.8 },
    });
    const confirmed = preparation({ ...prepared, revision: 3, confirmed: true });
    vi.mocked(getPreparation).mockResolvedValue({
      ok: true,
      value: preparation(),
      requestId: 'get',
    });
    vi.mocked(previewPreparation).mockResolvedValue({
      ok: true,
      value: prepared,
      requestId: 'preview',
    });
    vi.mocked(confirmPreparation).mockResolvedValue({
      ok: true,
      value: confirmed,
      requestId: 'confirm',
    });
    vi.mocked(createRecognitionJob).mockResolvedValue({
      ok: true,
      value: { id: 'job' } as never,
      requestId: 'job',
    });
    const phases: string[] = [];

    await startAutomaticRecognition('page', 'csrf', { onPhase: (phase) => phases.push(phase) });

    expect(previewPreparation).toHaveBeenCalledWith('page', defaultPreparationRecipe, 'csrf');
    expect(confirmPreparation).toHaveBeenCalledWith('page', 2, 'csrf');
    expect(createRecognitionJob).toHaveBeenCalledWith(
      'page',
      'recognition:page:3',
      'csrf',
      undefined,
    );
    expect(phases).toEqual(['quality', 'confirming', 'detecting']);
  });

  it('reuses an already confirmed preparation after refresh', async () => {
    const ready = preparation({
      revision: 7,
      preparedAsset: asset,
      recipe: defaultPreparationRecipe,
      recipeHash: 'hash',
      qualityThresholdVersion: 'quality-v1',
      qualityMetrics: { contrast: 0.8 },
      qualityWarnings: [],
      confirmed: true,
    });
    vi.mocked(getPreparation).mockResolvedValue({ ok: true, value: ready, requestId: 'get' });
    vi.mocked(createRecognitionJob).mockResolvedValue({
      ok: true,
      value: { id: 'job' } as never,
      requestId: 'job',
    });

    await startAutomaticRecognition('page', 'csrf');

    expect(previewPreparation).not.toHaveBeenCalled();
    expect(confirmPreparation).not.toHaveBeenCalled();
    expect(createRecognitionJob).toHaveBeenCalledWith(
      'page',
      'recognition:page:7',
      'csrf',
      undefined,
    );
  });
});
