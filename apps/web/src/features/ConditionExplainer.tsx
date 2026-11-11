import { lazy, Suspense, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { LENSES, LENS_EVIDENCE, type Lens } from '@/components/explainer/explainerModel';
import { cn } from '@/lib/utils';
import { may3D } from '@/lib/webgl';

const ExplainerScene = lazy(() => import('@/components/explainer/ExplainerScene'));

/**
 * "Sidewalk condition explainer" (ux-spec §3D, optional). The text panel is the content and
 * works without 3D; the scene is decorative (aria-hidden), illustrative, loaded only when
 * scrolled near and only with WebGL, without reduced motion and without Save-Data.
 */
export function ConditionExplainer() {
  const { t } = useTranslation('how');
  const [lens, setLens] = useState<Lens>('steps');
  const [show3d] = useState(may3D);
  const [load3d, setLoad3d] = useState(false);
  const [ready, setReady] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const base = useId();

  useEffect(() => {
    const el = stage.current;
    if (!show3d || !el) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e?.isIntersecting) {
          setLoad3d(true);
          io.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [show3d]);

  const onKey = (e: KeyboardEvent, i: number) => {
    const next = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: LENSES.length - 1 }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    const j = (next + LENSES.length) % LENSES.length;
    setLens(LENSES[j]!);
    tabs.current[j]?.focus();
  };

  const evidence = LENS_EVIDENCE[lens];

  return (
    <div className={cn('grid gap-6', show3d && 'md:grid-cols-[1fr_1fr]')} data-testid="condition-explainer">
      <div>
        <div role="tablist" aria-label={t('conditions.tablist')} className="flex flex-wrap gap-2">
          {LENSES.map((l, i) => (
            <button
              key={l}
              ref={(el) => {
                tabs.current[i] = el;
              }}
              type="button"
              role="tab"
              id={`${base}-tab-${l}`}
              aria-selected={lens === l}
              aria-controls={`${base}-panel`}
              tabIndex={lens === l ? 0 : -1}
              onClick={() => setLens(l)}
              onKeyDown={(e) => onKey(e, i)}
              className={cn(
                'inline-flex min-h-9 items-center rounded-full border px-3 text-sm',
                lens === l ? 'border-foreground bg-foreground text-background' : 'border-border hover:bg-muted',
              )}
            >
              {t(`conditions.lens.${l}.label`)}
            </button>
          ))}
        </div>
        <div
          role="tabpanel"
          id={`${base}-panel`}
          aria-labelledby={`${base}-tab-${lens}`}
          tabIndex={0}
          className="mt-4 rounded-lg border border-border bg-card p-4"
          data-lens={lens}
        >
          <h3 className="font-semibold">{t(`conditions.lens.${lens}.label`)}</h3>
          <dl className="mt-3 space-y-3 text-sm">
            <div>
              <dt className="font-medium">{t('conditions.source')}</dt>
              <dd className="mt-1 text-muted-foreground">{t(`conditions.lens.${lens}.source`)}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('conditions.inWinterPath')}</dt>
              <dd className="mt-1 text-muted-foreground">{t(`conditions.lens.${lens}.use`)}</dd>
            </div>
            <div>
              <dt className="font-medium">{t('conditions.shownAs')}</dt>
              <dd className="mt-1">
                {evidence ? (
                  <>
                    <EvidenceBadge state={evidence} />
                    <span className="ml-2 text-muted-foreground">{t(`conditions.lens.${lens}.evidenceNote`)}</span>
                  </>
                ) : (
                  <span className="text-muted-foreground">{t(`conditions.lens.${lens}.evidenceNote`)}</span>
                )}
              </dd>
            </div>
          </dl>
        </div>
      </div>
      {show3d && (
        <figure className="relative aspect-[4/3] overflow-hidden rounded-2xl bg-navy" data-testid="explainer-stage">
          <div ref={stage} aria-hidden="true" className={cn('absolute inset-0 transition-opacity duration-500', ready ? 'opacity-100' : 'opacity-0')}>
            {load3d && (
              <Suspense fallback={null}>
                <ExplainerScene lens={lens} onReady={() => setReady(true)} />
              </Suspense>
            )}
          </div>
          <p className="sr-only">{t('conditions.sceneDescription')}</p>
          <figcaption className="absolute bottom-2 left-2 rounded-md bg-navy/80 px-2 py-1 text-xs text-ice">{t('conditions.illustrative')}</figcaption>
        </figure>
      )}
    </div>
  );
}
