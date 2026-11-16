import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RotateCcw, Search, X } from 'lucide-react';
import { EvidenceBadge } from '@/components/evidence/EvidenceBadge';
import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/input';
import { getCoverage } from '@/lib/coverage';
import { cn } from '@/lib/utils';
import { usePlannerStore, type EndpointLabel, type PointKey } from '@/stores/planner';
import type { SearchResult } from './types';
import { useSearch, useSearchProvider } from './useSearch';

function toLabel(r: SearchResult): EndpointLabel {
  return {
    text: r.label,
    detail: r.detail,
    kind: r.kind === 'street' ? 'place' : r.kind,
    source: r.source,
    quality: r.quality,
    evidence: r.evidence,
  };
}

/** Secondary line of an option / endpoint: source, position quality, notes. */
export function ResultMeta({ r, civic }: { r: Pick<SearchResult, 'source' | 'quality' | 'kind' | 'note' | 'evidence'>; civic?: string }) {
  const { t } = useTranslation('plan');
  const parts: string[] = [t(`search.source.${r.source}`)];
  if (r.source === 'rqa' && r.kind === 'address' && r.quality) parts.push(`${t('search.quality.label')}: ${t(`search.quality.${r.quality}`)}`);
  if (r.source === 'osm') parts.push(t('search.placePoint'));
  if (r.note === 'lat_lon' || r.note === 'lon_lat') parts.push(t(`search.order.${r.note}`));
  if (r.note === 'outside_area') parts.push(t('search.outsideArea'));
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <span>{parts.join(' · ')}</span>
      {r.note === 'nearest_civic' && <span className="font-medium text-foreground">{t('search.nearestCivic', { civic })}</span>}
      {r.evidence && <EvidenceBadge state={r.evidence} />}
    </span>
  );
}

/**
 * Place search (ARIA 1.2 combobox with a listbox popup): addresses (RQA) and named places (OSM)
 * from the self-hosted static index, plus typed coordinates. A chosen result fills the start or
 * the destination; the existing map markers follow the planner store.
 */
export function SearchBox() {
  const { t } = useTranslation('plan');
  const id = useId();
  const listId = `${id}-list`;
  const optId = (i: number) => `${id}-opt-${i}`;
  const provider = useSearchProvider();
  const origin = usePlannerStore((s) => s.origin);
  const destination = usePlannerStore((s) => s.destination);
  const setPoint = usePlannerStore((s) => s.setPoint);
  const [target, setTarget] = useState<PointKey>(origin && !destination ? 'destination' : 'origin');
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [announce, setAnnounce] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const box = getCoverage().box;
  const { state, pending, retry } = useSearch(text, provider, { lon: (box.west + box.east) / 2, lat: (box.south + box.north) / 2 });

  const results = state.phase === 'done' ? state.outcome.results : [];
  const listOpen = open && results.length > 0 && !pending;
  useEffect(() => setActive(-1), [state]);
  const civic = /^\s*(\d+)/.exec(state.phase === 'done' ? state.query : '')?.[1];
  const ambiguous = results.some((r) => r.note === 'lat_lon' || r.note === 'lon_lat');

  const choose = (r: SearchResult) => {
    if (r.kind === 'street' || !r.point) {
      const completion = r.completion ?? r.label;
      setText(completion);
      setOpen(true);
      setAnnounce(t('search.completed'));
      requestAnimationFrame(() => inputRef.current?.setSelectionRange(0, 0));
      return;
    }
    setPoint(target, r.point, toLabel(r));
    setText(r.label);
    setOpen(false);
    setAnnounce(t('search.selected', { point: t(`points.${target}`), label: r.label }));
    if (target === 'origin' && !destination) setTarget('destination');
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const n = results.length;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!listOpen) {
        setOpen(true);
        if (n) setActive(0);
      } else setActive((a) => (a + 1) % n);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (!listOpen) {
        setOpen(true);
        if (n) setActive(n - 1);
      } else setActive((a) => (a <= 0 ? n - 1 : a - 1));
    } else if (e.key === 'Enter') {
      if (listOpen && active >= 0 && results[active]) {
        e.preventDefault();
        choose(results[active]!);
      }
    } else if (e.key === 'Escape') {
      if (listOpen) {
        e.preventDefault();
        setOpen(false);
        setActive(-1);
      } else if (text) {
        e.preventDefault();
        setText('');
      }
    }
  };

  let status: React.ReactNode = null;
  let statusKind: 'busy' | 'info' | 'error' | 'count' = 'info';
  if (pending || state.phase === 'loading') {
    statusKind = 'busy';
    status = t('search.searching');
  } else if (state.phase === 'error') {
    statusKind = 'error';
    status = state.unavailable ? t('search.unavailable') : t('search.error');
  } else if (state.phase === 'done') {
    const { status: st } = state.outcome;
    if (st === 'too_short') status = t('search.typeMore');
    else if (st === 'coords_out_of_range') status = t('search.coordsOutOfRange');
    else if (results.length === 0) status = t('search.empty', { query: state.query });
    else {
      statusKind = 'count';
      status = (
        <>
          {ambiguous && <span className="not-sr-only block">{t('search.order.ambiguous')}</span>}
          <span className="sr-only">{t('search.results', { count: results.length })}</span>
        </>
      );
    }
  }

  return (
    <div className="space-y-2" data-testid="place-search">
      <Label htmlFor={`${id}-input`} className="flex items-center gap-1.5">
        <Search className="size-4" aria-hidden="true" />
        {t('search.label')}
      </Label>
      <fieldset className="flex flex-wrap items-center gap-3 text-sm" aria-describedby={`${id}-fill-hint`}>
        <legend className="float-left mr-1 text-xs font-medium text-muted-foreground">{t('search.fill')}</legend>
        <span id={`${id}-fill-hint`} className="sr-only">
          {t('search.fillHint')}
        </span>
        {(['origin', 'destination'] as const).map((k) => (
          <label key={k} className="inline-flex min-h-8 cursor-pointer items-center gap-1.5">
            <input
              type="radio"
              name={`${id}-target`}
              value={k}
              checked={target === k}
              onChange={() => setTarget(k)}
              className="size-4 accent-[var(--primary)]"
              data-testid={`search-fill-${k}`}
            />
            <span
              aria-hidden="true"
              className={`inline-flex size-5 items-center justify-center rounded-full text-xs text-white ${k === 'origin' ? 'bg-teal' : 'bg-navy dark:bg-slate-brand'}`}
            >
              {k === 'origin' ? 'A' : 'B'}
            </span>
            {t(`points.${k}`)}
          </label>
        ))}
      </fieldset>
      <div className="relative">
        <Input
          ref={inputRef}
          id={`${id}-input`}
          role="combobox"
          aria-expanded={listOpen}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={listOpen && active >= 0 ? optId(active) : undefined}
          aria-describedby={`${id}-help ${id}-status`}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          enterKeyHint="search"
          placeholder={t('search.placeholder')}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          className="pr-10"
          data-testid="search-input"
        />
        <span className="absolute inset-y-0 right-1 flex items-center">
          {pending || state.phase === 'loading' ? (
            <Loader2 className="mr-2 size-4 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden="true" />
          ) : text ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 px-2"
              onClick={() => {
                setText('');
                inputRef.current?.focus();
              }}
              data-testid="search-clear"
            >
              <X aria-hidden="true" />
              <span className="sr-only">{t('points.clear')}</span>
            </Button>
          ) : null}
        </span>
        <ul
          id={listId}
          role="listbox"
          aria-label={t('search.label')}
          hidden={!listOpen}
          className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-md border border-border bg-card p-1 shadow-lg"
          data-testid="search-results"
        >
          {listOpen &&
            results.map((r, i) => (
              // Keyboard selection is on the combobox input (aria-activedescendant + Enter), per the ARIA combobox pattern.
              // eslint-disable-next-line jsx-a11y/click-events-have-key-events
              <li
                key={r.id}
                id={optId(i)}
                role="option"
                aria-selected={i === active}
                className={cn('cursor-pointer rounded px-2 py-1.5 text-sm', i === active ? 'bg-muted outline-2 outline-ring' : 'hover:bg-muted')}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(r)}
                onMouseMove={() => active !== i && setActive(i)}
                data-testid="search-option"
                data-kind={r.kind}
                data-source={r.source}
              >
                <span className="block font-medium">{r.label}</span>
                <span className="block text-xs">
                  {t(`search.kind.${r.kind}`)}
                  {r.detail ? ` · ${r.detail}` : ''}
                </span>
                {r.kind !== 'street' && <ResultMeta r={r} civic={civic} />}
              </li>
            ))}
        </ul>
      </div>
      <div id={`${id}-status`} aria-live="polite" className="min-h-0 text-sm" data-testid="search-status" data-state={state.phase === 'done' ? state.outcome.status : state.phase}>
        {status && (
          <p className={cn('flex items-center gap-2', statusKind === 'error' ? 'text-danger' : statusKind === 'count' ? '' : 'text-muted-foreground')}>{status}</p>
        )}
        <span className="sr-only">{announce}</span>
      </div>
      {state.phase === 'error' && (
        <Button type="button" variant="outline" size="sm" onClick={retry} data-testid="search-retry">
          <RotateCcw aria-hidden="true" />
          {t('search.retry')}
        </Button>
      )}
      <p id={`${id}-help`} className="text-xs text-muted-foreground">
        {t('search.help')}
      </p>
      <p className="text-xs text-muted-foreground" data-testid="search-attribution">
        {t('search.attribution')}
      </p>
    </div>
  );
}
