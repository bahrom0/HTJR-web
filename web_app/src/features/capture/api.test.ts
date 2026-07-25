import { describe, expect, it } from 'vitest';

import { parseUpload } from './api';

describe('parseUpload', () => {
  const valid = {
    document_id: '2ea62ed2-cbe8-4ad6-a448-2e17db982ea2',
    page_id: '5f62f690-241f-491b-888f-d7f224c1bf14',
    duplicate: false,
    asset: {
      id: 'c7c85286-9599-42d5-ab81-9badf40e986d',
      media_type: 'image/png',
      width: 1200,
      height: 800,
      preview_url: '/api/v1/assets/c7c85286-9599-42d5-ab81-9badf40e986d/preview',
    },
  };

  it('maps the validated upload contract', () => {
    expect(parseUpload(valid)).toEqual({
      documentId: valid.document_id,
      pageId: valid.page_id,
      duplicate: false,
      asset: {
        id: valid.asset.id,
        mediaType: 'image/png',
        width: 1200,
        height: 800,
        previewUrl: valid.asset.preview_url,
      },
    });
  });

  it('rejects unstable identifiers and non-positive dimensions', () => {
    expect(parseUpload({ ...valid, document_id: 'document-1' })).toBeNull();
    expect(parseUpload({ ...valid, asset: { ...valid.asset, width: 0 } })).toBeNull();
  });
});
