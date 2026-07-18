import { isRouteErrorResponse, useRouteError } from 'react-router-dom';

import { ErrorState } from '@shared/ui';

export function RouteError() {
  const error = useRouteError();
  const title = isRouteErrorResponse(error)
    ? `Ошибка маршрута: ${error.status}`
    : 'Не удалось открыть раздел';
  return <ErrorState title={title} onRetry={() => window.location.reload()} />;
}
