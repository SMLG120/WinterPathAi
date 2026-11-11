import createClient from 'openapi-fetch';
import type { paths } from './schema';
import type { ApiError as ApiErrorBody, ErrorCode } from './types';
import { API_BASE_URL } from '@/lib/env';

/**
 * Thin typed client generated from docs/contracts/openapi.yaml.
 * No routing or risk logic lives in the browser — it only renders API output.
 */
export const api = createClient<paths>({ baseUrl: API_BASE_URL });

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: ErrorCode | 'NETWORK' | 'UNKNOWN';
  readonly retryAfterS: number | null;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: Partial<ApiErrorBody> | undefined, retryAfter: string | null) {
    super(body?.message ?? `HTTP ${status}`);
    this.name = 'ApiRequestError';
    this.status = status;
    this.code = (body?.code as ErrorCode | undefined) ?? (status === 0 ? 'NETWORK' : 'UNKNOWN');
    const n = retryAfter ? Number.parseInt(retryAfter, 10) : Number.NaN;
    this.retryAfterS = Number.isFinite(n) ? n : null;
    this.requestId = body?.request_id ?? null;
    this.details = (body?.details as Record<string, unknown> | undefined) ?? {};
  }
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

/** Unwraps an openapi-fetch result, throwing a typed error for non-2xx responses. */
export async function unwrap<T>(p: Promise<FetchResult<T>>): Promise<T> {
  let res: FetchResult<T>;
  try {
    res = await p;
  } catch {
    throw new ApiRequestError(0, undefined, null);
  }
  if (res.error !== undefined || !res.response.ok) {
    const body = (typeof res.error === 'object' && res.error !== null ? res.error : undefined) as
      | Partial<ApiErrorBody>
      | undefined;
    throw new ApiRequestError(res.response.status, body, res.response.headers.get('Retry-After'));
  }
  return res.data as T;
}

export function isApiError(e: unknown): e is ApiRequestError {
  return e instanceof ApiRequestError;
}
