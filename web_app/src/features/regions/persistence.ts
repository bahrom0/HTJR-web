import { databaseStores, transactStore } from '@shared/persistence/database';

import type { RegionDraft } from './model';

export function saveRegionDraft(draft: RegionDraft): Promise<void> {
  return transactStore(databaseStores.regionDrafts, 'readwrite', (store, done) => {
    store.put(draft);
    done();
  });
}

export function loadRegionDraft(pageId: string): Promise<RegionDraft | null> {
  return transactStore(databaseStores.regionDrafts, 'readonly', (store, done) => {
    const request = store.get(pageId);
    request.onsuccess = () => done((request.result as RegionDraft | undefined) ?? null);
  });
}

export function removeRegionDraft(pageId: string): Promise<void> {
  return transactStore(databaseStores.regionDrafts, 'readwrite', (store, done) => {
    store.delete(pageId);
    done();
  });
}
