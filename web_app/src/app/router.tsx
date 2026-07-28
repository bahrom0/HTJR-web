import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';

import { AppShell } from '@app/shell/AppShell';
import { RouteError } from '@app/shell/RouteError';
import { AccessGuard } from '@shared/access/AccessGuard';

const AccessRoute = lazy(() => import('@routes/access/AccessRoute'));
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

function RouteFallback() {
  return <p role="status">Открываем раздел…</p>;
}

function lazyRoute(element: React.ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { path: '/access', element: lazyRoute(<AccessRoute />) },
      { path: '/access/register', element: lazyRoute(<AccessRoute />) },
      { path: '/access/verify', element: lazyRoute(<AccessRoute />) },
      { path: '/access/recover', element: lazyRoute(<AccessRoute />) },
      { path: '/offline', element: lazyRoute(<OfflineRoute />) },
      {
        element: <AccessGuard />,
        children: [
          { path: '/', element: lazyRoute(<HomeRoute />) },
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
