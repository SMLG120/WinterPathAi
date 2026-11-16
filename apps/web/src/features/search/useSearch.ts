import { createContext, useContext, useEffect, useState } from 'react';
import type { LonLat } from '@/api/types';
import { useDebounced } from '@/lib/useDebounced';
import { StaticIndexProvider } from './staticProvider';
import { SearchUnavailableError, type SearchOutcome, type SearchProvider } from './types';

export const SEARCH_DEBOUNCE_MS = 300;

let defaultProvider: SearchProvider | null = null;
/** The app-wide provider (lazy, so tests and SSR-less builds don't construct it eagerly). */
export function getDefaultProvider(): SearchProvider {
  defaultProvider ??= new StaticIndexProvider();
  return defaultProvider;
}

/** Inject another provider (tests, or a future backend geocoder). */
export const SearchProviderContext = createContext<SearchProvider | null>(null);
export const useSearchProvider = () => useContext(SearchProviderContext) ?? getDefaultProvider();

export type SearchState =
  | { phase: 'idle' }
  | { phase: 'loading'; query: string }
  | { phase: 'done'; query: string; outcome: SearchOutcome }
  | { phase: 'error'; query: string; unavailable: boolean };

/** Debounced (300 ms), abortable search. `pending` is true while the user is still typing. */
export function useSearch(query: string, provider: SearchProvider, near?: LonLat) {
  const debounced = useDebounced(query.trim(), SEARCH_DEBOUNCE_MS);
  const [nonce, setNonce] = useState(0);
  const [state, setState] = useState<SearchState>({ phase: 'idle' });

  useEffect(() => {
    if (!debounced) {
      setState({ phase: 'idle' });
      return;
    }
    const ac = new AbortController();
    setState({ phase: 'loading', query: debounced });
    provider
      .search(debounced, { signal: ac.signal, near })
      .then((outcome) => {
        if (!ac.signal.aborted) setState({ phase: 'done', query: debounced, outcome });
      })
      .catch((e: unknown) => {
        if (ac.signal.aborted) return;
        setState({ phase: 'error', query: debounced, unavailable: e instanceof SearchUnavailableError && e.reason !== 'network' });
      });
    return () => ac.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `near` is a tie-breaker only: no re-query when it moves
  }, [debounced, nonce, provider]);

  const pending = query.trim() !== '' && query.trim() !== debounced;
  return { state, pending, retry: () => setNonce((n) => n + 1) };
}
