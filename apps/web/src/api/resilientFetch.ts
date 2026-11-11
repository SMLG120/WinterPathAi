/**
 * fetch wrapper for the API: per-attempt timeout (AbortController) and a bounded
 * "cold start" retry. Render Free sleeps after ~15 min idle and needs ~1 min to wake;
 * while it does, requests fail at the network level, time out, or get a 502/503/504
 * from the proxy (no WinterPath error body). Those are retried with backoff for a
 * bounded total time; anything the API itself answered is returned as is.
 *
 * Never invents a response: it either returns what the server sent or throws a FetchFailure.
 */

/** Error codes the WinterPath API emits (openapi Error.code). A 5xx carrying one is a live API answer, not a sleeping host. */
const API_ERROR_CODES = new Set([
  'VALIDATION_ERROR',
  'OUTSIDE_COVERAGE',
  'OFF_NETWORK',
  'BBOX_TOO_LARGE',
  'NO_ROUTE',
  'NOT_FOUND',
  'UNAUTHORIZED',
  'RATE_LIMITED',
  'UPSTREAM_UNAVAILABLE',
  'WRITES_DISABLED',
  'INTERNAL',
]);

/** POSTs that only read (safe to resend). Other non-GET requests are writes. */
const READ_ONLY_POST = /\/routes\/compare$/;

export type FailureKind = 'timeout' | 'network' | 'asleep';

export class FetchFailure extends Error {
  readonly kind: FailureKind;
  constructor(kind: FailureKind) {
    super(`fetch failed: ${kind}`);
    this.name = 'FetchFailure';
    this.kind = kind;
  }
}

export type ResilientOptions = {
  timeoutMs: number;
  /** Total time to keep retrying a sleeping backend (≈90 s). */
  budgetMs: number;
  /** +1 when a request starts waiting for the backend to wake, −1 when it stops. */
  onWaking?: (delta: 1 | -1) => void;
  baseFetch?: typeof fetch;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
};

/** 1 s, 2 s, 4 s, 8 s, then every 10 s. */
export const backoffMs = (attempt: number) => Math.min(10_000, 1000 * 2 ** (attempt - 1));

async function isSleepingHost(res: Response): Promise<boolean> {
  if (res.status !== 502 && res.status !== 503 && res.status !== 504) return false;
  try {
    const body = (await res.clone().json()) as { code?: unknown };
    return !(typeof body?.code === 'string' && API_ERROR_CODES.has(body.code));
  } catch {
    return true; // HTML/empty proxy page, not a WinterPath error body
  }
}

export function createResilientFetch(opts: ResilientOptions): typeof fetch {
  const baseFetch = opts.baseFetch ?? ((...a: Parameters<typeof fetch>) => globalThis.fetch(...a));
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const now = opts.now ?? (() => Date.now());

  async function attempt(req: Request): Promise<Response> {
    const ctrl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      ctrl.abort();
    }, opts.timeoutMs);
    const onCallerAbort = () => ctrl.abort();
    req.signal?.addEventListener('abort', onCallerAbort);
    try {
      return await baseFetch(new Request(req, { signal: ctrl.signal }));
    } catch (e) {
      if (req.signal?.aborted) throw e; // the caller cancelled: not ours to retry
      throw new FetchFailure(timedOut ? 'timeout' : 'network');
    } finally {
      clearTimeout(timer);
      req.signal?.removeEventListener('abort', onCallerAbort);
    }
  }

  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const original = new Request(input, init);
    const method = original.method.toUpperCase();
    const readOnly = method === 'GET' || method === 'HEAD' || (method === 'POST' && READ_ONLY_POST.test(new URL(original.url).pathname));
    const start = now();
    let waking = false;
    try {
      for (let n = 1; ; n++) {
        try {
          const res = await attempt(original.clone());
          if (!(await isSleepingHost(res))) return res;
        } catch (e) {
          if (!(e instanceof FetchFailure)) throw e;
          // A write that timed out may still reach the API once it wakes: never resend it
          // automatically (no duplicate reports). The user gets a retry button instead.
          if (!readOnly && e.kind === 'timeout') throw e;
        }
        const wait = backoffMs(n);
        if (now() - start + wait > opts.budgetMs) throw new FetchFailure('asleep');
        if (!waking) {
          waking = true;
          opts.onWaking?.(1);
        }
        await sleep(wait);
      }
    } finally {
      if (waking) opts.onWaking?.(-1);
    }
  };
}
