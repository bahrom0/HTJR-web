import { useEffect, useState } from 'react';

import { Button } from '@shared/ui';

export function PwaUpdateNotice() {
  const [waitingWorker, setWaitingWorker] = useState<ServiceWorker | null>(null);

  useEffect(() => {
    if (!('serviceWorker' in navigator) || !import.meta.env.PROD) return undefined;
    let hasReloaded = false;
    const onControllerChange = () => {
      if (!hasReloaded) {
        hasReloaded = true;
        window.location.reload();
      }
    };
    const onUpdateFound = (registration: ServiceWorkerRegistration) => {
      const installing = registration.installing;
      if (!installing) return;
      installing.addEventListener('statechange', () => {
        if (installing.state === 'installed' && navigator.serviceWorker.controller) {
          setWaitingWorker(registration.waiting);
        }
      });
    };
    navigator.serviceWorker.addEventListener('controllerchange', onControllerChange);
    void navigator.serviceWorker.getRegistration().then((registration) => {
      if (!registration) return;
      if (registration.waiting) setWaitingWorker(registration.waiting);
      registration.addEventListener('updatefound', () => onUpdateFound(registration));
    });
    return () =>
      navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
  }, []);

  if (!waitingWorker) return null;
  return (
    <aside className="pwa-update" role="status" aria-live="polite">
      <p>Доступна новая версия оболочки.</p>
      <Button onClick={() => waitingWorker.postMessage({ type: 'SKIP_WAITING' })}>Обновить</Button>
    </aside>
  );
}
