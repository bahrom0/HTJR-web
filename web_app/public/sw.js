const cacheName = 'tajik-htr-shell-v2';
const shellAssets = ['/', '/index.html', '/manifest.webmanifest', '/favicon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(cacheName)
      .then((cache) => cache.addAll(shellAssets))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== cacheName).map((key) => caches.delete(key))),
      ),
  );
  self.clients.claim();
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (
    event.request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/')
  )
    return;
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match('/index.html')));
    return;
  }
  event.respondWith(
    caches.match(event.request).then(
      async (cached) => {
        if (cached) return cached;

        const response = await fetch(event.request);
        if (response.ok) {
          // Clone before returning the original response.  Cloning later in a
          // nested promise races with the page consuming the response body.
          const responseForCache = response.clone();
          event.waitUntil(
            caches
              .open(cacheName)
              .then((cache) => cache.put(event.request, responseForCache))
              .catch(() => undefined),
          );
        }
        return response;
      },
    ),
  );
});
