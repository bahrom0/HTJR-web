import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import RegionReviewRoute from './RegionReviewRoute';
import { confirmRegions, getRegions, replaceRegions } from '@features/regions';
import { getPreparation } from '@features/preparation/api';
import { getJobSnapshot } from '@entities/job';
import { loadRegionDraft, removeRegionDraft, saveRegionDraft } from '@features/regions/persistence';

vi.mock('@shared/access/AccessProvider', () => ({
  useAccess: () => ({ csrfToken: 'csrf-token', reconnect: vi.fn() }),
}));
vi.mock('@features/regions', async () => {
  const actual = await vi.importActual<typeof import('@features/regions')>('@features/regions');
  return { ...actual, getRegions: vi.fn(), replaceRegions: vi.fn(), confirmRegions: vi.fn() };
});
vi.mock('@features/preparation/api', () => ({ getPreparation: vi.fn() }));
vi.mock('@entities/job', () => ({ getJobSnapshot: vi.fn() }));
vi.mock('@features/regions/persistence', () => ({
  loadRegionDraft: vi.fn(),
  removeRegionDraft: vi.fn(),
  saveRegionDraft: vi.fn(),
}));

const pageId = '11111111-1111-4111-8111-111111111111';
const jobId = '33333333-3333-4333-8333-333333333333';
const regionId = '22222222-2222-4222-8222-222222222222';

const regionSnapshot = {
  pageId,
  revision: 7,
  confirmed: false,
  resumedJobId: null,
  regions: [
    {
      id: regionId,
      polygon: [
        { x: 0.1, y: 0.2 },
        { x: 0.9, y: 0.2 },
        { x: 0.9, y: 0.3 },
        { x: 0.1, y: 0.3 },
      ],
      readingOrder: 0,
      revision: 1,
      source: 'craft' as const,
      flags: ['baseline_skew'],
      detectorVersion: 'craft_mlt_25k',
      detectorScore: 0.91,
    },
  ],
};

function renderRoute() {
  function LocationProbe() {
    return (
      <output data-testid="location">
        {useLocation().pathname}
        {useLocation().search}
      </output>
    );
  }
  return render(
    <MemoryRouter initialEntries={[`/regions?pageId=${pageId}&jobId=${jobId}`]}>
      <RegionReviewRoute />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe('RegionReviewRoute', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.mocked(getRegions).mockResolvedValue({
      ok: true,
      requestId: 'request',
      value: regionSnapshot,
    });
    vi.mocked(getPreparation).mockResolvedValue({
      ok: true,
      requestId: 'request',
      value: {
        documentId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        pageId,
        revision: 2,
        sourceAsset: {
          id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          mediaType: 'image/png',
          width: 1200,
          height: 800,
          previewUrl: '/api/v1/assets/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb/preview',
        },
        preparedAsset: {
          id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          mediaType: 'image/png',
          width: 1200,
          height: 800,
          previewUrl: '/api/v1/assets/cccccccc-cccc-4ccc-8ccc-cccccccccccc/preview',
        },
        recipe: null,
        recipeHash: null,
        qualityThresholdVersion: null,
        qualityMetrics: null,
        qualityWarnings: [],
        confirmed: true,
      },
    });
    vi.mocked(getJobSnapshot).mockResolvedValue({
      ok: true,
      requestId: 'request',
      value: {
        id: jobId,
        documentId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        pageId,
        state: 'awaiting_region_review',
        stage: 'awaiting_region_review',
        priority: 0,
        processedCount: 0,
        totalCount: 1,
        attempt: 1,
        maxAttempts: 3,
        cancellationRequested: false,
        errorCode: null,
        errorRetryable: false,
        canCancel: true,
        canRetry: false,
        revision: 4,
        createdAt: '2026-07-20T10:00:00Z',
        updatedAt: '2026-07-20T10:00:00Z',
        duplicate: false,
      },
    });
    vi.mocked(loadRegionDraft).mockResolvedValue(null);
    vi.mocked(saveRegionDraft).mockResolvedValue();
    vi.mocked(removeRegionDraft).mockResolvedValue();
    vi.mocked(replaceRegions).mockResolvedValue({
      ok: true,
      requestId: 'request',
      value: regionSnapshot,
    });
    vi.mocked(confirmRegions).mockResolvedValue({
      ok: true,
      requestId: 'request',
      value: { ...regionSnapshot, revision: 8, confirmed: true, resumedJobId: jobId },
    });
    vi.stubGlobal(
      'ResizeObserver',
      class ResizeObserver {
        observe() {}
        disconnect() {}
      },
    );
  });

  it('offers an accessible list and keyboard-safe manual add/undo controls', async () => {
    renderRoute();

    await screen.findByRole('button', { name: /Регион 1: CRAFT/ });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить область' }));

    expect(
      await screen.findByRole('button', { name: /Регион 2: ручная область/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отменить' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Отменить' }));
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Регион 2: ручная область/ })).toBeNull(),
    );
  });

  it('keeps mobile-size resize handles while offering keyboard movement outside the canvas', async () => {
    renderRoute();

    const region = await screen.findByRole('button', { name: /Регион 1: CRAFT/ });
    expect(
      screen.getAllByRole('button', { name: /Изменить размер выбранной области/ }),
    ).toHaveLength(4);
    fireEvent.keyDown(region, { key: 'ArrowRight' });

    expect(screen.getByRole('button', { name: 'Отменить' })).toBeEnabled();
    await waitFor(() => expect(saveRegionDraft).toHaveBeenCalled());
  });

  it('restores a same-revision region draft after a refresh instead of silently discarding it', async () => {
    const manualId = '77777777-7777-4777-8777-777777777777';
    vi.mocked(loadRegionDraft).mockResolvedValue({
      pageId,
      preparedAssetId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      baseRevision: 7,
      regions: [
        ...regionSnapshot.regions,
        {
          id: manualId,
          polygon: [
            { x: 0.1, y: 0.5 },
            { x: 0.9, y: 0.5 },
            { x: 0.9, y: 0.58 },
            { x: 0.1, y: 0.58 },
          ],
          readingOrder: 1,
          revision: 0,
          source: 'manual',
          flags: [],
          detectorVersion: null,
          detectorScore: null,
        },
      ],
      history: [],
      redo: [],
      selectedIds: [manualId],
      updatedAt: '2026-07-20T10:01:00Z',
    });
    renderRoute();

    expect(
      await screen.findByText(/Восстановлены несохранённые правки областей/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Регион 2: ручная область/ })).toBeInTheDocument();
  });

  it('saves the current revision before atomically confirming the durable job', async () => {
    renderRoute();

    await screen.findByRole('button', { name: /Регион 1: CRAFT/ });
    fireEvent.click(screen.getByRole('button', { name: 'Распознать текст' }));

    await waitFor(() =>
      expect(confirmRegions).toHaveBeenCalledWith(pageId, 7, 'csrf-token', {
        id: jobId,
        revision: 4,
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(`/processing?jobId=${jobId}`),
    );
  });

  it('keeps a local draft when the server rejects a stale revision', async () => {
    vi.mocked(replaceRegions).mockResolvedValue({
      ok: false,
      error: { code: 'revision_conflict', message: 'stale', retryable: true, requestId: 'request' },
    });
    renderRoute();

    await screen.findByRole('button', { name: /Регион 1: CRAFT/ });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить область' }));
    fireEvent.click(screen.getByRole('button', { name: 'Распознать текст' }));

    expect(await screen.findByText(/Версия страницы изменилась на сервере/)).toBeInTheDocument();
    await waitFor(() => expect(saveRegionDraft).toHaveBeenCalled());
  });
});
