import { databaseStores, transactStore } from '@shared/persistence/database';

import type { PreparationDraft } from './model';

export function savePreparationDraft(draft: PreparationDraft): Promise<void> {
  return transactStore(databaseStores.preparationDrafts, 'readwrite', (store, done) => {
    store.put(draft);
    done();
  });
}

export function loadPreparationDraft(pageId: string): Promise<PreparationDraft | null> {
  return transactStore(databaseStores.preparationDrafts, 'readonly', (store, done) => {
    const request = store.get(pageId);
    request.onsuccess = () => done((request.result as PreparationDraft | undefined) ?? null);
  });
}

export function removePreparationDraft(pageId: string): Promise<void> {
  return transactStore(databaseStores.preparationDrafts, 'readwrite', (store, done) => {
    store.delete(pageId);
    done();
  });
}
