export type PendingUpload = Readonly<{
  idempotencyKey: string;
  file: Blob;
  filename: string;
  mediaType: string;
  createdAt: string;
}>;
const DATABASE = 'tajik-htr-studio';
const VERSION = 1;
const STORE = 'upload-outbox';

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, VERSION);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE))
        request.result.createObjectStore(STORE, { keyPath: 'idempotencyKey' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB unavailable'));
  });
}

async function transact<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore, done: (value: T) => void) => void,
): Promise<T> {
  const database = await openDatabase();
  return new Promise<T>((resolve, reject) => {
    const transaction = database.transaction(STORE, mode);
    let value: T;
    run(transaction.objectStore(STORE), (result) => {
      value = result;
    });
    transaction.oncomplete = () => {
      database.close();
      resolve(value);
    };
    transaction.onerror = () => {
      database.close();
      reject(transaction.error ?? new Error('Outbox transaction failed'));
    };
    transaction.onabort = () => {
      database.close();
      reject(transaction.error ?? new Error('Outbox transaction aborted'));
    };
  });
}
export function savePendingUpload(upload: PendingUpload): Promise<void> {
  return transact('readwrite', (store, done) => {
    store.put(upload);
    done();
  });
}
export function removePendingUpload(idempotencyKey: string): Promise<void> {
  return transact('readwrite', (store, done) => {
    store.delete(idempotencyKey);
    done();
  });
}
export function listPendingUploads(): Promise<PendingUpload[]> {
  return transact('readonly', (store, done) => {
    const request = store.getAll();
    request.onsuccess = () =>
      done(
        (request.result as PendingUpload[]).sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
      );
  });
}
