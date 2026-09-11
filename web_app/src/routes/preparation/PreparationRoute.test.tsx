import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { getPreparation } from '@features/preparation/api';
import { loadPreparationDraft, savePreparationDraft } from '@features/preparation/persistence';

import PreparationRoute from './PreparationRoute';

vi.mock('@shared/access/AccessProvider', () => ({
  useAccess: () => ({ csrfToken: 'csrf-token', reconnect: vi.fn() }),
}));
vi.mock('@features/preparation/api', async () => {
  const actual = await vi.importActual<typeof import('@features/preparation/api')>(
    '@features/preparation/api',
  );
  return { ...actual, getPreparation: vi.fn() };
});
vi.mock('@features/preparation/persistence', () => ({
  loadPreparationDraft: vi.fn(),
  removePreparationDraft: vi.fn(),
  savePreparationDraft: vi.fn(),
}));

const pageId = '11111111-1111-4111-8111-111111111111';

describe('PreparationRoute', () => {
  afterEach(cleanup);

  beforeEach(() => {
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
        preparedAsset: null,
        recipe: null,
        recipeHash: null,
        qualityThresholdVersion: null,
        qualityMetrics: null,
        qualityWarnings: [],
        confirmed: false,
      },
    });
    vi.mocked(loadPreparationDraft).mockResolvedValue(null);
    vi.mocked(savePreparationDraft).mockResolvedValue();
    vi.stubGlobal(
      'ResizeObserver',
      class ResizeObserver {
        observe() {}
        disconnect() {}
      },
    );
  });

  it('keeps wheel zoom inside the canvas instead of scrolling the page', async () => {
    render(
      <MemoryRouter initialEntries={[`/preparation?pageId=${pageId}`]}>
        <PreparationRoute />
      </MemoryRouter>,
    );

    const workspace = await screen.findByRole('region', { name: 'Подготовка изображения' });
    const canvas = workspace.querySelector('.preparation-canvas');
    expect(canvas).toBeInstanceOf(HTMLElement);

    const wheel = new WheelEvent('wheel', {
      bubbles: true,
      cancelable: true,
      clientX: 120,
      clientY: 80,
      deltaY: 100,
    });
    expect(canvas?.dispatchEvent(wheel)).toBe(false);
    expect(wheel.defaultPrevented).toBe(true);
  });

  it('keeps the real editing tools in one tabbed panel with undo and redo', async () => {
    render(
      <MemoryRouter initialEntries={[`/preparation?pageId=${pageId}`]}>
        <PreparationRoute />
      </MemoryRouter>,
    );

    await screen.findByRole('region', { name: 'Подготовка изображения' });
    expect(screen.getAllByRole('tab')).toHaveLength(4);

    fireEvent.click(screen.getByRole('button', { name: 'Влево' }));
    fireEvent.click(screen.getByRole('tab', { name: 'История' }));

    const undo = screen.getByRole('button', { name: 'Отменить' });
    const redo = screen.getByRole('button', { name: 'Вернуть' });
    expect(undo).toBeEnabled();
    expect(redo).toBeDisabled();

    fireEvent.click(undo);
    expect(redo).toBeEnabled();

    fireEvent.click(screen.getByRole('tab', { name: 'Вид' }));
    expect(screen.getByRole('slider', { name: 'Масштаб изображения' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Вписать изображение' })).toHaveLength(2);
  });
});
