const DATABASE_NAME = 'tajik-htr-studio';
const DATABASE_VERSION = 3;

export const databaseStores = {
  uploadOutbox: 'upload-outbox',
  preparationDrafts: 'preparation-drafts',
  regionDrafts: 'region-drafts',
} as const;

export type DatabaseStore = (typeof databaseStores)[keyof typeof databaseStores];

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(databaseStores.uploadOutbox)) {
        database.createObjectStore(databaseStores.uploadOutbox, { keyPath: 'idempotencyKey' });
      }
      if (!database.objectStoreNames.contains(databaseStores.preparationDrafts)) {
        database.createObjectStore(databaseStores.preparationDrafts, { keyPath: 'pageId' });
      }
      if (!database.objectStoreNames.contains(databaseStores.regionDrafts)) {
        database.createObjectStore(databaseStores.regionDrafts, { keyPath: 'pageId' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB unavailable'));
  });
}

export async function transactStore<T>(
  storeName: DatabaseStore,
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore, resolve: (value: T) => void) => void,
): Promise<T> {
  const database = await openDatabase();
  return new Promise<T>((resolve, reject) => {
    const transaction = database.transaction(storeName, mode);
    let value: T;
    run(transaction.objectStore(storeName), (result) => {
      value = result;
    });
    transaction.oncomplete = () => {
      database.close();
      resolve(value);
    };
    transaction.onerror = () => {
      database.close();
      reject(transaction.error ?? new Error('IndexedDB transaction failed'));
    };
    transaction.onabort = () => {
      database.close();
      reject(transaction.error ?? new Error('IndexedDB transaction aborted'));
    };
  });
}
