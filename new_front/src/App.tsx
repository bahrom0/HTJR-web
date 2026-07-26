import React from 'react';
import { RouterProvider, createBrowserRouter, createRoutesFromElements, Route, Navigate, useLocation } from 'react-router-dom';
import { useAppStore } from './lib/store';
import { ThemeProvider } from './components/ThemeProvider';
import { Layout } from './components/Layout';
import { SignIn } from './pages/SignIn';
import { SignUp } from './pages/SignUp';
import { Recover } from './pages/Recover';
import { Verify } from './pages/Verify';
import { Home } from './pages/Home';
import { NewDocument } from './pages/NewDocument';
import { Prepare } from './pages/Prepare';
import { Regions } from './pages/Regions';
import { Processing } from './pages/Processing';
import { DocumentEditor } from './pages/DocumentEditor';
import { Documents } from './pages/Documents';
import { Settings } from './pages/Settings';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const user = useAppStore(state => state.user);
  const location = useLocation();
  if (!user) {
    return <Navigate to="/auth/sign-in" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}

const router = createBrowserRouter(
  createRoutesFromElements(
    <>
      <Route path="/auth/sign-in" element={<SignIn />} />
      <Route path="/auth/sign-up" element={<SignUp />} />
      <Route path="/auth/recover" element={<Recover />} />
      <Route path="/auth/verify" element={<Verify />} />
      <Route path="/" element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route index element={<Home />} />
        <Route path="documents" element={<Documents />} />
        <Route path="documents/:documentId" element={<DocumentEditor />} />
        <Route path="recognition/new" element={<NewDocument />} />
        <Route path="documents/:documentId/pages/:pageId/prepare" element={<Prepare />} />
        <Route path="documents/:documentId/pages/:pageId/regions" element={<Regions />} />
        <Route path="documents/:documentId/pages/:pageId/processing" element={<Processing />} />
        <Route path="settings" element={<Settings />} />
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
