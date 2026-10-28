import React, { lazy, useCallback, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import './index.css';
import { RefreshContext } from './lib/api';
import { PersonaProvider } from './lib/persona';
import { ToastProvider } from './lib/toast';
import { Shell } from './shell/Shell';

// One chunk per page: the first paint carries the shell, not every table on the site.
const FeaturesPage = lazy(() => import('./pages/FeaturesPage'));
const NewFeaturePage = lazy(() => import('./pages/NewFeaturePage'));
const InboxPage = lazy(() => import('./pages/InboxPage'));
const FeaturePage = lazy(() => import('./pages/FeaturePage'));
const DraftPage = lazy(() => import('./pages/DraftPage'));
const DriftPage = lazy(() => import('./pages/DriftPage'));
const TaskPage = lazy(() => import('./pages/TaskPage'));
const RecordPage = lazy(() => import('./pages/RecordPage'));
const ReviewsPage = lazy(() => import('./pages/ReviewsPage'));
const ActivityPage = lazy(() => import('./pages/ActivityPage'));
const GlobalPage = lazy(() => import('./pages/GlobalPage'));
const BlueprintPage = lazy(() => import('./pages/BlueprintPage'));

// Routes are the real page paths. Every path here is also in app/web/spa.py's PAGE_PATHS
// (the backend serves index.html only at listed paths): a new page is a route in both.
const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: '/', element: <FeaturesPage /> },
      { path: '/new', element: <NewFeaturePage /> },
      { path: '/inbox', element: <InboxPage /> },
      { path: '/standards', element: <GlobalPage kind="standards" /> },
      { path: '/learnings', element: <GlobalPage kind="learnings" /> },
      { path: '/blueprint', element: <BlueprintPage /> },
      { path: '/features/:id', element: <FeaturePage /> },
      { path: '/features/:id/draft', element: <DraftPage /> },
      { path: '/features/:id/drift', element: <DriftPage /> },
      { path: '/features/:id/tasks/:ref', element: <TaskPage /> },
      { path: '/features/:id/records/:ref', element: <RecordPage /> },
      { path: '/features/:id/reviews', element: <ReviewsPage /> },
      { path: '/features/:id/activity', element: <ActivityPage /> },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]);

function App() {
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  const refresh = useMemo(() => ({ version, bump }), [version, bump]);
  return (
    <RefreshContext.Provider value={refresh}>
      <ToastProvider>
        <PersonaProvider>
          <RouterProvider router={router} />
        </PersonaProvider>
      </ToastProvider>
    </RefreshContext.Provider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
