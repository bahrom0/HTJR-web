import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';

import { AppShell } from '@app/shell/AppShell';
import { RouteError } from '@app/shell/RouteError';
import { AccessGuard } from '@shared/access/AccessGuard';
import { LoadingState } from '@shared/ui';

const AccessRoute = lazy(() => import('@routes/access/AccessRoute'));
const LandingRoute = lazy(() => import('@routes/landing/LandingRoute'));
const HomeRoute = lazy(() => import('@routes/home/HomeRoute'));
const OfflineRoute = lazy(() => import('@routes/offline/OfflineRoute'));
const NotFoundRoute = lazy(() => import('@routes/not-found/NotFoundRoute'));
const CaptureRoute = lazy(() => import('@routes/capture/CaptureRoute'));
const PreparationRoute = lazy(() => import('@routes/preparation/PreparationRoute'));
const RegionReviewRoute = lazy(() => import('@routes/regions/RegionReviewRoute'));
const ResultRoute = lazy(() => import('@routes/result/ResultRoute'));
const ProcessingRoute = lazy(() => import('@routes/processing/ProcessingRoute'));
const SettingsRoute = lazy(() => import('@routes/settings/SettingsRoute'));
const DocumentsRoute = lazy(() => import('@routes/documents/DocumentsRoute'));
const EditorRoute = lazy(() => import('@routes/editor/EditorRoute'));
const ExportRoute = lazy(() => import('@routes/export/ExportRoute'));
const DemoRoute = lazy(() => import('@routes/demo/DemoRoute'));

function RouteFallback() {
  return <LoadingState title="Открываем раздел" description="Загружаем интерфейс." />;
}

function lazyRoute(element: React.ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { path: '/', element: lazyRoute(<LandingRoute />) },
      { path: '/access', element: <Navigate to="/app" replace /> },
      { path: '/access/register', element: <Navigate to="/app" replace /> },
      { path: '/offline', element: lazyRoute(<OfflineRoute />) },
      { path: '/0', element: lazyRoute(<DemoRoute />) },
      {
        element: <AccessGuard />,
        children: [
          { path: '/app', element: lazyRoute(<HomeRoute />) },
          { path: '/capture', element: lazyRoute(<CaptureRoute />) },
          { path: '/preparation', element: lazyRoute(<PreparationRoute />) },
          { path: '/regions', element: lazyRoute(<RegionReviewRoute />) },
          { path: '/result', element: lazyRoute(<ResultRoute />) },
          { path: '/processing', element: lazyRoute(<ProcessingRoute />) },
          { path: '/settings', element: lazyRoute(<SettingsRoute />) },
          { path: '/documents', element: lazyRoute(<DocumentsRoute />) },
          { path: '/documents/:documentId', element: lazyRoute(<DocumentsRoute />) },
          { path: '/organizer', element: <Navigate to="/documents" replace /> },
          { path: '/editor', element: lazyRoute(<EditorRoute />) },
          { path: '/review', element: <Navigate to="/editor" replace /> },
          { path: '/export', element: lazyRoute(<ExportRoute />) },
          { path: '/diagnostics', element: <Navigate to="/settings" replace /> },
        ],
      },
      { path: '*', element: lazyRoute(<NotFoundRoute />) },
    ],
  },
]);
