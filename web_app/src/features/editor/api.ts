import { request, type ApiResult } from '@shared/api/client';

import type { DocumentItem } from '@entities/document';
import type { LineBlock } from './model';

export type EditorDocument = Readonly<{
  document: DocumentItem;
  lines: LineBlock[];
}>;

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
  ) return null;
  if (!['draft', 'processing', 'review', 'ready', 'failed'].includes(value.status)) return null;
  return {
    id: value.id,
    title: value.title,
    status: value.status as DocumentItem['status'],
    revision: value.revision,
    pageCount: value.page_count,
    createdAt: value.created_at,
    updatedAt: value.updated_at,
    ...(typeof value.latest_job_id === 'string' ? { latestJobId: value.latest_job_id } : {}),
    ...(typeof value.preview_url === 'string' ? { previewUrl: value.preview_url } : {}),
    ...(typeof value.preview_text === 'string' ? { previewText: value.preview_text } : {}),
  };
}

function parseEditor(value: unknown): EditorDocument | null {
  if (!isRecord(value) || !Array.isArray(value.lines)) return null;
  const document = parseDocument(value.document);
  if (!document) return null;
  const lines = value.lines.map((line): LineBlock | null => {
    if (
      !isRecord(line) ||
      typeof line.id !== 'string' ||
      typeof line.page_id !== 'string' ||
      typeof line.position !== 'number' ||
      typeof line.raw_text !== 'string' ||
      typeof line.text !== 'string' ||
      typeof line.status !== 'string' ||
      typeof line.revision !== 'number' ||
      typeof line.crop_url !== 'string'
    ) return null;
    if (!['unverified', 'confirmed', 'edited'].includes(line.status)) return null;
    return {
      id: line.id,
      pageId: line.page_id,
      lineNumber: line.position + 1,
      rawText: line.raw_text,
      editedText: line.text,
      status: line.status as LineBlock['status'],
      revision: line.revision,
      cropUrl: line.crop_url,
    };
  });
  if (!lines.every((line): line is LineBlock => line !== null)) return null;
  return { document, lines };
}

function parseMutation(value: unknown): { revision: number; status?: string } | null {
  if (!isRecord(value) || typeof value.revision !== 'number') return null;
  return {
    revision: value.revision,
    ...(typeof value.status === 'string' ? { status: value.status } : {}),
  };
}

export function getEditorDocument(
  documentId: string,
  signal?: AbortSignal,
): Promise<ApiResult<EditorDocument>> {
  return request(`/documents/${encodeURIComponent(documentId)}/editor`, parseEditor, { signal });
}

export function saveLineDraft(
  line: Pick<LineBlock, 'id' | 'editedText' | 'revision'>,
  csrfToken: string,
): Promise<ApiResult<{ revision: number; status?: string }>> {
  return request(`/text-lines/${encodeURIComponent(line.id)}/draft`, parseMutation, {
    method: 'PUT',
    csrfToken,
    json: { text: line.editedText, revision: line.revision },
  });
}

export function confirmEditorLine(
  line: Pick<LineBlock, 'id' | 'editedText' | 'revision'>,
  csrfToken: string,
): Promise<ApiResult<{ revision: number; status?: string }>> {
  return request(`/text-lines/${encodeURIComponent(line.id)}/confirm`, parseMutation, {
    method: 'POST',
    csrfToken,
    json: {
      text: line.editedText,
      revision: line.revision,
      idempotency_key: crypto.randomUUID(),
    },
  });
}
