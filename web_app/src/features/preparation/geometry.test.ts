import { describe, expect, it } from 'vitest';

import { canvasToNormalized, fitTransform, normalizedToCanvas, zoomTransform } from './geometry';

describe('preparation geometry', () => {
  it.each([
    { width: 1200, height: 1600 },
    { width: 2200, height: 900 },
  ])('fits portrait and landscape images without cropping', (image) => {
    const view = fitTransform(image, { width: 360, height: 480 });
    expect(image.width * view.scale).toBeLessThanOrEqual(328);
    expect(image.height * view.scale).toBeLessThanOrEqual(448);
  });

  it('round-trips normalized coordinates after zoom and pan', () => {
    const image = { width: 1600, height: 1000 };
    const fit = fitTransform(image, { width: 900, height: 600 });
    const zoomed = zoomTransform(fit, 1.8, { x: 420, y: 280 });
    const point = { x: 0.35, y: 0.7 };
    const canvas = normalizedToCanvas(point, image, zoomed);
    const restored = canvasToNormalized(canvas, image, zoomed);
    expect(restored.x).toBeCloseTo(point.x, 12);
    expect(restored.y).toBeCloseTo(point.y, 12);
  });

  it('bounds wheel and pinch zoom to a safe finite range', () => {
    const initial = { scale: 1, offsetX: 0, offsetY: 0 };
    expect(zoomTransform(initial, 100, { x: 0, y: 0 }).scale).toBe(8);
    expect(zoomTransform(initial, 0.0001, { x: 0, y: 0 }).scale).toBe(0.1);
  });
});
