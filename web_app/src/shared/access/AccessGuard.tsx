import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAccess } from './AccessProvider';
import { LoadingState } from '@shared/ui';

export function AccessGuard() {
  const access = useAccess();
  const location = useLocation();
  if (access.state === 'checking')
    return (
      <LoadingState
        title="Подключаем сессию"
        description="Подготавливаем рабочее пространство."
      />
    );
  return <Outlet />;
}
