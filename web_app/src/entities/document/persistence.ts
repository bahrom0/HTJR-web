import { databaseStores, transactStore } from '@shared/persistence/database';

import type { DocumentItem } from './model';

const CACHE_KEY = 'all';
type DocumentCache = Readonly<{ cacheKey: string; items: DocumentItem[]; updatedAt: string }>;

export function saveDocumentCache(items: readonly DocumentItem[]): Promise<void> {
  return transactStore(databaseStores.documentCache, 'readwrite', (store, done) => {
    store.put({ cacheKey: CACHE_KEY, items: [...items], updatedAt: new Date().toISOString() } satisfies DocumentCache);
    done();
  });
}

export function loadDocumentCache(): Promise<DocumentItem[]> {
  return transactStore(databaseStores.documentCache, 'readonly', (store, done) => {
    const request = store.get(CACHE_KEY);
    request.onsuccess = () => done((request.result as DocumentCache | undefined)?.items ?? []);
  });
}
