import { describe, expect, it } from 'vitest';

import { canvasToNormalized, fitTransform, normalizedToCanvas, zoomTransform } from './geometry';

describe('region canvas geometry', () => {
  it.each([
    { width: 1920, height: 1080 },
    { width: 860, height: 1810 },
  ])('fits the complete prepared image inside the viewport', (image) => {
    const view = fitTransform(image, { width: 768, height: 560 });
    expect(image.width * view.scale).toBeLessThanOrEqual(736);
    expect(image.height * view.scale).toBeLessThanOrEqual(528);
  });

  it('round-trips normalized region coordinates after pan and zoom', () => {
    const image = { width: 2400, height: 1600 };
    const fit = fitTransform(image, { width: 1024, height: 720 });
    const zoomed = zoomTransform(
      { ...fit, offsetX: fit.offsetX + 37, offsetY: fit.offsetY - 24 },
      2.15,
      {
        x: 510,
        y: 340,
      },
    );
    const point = { x: 0.7234, y: 0.1827 };

    const restored = canvasToNormalized(normalizedToCanvas(point, image, zoomed), image, zoomed);
    expect(restored.x).toBeCloseTo(point.x, 12);
    expect(restored.y).toBeCloseTo(point.y, 12);
  });

  it('keeps zoom bounded for pointer and touch gestures', () => {
    const initial = { scale: 1, offsetX: 0, offsetY: 0 };
    expect(zoomTransform(initial, 100, { x: 0, y: 0 }).scale).toBe(8);
    expect(zoomTransform(initial, 0.0001, { x: 0, y: 0 }).scale).toBe(0.1);
  });
});
