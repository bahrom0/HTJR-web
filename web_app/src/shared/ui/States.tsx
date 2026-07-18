import { type ReactNode } from 'react';

import { Button } from './Button';

export function EmptyState({
  title,
  children,
  action,
}: Readonly<{ title: string; children: ReactNode; action?: ReactNode }>) {
  return (
    <section className="ui-state">
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </section>
  );
}

export function ErrorState({
  title = 'Не удалось загрузить данные',
  onRetry,
}: Readonly<{ title?: string; onRetry?: () => void }>) {
  return (
    <section className="ui-state ui-state--error" role="alert">
      <h2>{title}</h2>
      <p>Проверьте соединение и повторите действие.</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      ) : null}
    </section>
  );
}

export function OfflineState() {
  return (
    <section className="ui-state ui-state--offline" role="status">
      <h2>Нет подключения</h2>
      <p>Серверные действия станут доступны после восстановления сети.</p>
    </section>
  );
}
