import { databaseStores, transactStore } from '@shared/persistence/database';

import type { EditorDocument } from './api';

type EditorCache = Readonly<{ documentId: string; value: EditorDocument; updatedAt: string }>;

export function saveEditorDraft(documentId: string, value: EditorDocument): Promise<void> {
  return transactStore(databaseStores.editorDrafts, 'readwrite', (store, done) => {
    store.put({ documentId, value, updatedAt: new Date().toISOString() } satisfies EditorCache);
    done();
  });
}

export function loadEditorDraft(documentId: string): Promise<EditorDocument | null> {
  return transactStore(databaseStores.editorDrafts, 'readonly', (store, done) => {
    const request = store.get(documentId);
    request.onsuccess = () => done((request.result as EditorCache | undefined)?.value ?? null);
  });
}
