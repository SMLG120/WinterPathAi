import { lazy } from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LazyMotion, MotionConfig } from 'motion/react';
// Section fade-ins are progressive enhancement: animation features arrive in their own
// chunk (Motion's async LazyMotion pattern); see lib/motionReady.ts.
import { loadMotionFeatures } from '@/lib/motionReady';
import { Layout } from '@/components/layout/Layout';
import { detectLang } from '@/i18n';
import { isApiError } from '@/api/client';

const Landing = lazy(() => import('@/pages/Landing'));
const Plan = lazy(() => import('@/pages/Plan'));
const Winter = lazy(() => import('@/pages/Winter'));
const Reports = lazy(() => import('@/pages/Reports'));
const HowItWorks = lazy(() => import('@/pages/HowItWorks'));
const Pilot = lazy(() => import('@/pages/Pilot'));
const Admin = lazy(() => import('@/pages/Admin'));
const NotFound = lazy(() => import('@/pages/NotFound'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Cold starts, timeouts and network failures are already retried (bounded) in the fetch layer:
      // only a live API's unexpected 5xx gets one more try here.
      retry: (n, e) => n < 1 && isApiError(e) && e.status >= 500 && (e.code === 'INTERNAL' || e.code === 'UNKNOWN'),
      refetchOnWindowFocus: false,
    },
  },
});

const routes = [
  { path: '/', element: <Navigate to={`/${detectLang()}`} replace /> },
  { path: '/:lang/plan', element: <Layout fullBleed />, children: [{ index: true, element: <Plan /> }] },
  {
    path: '/:lang',
    element: <Layout />,
    children: [
      { index: true, element: <Landing /> },
      { path: 'winter', element: <Winter /> },
      { path: 'reports', element: <Reports /> },
      { path: 'how-it-works', element: <HowItWorks /> },
      { path: 'pilot', element: <Pilot /> },
      { path: 'admin', element: <Admin /> },
      { path: '*', element: <NotFound /> },
    ],
  },
];

const router = createBrowserRouter(routes);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">
        <LazyMotion features={loadMotionFeatures} strict>
          <RouterProvider router={router} />
        </LazyMotion>
      </MotionConfig>
    </QueryClientProvider>
  );
}
