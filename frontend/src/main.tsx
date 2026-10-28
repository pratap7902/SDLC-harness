import React, { lazy, useCallback, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import './index.css';
import { RefreshContext } from './lib/api';
import { PersonaProvider, usePersona } from './lib/persona';
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

/** `/inbox` → the inbox of whoever the UI is viewing as. */
function MyInbox() {
  const { persona } = usePersona();
  return persona ? <Navigate to={`/inbox/${persona}`} replace /> : null;
}

// Routes are the real page paths. Every path here is also in app/web/spa.py's PAGE_PATHS
// (the backend serves index.html only at listed paths): a new page is a route in both.
const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: '/', element: <FeaturesPage /> },
      { path: '/new', element: <NewFeaturePage /> },
      { path: '/inbox', element: <MyInbox /> },
      { path: '/inbox/:person', element: <InboxPage /> },
      { path: '/standards', element: <GlobalPage kind="standards" /> },
      { path: '/learnings', element: <GlobalPage kind="learnings" /> },
      { path: '/blueprint', element: <BlueprintPage /> },
      { path: '/i/:slug', element: <FeaturePage /> },
      { path: '/i/:slug/draft', element: <DraftPage /> },
      { path: '/i/:slug/drift', element: <DriftPage /> },
      { path: '/i/:slug/t/:ref', element: <TaskPage /> },
      { path: '/i/:slug/r/:ref', element: <RecordPage /> },
      { path: '/i/:slug/reviews', element: <ReviewsPage /> },
      { path: '/i/:slug/activity', element: <ActivityPage /> },
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
