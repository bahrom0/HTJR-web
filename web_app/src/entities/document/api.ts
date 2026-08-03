import { request, type ApiResult } from '@shared/api/client';

import type { DocumentItem } from './model';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseDocument(value: unknown): DocumentItem | null {
  if (
    !isRecord(value) ||
    typeof value.id !== 'string' ||
    typeof value.title !== 'string' ||
    typeof value.status !== 'string' ||
    typeof value.revision !== 'number' ||
    typeof value.page_count !== 'number' ||
    typeof value.created_at !== 'string' ||
    typeof value.updated_at !== 'string'
  ) {
    return null;
  }
  if (!['draft', 'processing', 'review', 'ready', 'failed'].includes(value.status)) return null;
  return {
    id: value.id,
    title: value.title,
    revision: value.revision,
    pageCount: value.page_count,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    status: value.status as DocumentItem['status'],
    ...(typeof value.latest_job_id === 'string' ? { latestJobId: value.latest_job_id } : {}),
    ...(typeof value.preview_url === 'string' ? { previewUrl: value.preview_url } : {}),
    ...(typeof value.preview_text === 'string' ? { previewText: value.preview_text } : {}),
  };
}

function parseDocumentList(value: unknown): DocumentItem[] | null {
  if (!isRecord(value) || !Array.isArray(value.items)) return null;
  const items = value.items.map(parseDocument);
  return items.every((item): item is DocumentItem => item !== null) ? items : null;
}

export function getDocuments(query = '', signal?: AbortSignal): Promise<ApiResult<DocumentItem[]>> {
  const search = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : '';
  return request(`/documents${search}`, parseDocumentList, { signal });
}

export function getDocument(id: string, signal?: AbortSignal): Promise<ApiResult<DocumentItem>> {
  return request(`/documents/${encodeURIComponent(id)}`, parseDocument, { signal });
}

export function deleteDocument(
  document: Pick<DocumentItem, 'id' | 'revision'>,
  csrfToken: string,
): Promise<ApiResult<true>> {
  return request(`/documents/${encodeURIComponent(document.id)}`, () => true, {
    method: 'DELETE',
    csrfToken,
    json: { revision: document.revision },
  });
}
