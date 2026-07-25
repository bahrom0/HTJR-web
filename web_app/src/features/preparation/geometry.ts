import type { NormalizedPoint } from './model';

export type Viewport = Readonly<{ width: number; height: number }>;
export type ImageSize = Readonly<{ width: number; height: number }>;
export type Transform = Readonly<{ scale: number; offsetX: number; offsetY: number }>;

export function fitTransform(image: ImageSize, viewport: Viewport, padding = 16): Transform {
  const availableWidth = Math.max(1, viewport.width - padding * 2);
  const availableHeight = Math.max(1, viewport.height - padding * 2);
  const scale = Math.min(availableWidth / image.width, availableHeight / image.height);
  return {
    scale,
    offsetX: (viewport.width - image.width * scale) / 2,
    offsetY: (viewport.height - image.height * scale) / 2,
  };
}

export function zoomTransform(
  transform: Transform,
  factor: number,
  anchor: NormalizedPoint,
): Transform {
  const scale = Math.min(8, Math.max(0.1, transform.scale * factor));
  return {
    scale,
    offsetX: anchor.x - (anchor.x - transform.offsetX) * (scale / transform.scale),
    offsetY: anchor.y - (anchor.y - transform.offsetY) * (scale / transform.scale),
  };
}

export function normalizedToCanvas(
  point: NormalizedPoint,
  image: ImageSize,
  transform: Transform,
): NormalizedPoint {
  return {
    x: transform.offsetX + point.x * image.width * transform.scale,
    y: transform.offsetY + point.y * image.height * transform.scale,
  };
}

export function canvasToNormalized(
  point: NormalizedPoint,
  image: ImageSize,
  transform: Transform,
): NormalizedPoint {
  return {
    x: (point.x - transform.offsetX) / (image.width * transform.scale),
    y: (point.y - transform.offsetY) / (image.height * transform.scale),
  };
}
