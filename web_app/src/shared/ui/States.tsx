import { type ReactNode } from 'react';

import { Button } from './Button';
import { Skeleton } from './Surface';

export function LoadingState({
  title = 'Загружаем данные',
  description = 'Это займёт несколько секунд.',
}: Readonly<{ title?: string; description?: string }>) {
  return (
    <section className="ui-state ui-state--loading" role="status" aria-live="polite">
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="ui-state__skeletons" aria-hidden="true">
        <Skeleton />
        <Skeleton />
        <Skeleton />
      </div>
    </section>
  );
}

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

export function PartialState({
  title = 'Результат готов частично',
  children,
  action,
}: Readonly<{ title?: string; children: ReactNode; action?: ReactNode }>) {
  return (
    <section className="ui-state ui-state--partial" role="status">
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </section>
  );
}
