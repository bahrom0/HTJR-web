import React from 'react';
import { RouterProvider, createBrowserRouter, createRoutesFromElements, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './components/ThemeProvider';
import { Layout } from './components/Layout';
import { Landing } from './pages/Landing';
import { Home } from './pages/Home';
import { NewDocument } from './pages/NewDocument';
import { Prepare } from './pages/Prepare';
import { Regions } from './pages/Regions';
import { Processing } from './pages/Processing';
import { DocumentEditor } from './pages/DocumentEditor';
import { Documents } from './pages/Documents';
import { Settings } from './pages/Settings';

const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      <Route element={<Layout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/dashboard" element={<Home />} />
        <Route path="/documents" element={<Documents />} />
        <Route path="/documents/:documentId" element={<DocumentEditor />} />
        <Route path="/recognition/new" element={<NewDocument />} />
        <Route path="/documents/:documentId/pages/:pageId/prepare" element={<Prepare />} />
        <Route path="/documents/:documentId/pages/:pageId/regions" element={<Regions />} />
        <Route path="/documents/:documentId/pages/:pageId/processing" element={<Processing />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </>
  )
);

export default function App() {
  return (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  );
}
