import { isUuid, request, type ApiResult } from '@shared/api/client';

export type UploadDocument = Readonly<{
  documentId: string;
  pageId: string;
  asset: Readonly<{
    id: string;
    mediaType: string;
    width: number;
    height: number;
    previewUrl: string;
  }>;
  duplicate: boolean;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseUpload(value: unknown): UploadDocument | null {
  if (!isRecord(value) || !isRecord(value.asset)) return null;
  const asset = value.asset;
  if (
    !isUuid(value.document_id) ||
    !isUuid(value.page_id) ||
    !isUuid(asset.id) ||
    typeof asset.preview_url !== 'string' ||
    !asset.preview_url.startsWith('/api/v1/assets/') ||
    typeof asset.width !== 'number' ||
    !Number.isInteger(asset.width) ||
    asset.width <= 0 ||
    typeof asset.height !== 'number' ||
    !Number.isInteger(asset.height) ||
    asset.height <= 0 ||
    typeof asset.media_type !== 'string' ||
    typeof value.duplicate !== 'boolean'
  ) {
    return null;
  }
  return {
    documentId: value.document_id,
    pageId: value.page_id,
    duplicate: value.duplicate,
    asset: {
      id: asset.id,
      previewUrl: asset.preview_url,
      width: asset.width,
      height: asset.height,
      mediaType: asset.media_type,
    },
  };
}

export function uploadDocument(
  file: Blob,
  filename: string,
  idempotencyKey: string,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<UploadDocument>> {
  return request('/documents', parseUpload, {
    method: 'POST',
    body: file,
    signal,
    timeoutMs: 60_000,
    csrfToken,
    headers: {
      'Content-Type': file.type,
      'Idempotency-Key': idempotencyKey,
      'X-Original-Filename': encodeURIComponent(filename),
    },
  });
}
