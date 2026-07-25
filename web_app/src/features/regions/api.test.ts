import { describe, expect, it } from 'vitest';

import { parseRegionSnapshot } from './api';

const pageId = '11111111-1111-4111-8111-111111111111';
const regionId = '22222222-2222-4222-8222-222222222222';

describe('regions API contract mapping', () => {
  it('maps the server revision and CRAFT evidence without widening the contract', () => {
    const parsed = parseRegionSnapshot({
      page_id: pageId,
      revision: 7,
      confirmed: false,
      resumed_job_id: null,
      regions: [
        {
          id: regionId,
          polygon: [
            { x: 0.1, y: 0.2 },
            { x: 0.9, y: 0.2 },
            { x: 0.9, y: 0.3 },
            { x: 0.1, y: 0.3 },
          ],
          reading_order: 0,
          revision: 1,
          source: 'craft',
          flags: ['baseline_skew'],
          detector_version: 'craft_mlt_25k',
          detector_score: 0.91,
        },
      ],
    });

    expect(parsed).toMatchObject({ pageId, revision: 7, confirmed: false });
    expect(parsed?.regions[0]).toMatchObject({
      id: regionId,
      source: 'craft',
      detectorVersion: 'craft_mlt_25k',
      detectorScore: 0.91,
    });
  });

  it('rejects a craft region without detector provenance and non-contiguous order', () => {
    expect(
      parseRegionSnapshot({
        page_id: pageId,
        revision: 7,
        confirmed: false,
        regions: [
          {
            id: regionId,
            polygon: [
              { x: 0.1, y: 0.2 },
              { x: 0.9, y: 0.2 },
              { x: 0.9, y: 0.3 },
              { x: 0.1, y: 0.3 },
            ],
            reading_order: 1,
            revision: 1,
            source: 'craft',
            flags: [],
            detector_version: null,
            detector_score: null,
          },
        ],
      }),
    ).toBeNull();
  });
});
