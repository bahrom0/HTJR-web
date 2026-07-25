export type PendingUpload = Readonly<{
  idempotencyKey: string;
  file: Blob;
  filename: string;
  mediaType: string;
  createdAt: string;
}>;
import { databaseStores, transactStore } from '@shared/persistence/database';
export function savePendingUpload(upload: PendingUpload): Promise<void> {
  return transactStore(databaseStores.uploadOutbox, 'readwrite', (store, done) => {
    store.put(upload);
    done();
  });
}
export function removePendingUpload(idempotencyKey: string): Promise<void> {
  return transactStore(databaseStores.uploadOutbox, 'readwrite', (store, done) => {
    store.delete(idempotencyKey);
    done();
  });
}
export function listPendingUploads(): Promise<PendingUpload[]> {
  return transactStore(databaseStores.uploadOutbox, 'readonly', (store, done) => {
    const request = store.getAll();
    request.onsuccess = () =>
      done(
        (request.result as PendingUpload[]).sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
      );
  });
}
