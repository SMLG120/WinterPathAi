import { lazy, Suspense, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { HeroPoster } from './HeroPoster';
import { cn } from '@/lib/utils';
import { canUseWebGL } from '@/lib/webgl';

const Scene3D = lazy(() => import('./Scene3D'));

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
}

function saveData(): boolean {
  const c = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  return !!c?.saveData;
}

/**
 * Poster first (LCP-safe). The 3D chunk loads lazily after idle, only with
 * WebGL, without reduced-motion and without Save-Data.
 */
export function HeroVisual({ className }: { className?: string }) {
  const { t } = useTranslation('landing');
  const [load3d, setLoad3d] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (prefersReducedMotion() || saveData() || !canUseWebGL()) return;
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number };
    const start = () => setLoad3d(true);
    if (w.requestIdleCallback) {
      const id = w.requestIdleCallback(start, { timeout: 2500 });
      return () => (window as Window & { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback?.(id);
    }
    const id = window.setTimeout(start, 1200);
    return () => window.clearTimeout(id);
  }, []);

  return (
    <figure className={cn('relative overflow-hidden rounded-2xl bg-navy', className)} data-testid="hero-visual">
      <div aria-hidden="true" className="absolute inset-0">
        <HeroPoster className={cn('h-full w-full transition-opacity duration-700', ready && 'opacity-0')} />
        {load3d && (
          <Suspense fallback={null}>
            <div className={cn('absolute inset-0 transition-opacity duration-700', ready ? 'opacity-100' : 'opacity-0')}>
              <Scene3D onReady={() => setReady(true)} />
            </div>
          </Suspense>
        )}
      </div>
      <p className="sr-only">{t('scene.description')}</p>
      <figcaption className="absolute bottom-2 left-2 rounded-md bg-navy/80 px-2 py-1 text-xs text-ice">
        {t('scene.illustrative')}
      </figcaption>
    </figure>
  );
}
