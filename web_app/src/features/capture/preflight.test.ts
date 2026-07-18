import { describe, expect, it, vi } from 'vitest';
import { CLIENT_UPLOAD_MAX_BYTES, preflightImage } from './preflight';

describe('capture preflight', () => {
  it('rejects unsupported and oversized files before decoding', async () => {
    expect(await preflightImage(new File(['text'], 'notes.txt', { type: 'text/plain' }))).toContain(
      'JPEG',
    );
    const oversized = new File([new Uint8Array(CLIENT_UPLOAD_MAX_BYTES + 1)], 'large.png', {
      type: 'image/png',
    });
    expect(await preflightImage(oversized)).toContain('25 МБ');
  });

  it('checks decoded pixel dimensions and closes the bitmap', async () => {
    const close = vi.fn();
    vi.stubGlobal(
      'createImageBitmap',
      vi.fn().mockResolvedValue({ width: 13_000, height: 10, close }),
    );
    expect(
      (await preflightImage(new File(['png'], 'page.png', { type: 'image/png' })))?.toLowerCase(),
    ).toContain('разрешение');
    expect(close).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });
});
