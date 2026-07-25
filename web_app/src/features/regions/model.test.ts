import { describe, expect, it } from 'vitest';

import {
  createManualRegion,
  mergeRegions,
  moveReadingOrder,
  moveRegion,
  regionBounds,
  resizeRegion,
  splitRegion,
  withContiguousOrder,
  type Region,
} from './model';

const craftRegion: Region = {
  id: '44444444-4444-4444-8444-444444444444',
  polygon: [
    { x: 0.1, y: 0.2 },
    { x: 0.8, y: 0.2 },
    { x: 0.8, y: 0.28 },
    { x: 0.1, y: 0.28 },
  ],
  readingOrder: 0,
  revision: 1,
  source: 'craft',
  flags: ['close_component_gap'],
  detectorVersion: 'craft_mlt_25k',
  detectorScore: 0.94,
};

describe('region edit model', () => {
  it('turns edited CRAFT geometry into an adjusted region while retaining detector evidence', () => {
    const moved = moveRegion(craftRegion, { x: 0.1, y: -0.4 });
    const resized = resizeRegion(moved, 'southeast', { x: 0.94, y: 0.4 });

    expect(resized.source).toBe('adjusted');
    expect(resized.detectorVersion).toBe('craft_mlt_25k');
    expect(resized.detectorScore).toBe(0.94);
    expect(regionBounds(resized)).toMatchObject({ minY: 0, maxX: 0.94, maxY: 0.4 });
  });

  it('splits and merges regions without generating out-of-image polygons', () => {
    const [top, bottom] = splitRegion(craftRegion, 'horizontal');
    const merged = mergeRegions([top, bottom], '55555555-5555-4555-8555-555555555555');

    expect(top.source).toBe('adjusted');
    expect(bottom.id).not.toBe(top.id);
    expect(merged).not.toBeNull();
    expect(merged?.source).toBe('adjusted');
    expect(merged?.flags).toContain('manual_merge');
    expect(
      merged?.polygon
        .flatMap((point) => [point.x, point.y])
        .every((value) => value >= 0 && value <= 1),
    ).toBe(true);
  });

  it('keeps reading order contiguous after manual additions and reordering', () => {
    const manual = createManualRegion(
      { minX: 0.1, minY: 0.5, maxX: 0.9, maxY: 0.58 },
      '66666666-6666-4666-8666-666666666666',
    );
    const ordered = withContiguousOrder([craftRegion, manual]);
    const moved = moveReadingOrder(ordered, manual.id, -1);

    expect(moved.map((region) => region.id)).toEqual([manual.id, craftRegion.id]);
    expect(moved.map((region) => region.readingOrder)).toEqual([0, 1]);
  });

  it('keeps overlapping regions separate until the reviewer explicitly merges them', () => {
    const overlapping = createManualRegion(
      { minX: 0.18, minY: 0.24, maxX: 0.88, maxY: 0.34 },
      '77777777-7777-4777-8777-777777777777',
    );
    const separate = withContiguousOrder([craftRegion, overlapping]);
    const merged = mergeRegions(separate, '88888888-8888-4888-8888-888888888888');

    expect(separate).toHaveLength(2);
    expect(separate.map((region) => region.readingOrder)).toEqual([0, 1]);
    expect(merged).not.toBeNull();
    expect(regionBounds(merged!)).toMatchObject({ minX: 0.1, minY: 0.2, maxX: 0.88, maxY: 0.34 });
  });
});
