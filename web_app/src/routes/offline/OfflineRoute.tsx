import { useState } from 'react';

import { Button, OfflineState } from '@shared/ui';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';

export default function OfflineRoute() {
  const isOnline = useNetworkStatus();
  const [hasRetried, setHasRetried] = useState(false);
  if (isOnline) {
    return (
      <section className="shell-page">
        <OfflineState />
        <p>
          Подключение восстановлено. Серверные действия будут доступны после настройки access
          session.
        </p>
      </section>
    );
  }
  return (
    <section className="shell-page">
      <OfflineState />
      <p>
        {hasRetried
          ? 'Подключение пока не восстановлено.'
          : 'Распознавание требует сервер и не выполняется офлайн.'}
      </p>
      <Button variant="secondary" onClick={() => setHasRetried(true)}>
        Проверить снова
      </Button>
    </section>
  );
}
