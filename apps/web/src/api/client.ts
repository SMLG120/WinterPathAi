import createClient from 'openapi-fetch';
import type { paths } from './schema';
import type { ApiError as ApiErrorBody, ErrorCode } from './types';
import { API_BASE_URL, API_TIMEOUT_MS, WAKE_BUDGET_MS } from '@/lib/env';
import { useBackendStore } from '@/stores/backend';
import { createResilientFetch, FetchFailure } from './resilientFetch';

/**
 * Thin typed client generated from docs/contracts/openapi.yaml.
 * No routing or risk logic lives in the browser — it only renders API output.
 * Requests time out and ride out a free-tier cold start (see resilientFetch.ts).
 */
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  fetch: createResilientFetch({
    timeoutMs: API_TIMEOUT_MS,
    budgetMs: WAKE_BUDGET_MS,
    onWaking: (d) => useBackendStore.getState().adjust(d),
  }),
});

/**
 * Client-side codes (never sent by the API):
 * NETWORK — no connection; TIMEOUT — no answer within VITE_API_TIMEOUT_MS;
 * WAKE_TIMEOUT — the backend stayed asleep for the whole cold-start window;
 * INCOMPLETE — a 2xx whose body was unreadable or missing required parts; UNKNOWN — anything else.
 */
export type ClientErrorCode = 'NETWORK' | 'TIMEOUT' | 'WAKE_TIMEOUT' | 'INCOMPLETE' | 'UNKNOWN';

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: ErrorCode | ClientErrorCode;
  readonly retryAfterS: number | null;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: Partial<ApiErrorBody> | undefined, retryAfter: string | null, clientCode?: ClientErrorCode) {
    super(body?.message ?? clientCode ?? `HTTP ${status}`);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = clientCode ?? (body?.code as ErrorCode | undefined) ?? (status === 0 ? 'NETWORK' : 'UNKNOWN');
    const n = retryAfter ? Number.parseInt(retryAfter, 10) : Number.NaN;
    this.retryAfterS = Number.isFinite(n) ? n : null;
    this.requestId = body?.request_id ?? null;
    this.details = (body?.details as Record<string, unknown> | undefined) ?? {};
  }
}

const FAILURE_CODE = { timeout: 'TIMEOUT', network: 'NETWORK', asleep: 'WAKE_TIMEOUT' } as const;

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/**
 * Unwraps an openapi-fetch result, throwing a typed error for non-2xx responses.
 * `complete` (optional) rejects a 2xx body that lacks what the view needs → INCOMPLETE,
 * so a partial answer is never rendered as if it were whole.
 */
export async function unwrap<T>(p: Promise<FetchResult<T>>, complete?: (d: T) => boolean): Promise<T> {
  let res: FetchResult<T>;
  try {
    res = await p;
  } catch (e) {
    if (e instanceof FetchFailure) throw new ApiRequestError(0, undefined, null, FAILURE_CODE[e.kind]);
    // openapi-fetch parses the body after a successful fetch: a SyntaxError here is a truncated/garbled body.
    if (e instanceof SyntaxError) throw new ApiRequestError(200, undefined, null, 'INCOMPLETE');
    throw new ApiRequestError(0, undefined, null, 'NETWORK');
  }
  if (res.error !== undefined || !res.response.ok) {
    const body = (typeof res.error === 'object' && res.error !== null ? res.error : undefined) as
      | Partial<ApiErrorBody>
      | undefined;
    throw new ApiRequestError(res.response.status, body, res.response.headers.get('Retry-After'));
  }
  if (complete && (res.data === undefined || !complete(res.data))) {
    throw new ApiRequestError(res.response.status, undefined, null, 'INCOMPLETE');
  }
  return res.data as T;
}

export function isApiError(e: unknown): e is ApiRequestError {
  return e instanceof ApiRequestError;
}

/** Codes that mean "we never got an answer from a live API". */
export const isUnreachable = (e: unknown) => isApiError(e) && ['NETWORK', 'TIMEOUT', 'WAKE_TIMEOUT'].includes(e.code);
