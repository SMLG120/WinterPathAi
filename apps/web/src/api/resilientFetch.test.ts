// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { backoffMs, createResilientFetch, FetchFailure } from './resilientFetch';

const URL_GET = 'http://api.test/api/v1/coverage';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const proxyPage = (status: number) => new Response('<html>Service waking</html>', { status, headers: { 'Content-Type': 'text/html' } });

/** Virtual clock: sleep() advances time instantly. */
function harness(responses: (() => Promise<Response>)[], opts: { budgetMs?: number; timeoutMs?: number } = {}) {
  let t = 0;
  const calls: Request[] = [];
  const waking: number[] = [];
  const baseFetch = vi.fn(async (r: RequestInfo | URL) => {
    calls.push(r as Request);
    const next = responses.shift();
    if (!next) throw new Error('no more responses');
    return next();
  }) as unknown as typeof fetch;
  const f = createResilientFetch({
    timeoutMs: opts.timeoutMs ?? 15_000,
    budgetMs: opts.budgetMs ?? 90_000,
    baseFetch,
    now: () => t,
    sleep: async (ms) => {
      t += ms;
    },
    onWaking: (d) => waking.push(d),
  });
  return { f, calls, waking, elapsed: () => t };
}

describe('resilient API fetch', () => {
  it('passes a normal answer straight through, no retry, no waking state', async () => {
    const h = harness([async () => json(200, { ok: true })]);
    const r = await h.f(URL_GET);
    expect(r.status).toBe(200);
    expect(h.calls).toHaveLength(1);
    expect(h.waking).toEqual([]);
  });

  it('returns API errors as is — including 503 UPSTREAM_UNAVAILABLE and WRITES_DISABLED (a live API, not a sleeping host)', async () => {
    for (const code of ['UPSTREAM_UNAVAILABLE', 'WRITES_DISABLED']) {
      const h = harness([async () => json(503, { code, message: 'x' })]);
      expect((await h.f(URL_GET)).status).toBe(503);
      expect(h.calls).toHaveLength(1);
    }
  });

  it('cold start: proxy 502/503 and network errors are retried with backoff until the API answers', async () => {
    const h = harness([
      async () => proxyPage(502),
      async () => {
        throw new TypeError('Failed to fetch');
      },
      async () => proxyPage(503),
      async () => json(200, { ok: true }),
    ]);
    const r = await h.f(URL_GET);
    expect(r.status).toBe(200);
    expect(h.calls).toHaveLength(4);
    expect(h.elapsed()).toBe(backoffMs(1) + backoffMs(2) + backoffMs(3));
    expect(h.waking).toEqual([1, -1]); // one waking episode, cleared on success
  });

  it('gives up after the bounded budget (~90 s) with an "asleep" failure', async () => {
    const forever = Array.from({ length: 50 }, () => async () => proxyPage(503));
    const h = harness(forever);
    await expect(h.f(URL_GET)).rejects.toMatchObject({ kind: 'asleep' });
    expect(h.elapsed()).toBeLessThanOrEqual(90_000);
    expect(h.elapsed()).toBeGreaterThan(60_000);
    expect(h.waking).toEqual([1, -1]);
  });

  it('times out a hanging request with AbortController', async () => {
    vi.useFakeTimers();
    try {
      const hang = (r: RequestInfo | URL) =>
        new Promise<Response>((_, rej) => (r as Request).signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))));
      const f = createResilientFetch({ timeoutMs: 1000, budgetMs: 1500, baseFetch: hang as typeof fetch, sleep: async () => {} });
      const p = f(URL_GET);
      const assertion = expect(p).rejects.toBeInstanceOf(FetchFailure);
      await vi.advanceTimersByTimeAsync(1000);
      await vi.advanceTimersByTimeAsync(1000);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  it('never resends a write that timed out (it may still land once the API wakes: no duplicate reports)', async () => {
    vi.useFakeTimers();
    try {
      let calls = 0;
      const hang = ((r: RequestInfo | URL) => {
        calls++;
        return new Promise<Response>((_, rej) => (r as Request).signal.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))));
      }) as typeof fetch;
      const f = createResilientFetch({ timeoutMs: 1000, budgetMs: 90_000, baseFetch: hang, sleep: async () => {} });
      const p = f('http://api.test/api/v1/reports', { method: 'POST', body: '{}' });
      const assertion = expect(p).rejects.toMatchObject({ kind: 'timeout' });
      await vi.advanceTimersByTimeAsync(1000);
      await assertion;
      expect(calls).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it('a write rejected by a sleeping proxy (502, never forwarded) is retried', async () => {
    const h = harness([async () => proxyPage(502), async () => json(201, { id: 'r1' })]);
    const r = await h.f('http://api.test/api/v1/reports', { method: 'POST', body: '{}' });
    expect(r.status).toBe(201);
    expect(h.calls).toHaveLength(2);
  });

  it('a caller abort is passed through, not retried', async () => {
    const ctrl = new AbortController();
    const h = harness([
      async () => {
        ctrl.abort();
        throw new DOMException('aborted', 'AbortError');
      },
    ]);
    await expect(h.f(URL_GET, { signal: ctrl.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(h.calls).toHaveLength(1);
  });

  it('a POST /routes/compare (read-only) is resent across a cold start, with its body intact', async () => {
    const h = harness([async () => proxyPage(502), async () => json(200, { routes: [] })]);
    const r = await h.f('http://api.test/api/v1/routes/compare', { method: 'POST', body: '{"a":1}', headers: { 'Content-Type': 'application/json' } });
    expect(r.status).toBe(200);
    expect(await h.calls[1]!.text()).toBe('{"a":1}');
  });
});
