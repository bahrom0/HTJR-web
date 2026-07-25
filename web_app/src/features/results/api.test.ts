import { describe, expect, it } from 'vitest';

import { parseRecognitionResult } from './api';

const ids = {
  job_id: '11111111-1111-4111-8111-111111111111',
  document_id: '22222222-2222-4222-8222-222222222222',
  page_id: '33333333-3333-4333-8333-333333333333',
};

describe('recognition result contract', () => {
  it('accepts a persisted raw result and preserves partial status', () => {
    expect(parseRecognitionResult({ ...ids, raw_text: 'сатр 1', is_partial: true })).toEqual({
      jobId: ids.job_id,
      documentId: ids.document_id,
      pageId: ids.page_id,
      rawText: 'сатр 1',
      isPartial: true,
    });
  });

  it('rejects an incomplete response', () => {
    expect(parseRecognitionResult({ ...ids, raw_text: 'сатр 1' })).toBeNull();
  });
});
