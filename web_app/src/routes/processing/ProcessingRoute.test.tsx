import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { JobSnapshot } from '@entities/job';
import { createJobSubscription, projectJobProgress } from '@features/job-progress';
import { startAutomaticRecognition } from '@features/preparation/automatic';
import { getPreparation } from '@features/preparation/api';
import { getRegions } from '@features/regions/api';

import ProcessingRoute from './ProcessingRoute';

vi.mock('@shared/access/AccessProvider', () => ({
  useAccess: () => ({ csrfToken: 'csrf-token', reconnect: vi.fn() }),
}));
vi.mock('@features/preparation/automatic', () => ({ startAutomaticRecognition: vi.fn() }));
vi.mock('@features/preparation/api', () => ({ getPreparation: vi.fn() }));
vi.mock('@features/regions/api', () => ({ getRegions: vi.fn() }));
vi.mock('@features/job-progress', () => ({
  createJobSubscription: vi.fn(),
  projectJobProgress: vi.fn(),
}));

const pageId = '11111111-1111-4111-8111-111111111111';
const jobId = '22222222-2222-4222-8222-222222222222';

function snapshot(overrides: Partial<JobSnapshot> = {}): JobSnapshot {
  return {
    id: jobId,
    documentId: '33333333-3333-4333-8333-333333333333',
    pageId,
    state: 'running',
    stage: 'detecting_regions',
    priority: 0,
    processedCount: 0,
    totalCount: 0,
    attempt: 1,
    maxAttempts: 3,
    cancellationRequested: false,
    errorCode: null,
    errorRetryable: false,
    canCancel: true,
    canRetry: false,
    revision: 4,
    createdAt: '2026-08-04T10:00:00Z',
    updatedAt: '2026-08-04T10:00:00Z',
    duplicate: false,
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderRoute(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <ProcessingRoute />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProcessingRoute automatic flow', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createJobSubscription).mockReturnValue({
      start: vi.fn().mockResolvedValue(undefined),
      dispose: vi.fn(),
    } as never);
    vi.mocked(projectJobProgress).mockReturnValue({
      stage: 'detecting_regions',
      stageLabel: 'Поиск строк',
      progressPercent: 45,
      counterLabel: 'Ищем строки',
      error: null,
      isPartial: false,
      canCancel: true,
      canRetry: false,
    } as never);
    vi.mocked(getPreparation).mockResolvedValue({
      ok: true,
      requestId: 'preparation',
      value: {
        documentId: '33333333-3333-4333-8333-333333333333',
        pageId,
        revision: 3,
        sourceAsset: {
          id: '44444444-4444-4444-8444-444444444444',
          mediaType: 'image/png',
          width: 1200,
          height: 800,
          previewUrl: '/api/v1/assets/44444444-4444-4444-8444-444444444444/preview',
        },
        preparedAsset: null,
        recipe: null,
        recipeHash: null,
        qualityThresholdVersion: null,
        qualityMetrics: null,
        qualityWarnings: [],
        confirmed: false,
      },
    });
    vi.mocked(getRegions).mockResolvedValue({
      ok: false,
      error: { code: 'not_ready', message: 'not ready', retryable: true, requestId: 'regions' },
    });
  });

  it('starts quality and Kraken automatically from the uploaded page', async () => {
    vi.mocked(startAutomaticRecognition).mockImplementation(async (_page, _csrf, options) => {
      options?.onPhase?.('quality');
      options?.onPhase?.('detecting');
      return { ok: true, requestId: 'job', value: snapshot() };
    });

    renderRoute(`/processing?pageId=${pageId}&auto=1`);

    expect(await screen.findByText('Запускаем поиск строк Kraken')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent(
        `/processing?pageId=${pageId}&jobId=${jobId}`,
      ),
    );
    expect(screen.getByRole('main')).toHaveClass('processing-page--bootstrap');
    expect(screen.queryByText('Проверка файла')).not.toBeInTheDocument();
  });

  it('opens the real region editor when Kraken reaches review', async () => {
    vi.mocked(createJobSubscription).mockImplementation(
      ({ onState }) =>
        ({
          start: vi.fn(async () => {
            onState({
              jobId,
              lastSequence: 0,
              connection: 'live',
              snapshot: snapshot({
                state: 'awaiting_region_review',
                stage: 'awaiting_region_review',
                totalCount: 2,
              }),
              transportError: null,
            });
          }),
          dispose: vi.fn(),
        }) as never,
    );

    renderRoute(`/processing?pageId=${pageId}&jobId=${jobId}`);

    expect(screen.getByRole('main')).toHaveClass('processing-page--bootstrap');
    expect(screen.queryByText('Проверка файла')).not.toBeInTheDocument();

    await waitFor(
      () =>
        expect(screen.getByTestId('location')).toHaveTextContent(
          `/regions?pageId=${pageId}&jobId=${jobId}`,
        ),
      { timeout: 2_000 },
    );
  });
});
