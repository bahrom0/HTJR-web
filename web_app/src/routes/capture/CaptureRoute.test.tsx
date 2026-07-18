import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import CaptureRoute from './CaptureRoute';
import { uploadDocument } from '@features/capture/api';
import { listPendingUploads, removePendingUpload, savePendingUpload } from '@shared/upload/outbox';

vi.mock('@shared/access/AccessProvider', () => ({
  useAccess: () => ({ csrfToken: 'csrf-token', reconnect: vi.fn() }),
}));
vi.mock('@features/capture/api', () => ({ uploadDocument: vi.fn() }));
vi.mock('@shared/upload/outbox', () => ({
  listPendingUploads: vi.fn(),
  removePendingUpload: vi.fn(),
  savePendingUpload: vi.fn(),
}));

describe('CaptureRoute', () => {
  afterEach(() => cleanup());
  beforeEach(() => {
    vi.mocked(listPendingUploads).mockResolvedValue([]);
    vi.mocked(savePendingUpload).mockResolvedValue();
    vi.mocked(removePendingUpload).mockResolvedValue();
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn().mockResolvedValue({ width: 1000, height: 1400, close: vi.fn() }),
    );
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:preview'),
      revokeObjectURL: vi.fn(),
    });
  });

  it('exposes a mobile rear-camera hint and a separate file picker', async () => {
    render(
      <MemoryRouter>
        <CaptureRoute />
      </MemoryRouter>,
    );
    const camera = screen.getByLabelText('Снять страницу камерой');
    expect(camera).toHaveAttribute('capture', 'environment');
    expect(camera).toHaveAttribute('accept', 'image/jpeg,image/png,image/webp');
    expect(screen.getByLabelText('Выбрать изображение')).not.toHaveAttribute('capture');
  });

  it('stores the upload before sending and removes it only after success', async () => {
    vi.mocked(uploadDocument).mockResolvedValue({
      ok: true,
      requestId: 'request',
      value: {
        documentId: 'doc',
        pageId: 'page',
        duplicate: false,
        asset: {
          id: 'asset',
          mediaType: 'image/png',
          width: 1000,
          height: 1400,
          previewUrl: '/api/v1/assets/asset/preview',
        },
      },
    });
    render(
      <MemoryRouter>
        <CaptureRoute />
      </MemoryRouter>,
    );
    const file = new File(['image'], 'tajik.png', { type: 'image/png' });
    fireEvent.change(screen.getByLabelText('Выбрать изображение'), { target: { files: [file] } });
    await screen.findByAltText('Предпросмотр выбранной страницы');
    fireEvent.click(screen.getByRole('button', { name: /Создать документ/ }));
    await waitFor(() => expect(savePendingUpload).toHaveBeenCalledOnce());
    await waitFor(() => expect(uploadDocument).toHaveBeenCalledOnce());
    await waitFor(() => expect(removePendingUpload).toHaveBeenCalledOnce());
    expect(await screen.findByText('Страница безопасно сохранена')).toBeInTheDocument();
  });
});
