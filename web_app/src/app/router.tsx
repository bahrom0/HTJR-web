import { lazy, Suspense } from 'react';
import { createBrowserRouter } from 'react-router-dom';

import { AppShell } from '@app/shell/AppShell';
import { RouteError } from '@app/shell/RouteError';
import { AccessGuard } from '@shared/access/AccessGuard';

const AccessRoute = lazy(() => import('@routes/access/AccessRoute'));
const HomeRoute = lazy(() => import('@routes/home/HomeRoute'));
const OfflineRoute = lazy(() => import('@routes/offline/OfflineRoute'));
const NotFoundRoute = lazy(() => import('@routes/not-found/NotFoundRoute'));
const WorkspaceRoute = lazy(() => import('@routes/workspace/WorkspaceRoute'));
const CaptureRoute = lazy(() => import('@routes/capture/CaptureRoute'));
const PreparationRoute = lazy(() => import('@routes/preparation/PreparationRoute'));
const RegionReviewRoute = lazy(() => import('@routes/regions/RegionReviewRoute'));
const ResultRoute = lazy(() => import('@routes/result/ResultRoute'));
const ProcessingRoute = lazy(() => import('@routes/processing/ProcessingRoute'));
const SettingsRoute = lazy(() => import('@routes/settings/SettingsRoute'));
const DocumentsRoute = lazy(() => import('@routes/documents/DocumentsRoute'));
const EditorRoute = lazy(() => import('@routes/editor/EditorRoute'));

function RouteFallback() {
  return <p role="status">Открываем раздел…</p>;
}

function lazyRoute(element: React.ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

const workspaceRoutes = [
  [
    '/preparation',
    'Подготовка изображения',
    'Подготовка станет доступна после безопасного импорта файла.',
  ],
  ['/editor', 'Редактор', 'Редактор откроется после появления версионируемого текста.'],
  ['/review', 'Проверка мест', 'Проверка появится после explainable Tajik suggestions.'],
  ['/documents', 'Документы', 'Список появится после серверного хранилища документов.'],
  ['/documents/:documentId', 'Документ', 'Детали доступны после document API.'],
  ['/organizer', 'Страницы', 'Организатор появится вместе с multi-page document model.'],
  ['/export', 'Экспорт', 'Экспорт будет доступен только для confirmed text.'],
  ['/diagnostics', 'Диагностика', 'Диагностика покажет только безопасные runtime данные.'],
] as const;

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { path: '/access', element: lazyRoute(<AccessRoute />) },
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
          { path: '/editor', element: lazyRoute(<EditorRoute />) },
          ...workspaceRoutes
            .filter(
              ([path]) =>
                path !== '/preparation' &&
                path !== '/documents' &&
                path !== '/documents/:documentId' &&
                path !== '/editor',
            )
            .map(([path, title, description]) => ({
              path,
              element: lazyRoute(<WorkspaceRoute title={title} description={description} />),
            })),
        ],
      },
      { path: '*', element: lazyRoute(<NotFoundRoute />) },
    ],
  },
]);
