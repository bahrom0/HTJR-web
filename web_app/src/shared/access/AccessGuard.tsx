import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAccess } from './AccessProvider';

export function AccessGuard() {
  const access = useAccess();
  const location = useLocation();
  if (access.state === 'checking') return <p className="access-check" role="status">Проверяем защищённую сессию…</p>;
  if (access.state === 'anonymous') return <Navigate to="/access" replace state={{ returnTo: `${location.pathname}${location.search}` }} />;
  return <Outlet />;
}
