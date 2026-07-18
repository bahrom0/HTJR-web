import { environment } from '@shared/lib/env';
import type { ApiError, ApiResult } from '@shared/api/client';

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
function parseUpload(value: unknown): UploadDocument | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  const asset = item.asset as Record<string, unknown> | undefined;
  if (
    typeof item.document_id !== 'string' ||
    typeof item.page_id !== 'string' ||
    !asset ||
    typeof asset.id !== 'string' ||
    typeof asset.preview_url !== 'string' ||
    typeof asset.width !== 'number' ||
    typeof asset.height !== 'number' ||
    typeof asset.media_type !== 'string'
  )
    return null;
  return {
    documentId: item.document_id,
    pageId: item.page_id,
    duplicate: item.duplicate === true,
    asset: {
      id: asset.id,
      previewUrl: asset.preview_url,
      width: asset.width,
      height: asset.height,
      mediaType: asset.media_type,
    },
  };
}
function parseError(value: unknown, requestId: string): ApiError {
  if (value && typeof value === 'object') {
    const item = value as Record<string, unknown>;
    if (
      typeof item.code === 'string' &&
      typeof item.message === 'string' &&
      typeof item.retryable === 'boolean'
    )
      return {
        code: item.code,
        message: item.message,
        retryable: item.retryable,
        requestId: typeof item.request_id === 'string' ? item.request_id : requestId,
      };
  }
  return {
    code: 'network_error',
    message: 'Сервер недоступен. Файл сохранён на этом устройстве для повтора.',
    retryable: true,
    requestId,
  };
}
export async function uploadDocument(
  file: Blob,
  filename: string,
  idempotencyKey: string,
  csrfToken: string,
  signal?: AbortSignal,
): Promise<ApiResult<UploadDocument>> {
  const requestId = crypto.randomUUID();
  try {
    const timeout = AbortSignal.timeout(60_000);
    const response = await fetch(`${environment.apiBaseUrl}/documents`, {
      method: 'POST',
      credentials: 'include',
      body: file,
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      headers: {
        'Content-Type': file.type,
        'X-Request-ID': requestId,
        'X-CSRF-Token': csrfToken,
        'Idempotency-Key': idempotencyKey,
        'X-Original-Filename': encodeURIComponent(filename),
      },
    });
    const body: unknown = await response.json();
    if (!response.ok) return { ok: false, error: parseError(body, requestId) };
    const parsed = parseUpload(body);
    if (!parsed)
      return {
        ok: false,
        error: {
          code: 'invalid_response',
          message: 'Сервер вернул некорректный ответ.',
          retryable: false,
          requestId,
        },
      };
    return {
      ok: true,
      value: parsed,
      requestId: response.headers.get('X-Request-ID') ?? requestId,
    };
  } catch {
    return { ok: false, error: parseError(null, requestId) };
  }
}
