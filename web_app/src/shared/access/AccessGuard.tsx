import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAccess } from './AccessProvider';
import { LoadingState } from '@shared/ui';

export function AccessGuard() {
  const access = useAccess();
  const location = useLocation();
  if (access.state === 'checking')
    return (
      <LoadingState
        title="Проверяем сессию"
        description="Подключаем защищённое рабочее пространство."
      />
    );
  if (access.state === 'anonymous')
    return (
      <Navigate
        to="/access"
        replace
        state={{ returnTo: `${location.pathname}${location.search}` }}
      />
    );
  return <Outlet />;
}
