import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useSegments } from './queries';

// An absolute base URL: the test stubs fetch, and jsdom's Request rejects relative URLs.
vi.mock('@/lib/env', async (orig) => ({ ...(await orig<typeof import('@/lib/env')>()), API_BASE_URL: 'http://api.test/api/v1' }));

afterEach(() => vi.unstubAllGlobals());

describe('viewport overlays', () => {
  it('abort the request for an area the map has left, and dedupe identical areas', async () => {
    const seen: { url: string; signal: AbortSignal }[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (req: Request) =>
          new Promise<Response>((_, reject) => {
            seen.push({ url: req.url, signal: req.signal });
            req.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
          }),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
    const a = '-73.57812,45.50195,-73.56250,45.50977';
    const b = '-73.56250,45.50195,-73.54688,45.50977';
    const first = renderHook(({ bbox }) => useSegments(bbox), { wrapper, initialProps: { bbox: a } });
    renderHook(() => useSegments(a), { wrapper }); // a second observer of the same area
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(first.result.current.freshness.state).toBe('loading');
    first.rerender({ bbox: b });
    await waitFor(() => expect(seen).toHaveLength(2));
    // area a still has the second observer: not aborted
    expect(seen[0]!.signal.aborted).toBe(false);
    expect(decodeURIComponent(seen[1]!.url)).toContain(b);
    first.unmount();
    await waitFor(() => expect(seen[1]!.signal.aborted).toBe(true));
  });
});
