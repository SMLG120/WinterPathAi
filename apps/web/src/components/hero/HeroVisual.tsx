import { lazy, Suspense, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { HeroPoster } from './HeroPoster';
import { cn } from '@/lib/utils';
import { may3D } from '@/lib/webgl';
import { afterLoadAndIdle } from '@/lib/afterLoad';

const Scene3D = lazy(() => import('./Scene3D'));

/**
 * Poster first (LCP-safe). The 3D chunk loads lazily after idle, only with
 * WebGL, without reduced-motion and without Save-Data.
 */
export function HeroVisual({ className }: { className?: string }) {
  const { t } = useTranslation('landing');
  const [load3d, setLoad3d] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!may3D()) return;
    // Keep the 3D chunk (~220 KB gz, heavy parse) out of the LCP window: poster first.
    return afterLoadAndIdle(() => setLoad3d(true), 2000);
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
