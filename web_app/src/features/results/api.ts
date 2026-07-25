import { isUuid, request, type ApiResult } from '@shared/api/client';

export type RecognitionResult = Readonly<{
  jobId: string;
  documentId: string;
  pageId: string;
  rawText: string;
  isPartial: boolean;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseRecognitionResult(value: unknown): RecognitionResult | null {
  if (!isRecord(value)) return null;
  if (
    !isUuid(value.job_id) ||
    !isUuid(value.document_id) ||
    !isUuid(value.page_id) ||
    typeof value.raw_text !== 'string' ||
    typeof value.is_partial !== 'boolean'
  ) {
    return null;
  }
  return {
    jobId: value.job_id,
    documentId: value.document_id,
    pageId: value.page_id,
    rawText: value.raw_text,
    isPartial: value.is_partial,
  };
}

export function getRecognitionResult(jobId: string): Promise<ApiResult<RecognitionResult>> {
  return request(`/jobs/${encodeURIComponent(jobId)}/result`, parseRecognitionResult);
}
