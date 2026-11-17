import { parseCoordinates } from './coords';
import { fold, shardKey, tokens } from './normalize';
import type { LonLat } from '@/api/types';
import { parseQuery, type ParsedQuery } from './query';
import {
  evidenceForQuality,
  qualityFromRqa,
  SearchUnavailableError,
  type SearchOutcome,
  type SearchProvider,
  type SearchResult,
  type SourceInfo,
} from './types';

export const FORMAT = 'winterpath-search/1';

export type Manifest = {
  format: string;
  build_id: string;
  base: string;
  key_len: number;
  address_buckets: number;
  municipalities: [code: string, name: string][];
  qualities: string[];
  sources: SourceInfo[];
  counts: Record<string, unknown>;
  shards: Record<string, string>;
};

// Shard rows (see services/ingestion/src/winterpath_ingestion/search_index/build.py).
type StreetRow = ['s', sid: number, display: string, muni: number, tokens: string, generic: string, dir: string, count: number, lonE5: number, latE5: number];
type PlaceRow = ['p', pid: number, name: string, muni: number, tokens: string, kind: string, lonE5: number, latE5: number, ref: string, primary: string];
type TokenShard = { v: 1; e: (StreetRow | PlaceRow)[] };
type AddressRow = [civic: string, dLon: number, dLat: number, quality: number];
type AddressShard = { v: 1; s: Record<string, AddressRow[]> };

const KIND_BONUS: Record<string, number> = {
  station: 1.5,
  university: 1.5,
  hospital: 1.5,
  airport: 1.5,
  museum: 1,
  park: 1,
  venue: 1,
  mall: 1,
  attraction: 1,
  government: 0.5,
  library: 0.5,
};
const DEFAULT_LIMIT = 8;
const STREETS_FOR_CIVIC = 5;
const MAX_CACHED_SHARDS = 48;

type Scored<T> = { row: T; score: number };

function hex(buf: ArrayBuffer): string {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Self-hosted static index (same origin, no third-party geocoder). Loads the manifest once, then
 * only the token shard for the query and, for a civic number, the address buckets of the best
 * streets. Nothing about the query leaves the site except which shard files are requested.
 */
export class StaticIndexProvider implements SearchProvider {
  readonly id = 'static-index';
  private manifestP: Promise<Manifest> | null = null;
  private cache = new Map<string, Promise<unknown>>();

  constructor(
    private readonly baseUrl = `${import.meta.env.BASE_URL ?? '/'}search/`,
    private readonly fetchImpl: typeof fetch = (...a) => fetch(...a),
  ) {}

  private async getJson(path: string, signal: AbortSignal | undefined, sha256?: string, revalidate = false): Promise<unknown> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.baseUrl + path, { signal, credentials: 'same-origin', ...(revalidate ? { cache: 'no-cache' as const } : {}) });
    } catch (e) {
      if ((e as Error)?.name === 'AbortError') throw e;
      throw new SearchUnavailableError(`search index unreachable: ${path}`, 'network');
    }
    // A missing file on Cloudflare Pages falls back to index.html (200, text/html): treat as missing.
    const type = res.headers.get('content-type') ?? '';
    if (!res.ok || !type.includes('json')) throw new SearchUnavailableError(`search index file missing: ${path}`, 'missing');
    const buf = await res.arrayBuffer();
    if (sha256 && globalThis.crypto?.subtle) {
      const got = hex(await globalThis.crypto.subtle.digest('SHA-256', buf));
      if (got !== sha256) throw new SearchUnavailableError(`search index file does not match its manifest hash: ${path}`, 'integrity');
    }
    try {
      return JSON.parse(new TextDecoder().decode(buf));
    } catch {
      throw new SearchUnavailableError(`search index file is not JSON: ${path}`, 'format');
    }
  }

  manifest(): Promise<Manifest> {
    if (!this.manifestP) {
      // Revalidated: after an index redeploy the old build directory is deleted (build.py), so a
      // stale manifest points at shards that no longer exist.
      this.manifestP = (this.getJson('manifest.json', undefined, undefined, true) as Promise<Manifest>).then((m) => {
        if (m?.format !== FORMAT || typeof m.base !== 'string' || !m.shards) throw new SearchUnavailableError('unsupported search index format', 'format');
        return m;
      });
      // A failed load is not cached: "Retry" tries again.
      this.manifestP.catch(() => (this.manifestP = null));
    }
    return this.manifestP;
  }

  private shard<T>(m: Manifest, rel: string, signal?: AbortSignal): Promise<T> {
    const hit = this.cache.get(rel);
    if (hit) {
      this.cache.delete(rel);
      this.cache.set(rel, hit); // LRU refresh
      return hit as Promise<T>;
    }
    // Not tied to one query's AbortSignal: a shard is shared by later keystrokes.
    void signal;
    const p = this.getJson(m.base + rel, undefined, m.shards[rel]);
    this.cache.set(rel, p);
    p.catch(() => this.cache.delete(rel));
    while (this.cache.size > MAX_CACHED_SHARDS) this.cache.delete(this.cache.keys().next().value!);
    return p as Promise<T>;
  }

  async sources(): Promise<SourceInfo[]> {
    return (await this.manifest()).sources;
  }

  async search(query: string, opts: { signal?: AbortSignal; limit?: number; near?: LonLat } = {}): Promise<SearchOutcome> {
    const m = this.manifestP;
    try {
      return await this.searchOnce(query, opts);
    } catch (e) {
      // A shard the loaded manifest names is gone: the index was redeployed while this tab was
      // open. Drop the manifest and shard cache and try once with the current manifest.
      if (!(e instanceof SearchUnavailableError) || e.reason !== 'missing' || m === null || this.manifestP !== m) throw e;
      this.manifestP = null;
      this.cache.clear();
      return this.searchOnce(query, opts);
    }
  }

  private async searchOnce(query: string, opts: { signal?: AbortSignal; limit?: number; near?: LonLat }): Promise<SearchOutcome> {
    const limit = opts.limit ?? DEFAULT_LIMIT;
    const q = query.trim();
    if (!q) return { status: 'ok', results: [] };

    const c = parseCoordinates(q);
    if (c.kind === 'out_of_range') return { status: 'coords_out_of_range', results: [] };
    if (c.kind === 'coords') {
      return {
        status: 'ok',
        results: c.candidates.map((p) => ({
          id: `coord:${p.order}:${p.lat},${p.lon}`,
          kind: 'coordinates',
          label: `${p.lat.toFixed(6)}, ${p.lon.toFixed(6)}`,
          detail: '',
          point: { lon: p.lon, lat: p.lat },
          source: 'typed',
          evidence: null,
          note: c.ambiguous ? p.order : p.inArea ? undefined : 'outside_area',
        })),
      };
    }

    const m = await this.manifest();
    const muniFolded = m.municipalities.map(([, name]) => tokens(name).join(' '));
    const known = new Set(muniFolded);
    const pq = parseQuery(q, (s) => known.has(s));
    const keyTok = pq.required.find((t) => t.length >= m.key_len || `s/${t}.json` in m.shards);
    if (!keyTok) return { status: 'too_short', results: [] };
    const rel = `s/${shardKey(keyTok)}.json`;
    if (!(rel in m.shards)) return { status: 'ok', results: [] };
    const shard = await this.shard<TokenShard>(m, rel, opts.signal);
    opts.signal?.throwIfAborted();

    const streets: Scored<StreetRow>[] = [];
    const places = new Map<number, Scored<PlaceRow>>();
    for (const row of shard.e) {
      const score = scoreRow(row, pq, muniFolded, opts.near);
      if (score === null) continue;
      if (row[0] === 's') streets.push({ row, score });
      else if (!pq.civic) {
        const prev = places.get(row[1]);
        if (!prev || prev.score < score) places.set(row[1], { row, score });
      }
    }
    const byScore = (a: Scored<StreetRow | PlaceRow>, b: Scored<StreetRow | PlaceRow>) =>
      b.score - a.score || a.row[2].localeCompare(b.row[2]) || a.row[1] - b.row[1];
    streets.sort(byScore);
    const muniName = (i: number) => m.municipalities[i]?.[1] ?? '';

    if (pq.civic) {
      const results = await this.civicResults(m, streets.slice(0, STREETS_FOR_CIVIC), pq.civic, muniName, opts.signal);
      return { status: 'ok', results: results.slice(0, limit) };
    }

    const placeRows = [...places.values()].sort(byScore);
    const merged: Scored<StreetRow | PlaceRow>[] = [...placeRows, ...streets];
    merged.sort(byScore);
    const results: SearchResult[] = merged.slice(0, limit).map(({ row }) => {
      if (row[0] === 'p') {
        const [, pid, name, muni, , kind, lon, lat, ref, primary] = row;
        return {
          id: `osm:${pid}:${name}`,
          kind: 'place',
          label: name,
          detail: primary ? `${primary} · ${muniName(muni)}` : muniName(muni),
          point: { lon: lon / 1e5, lat: lat / 1e5 },
          source: 'osm',
          placeKind: kind,
          // OSM is community-mapped: unverified, like every OSM attribute in this app.
          evidence: 'unverified_report',
          ref,
        };
      }
      const [, sid, display, muni] = row;
      return {
        id: `street:${sid}`,
        kind: 'street',
        label: display,
        detail: muniName(muni),
        point: null,
        source: 'rqa',
        evidence: null,
        completion: `${display}, ${muniName(muni)}`,
      };
    });
    return { status: 'ok', results };
  }

  private async civicResults(
    m: Manifest,
    streets: Scored<StreetRow>[],
    civic: string,
    muniName: (i: number) => string,
    signal?: AbortSignal,
  ): Promise<SearchResult[]> {
    if (!streets.length) return [];
    const top = streets[0]!.score;
    const picked = streets.filter((s) => s.score >= top - 3);
    const buckets = await Promise.all(picked.map((s) => this.shard<AddressShard>(m, `a/${s.row[1] % m.address_buckets}.json`, signal)));
    signal?.throwIfAborted();
    const exact: SearchResult[] = [];
    const nearest: { r: SearchResult; d: number }[] = [];
    const want = Number.parseInt(civic, 10);
    picked.forEach(({ row }, i) => {
      const [, sid, display, muni] = row;
      const list = buckets[i]!.s[String(sid)] ?? [];
      let lon = 0;
      let lat = 0;
      const decoded = list.map(([c, dl, dt, q]) => {
        lon += dl;
        lat += dt;
        return { c, lon, lat, q };
      });
      const make = (a: (typeof decoded)[number], note?: SearchResult['note']): SearchResult => {
        const quality = qualityFromRqa(m.qualities[a.q]);
        return {
          id: `rqa:${sid}:${a.c}`,
          kind: 'address',
          label: `${a.c} ${display}`,
          detail: muniName(muni),
          point: { lon: a.lon / 1e5, lat: a.lat / 1e5 },
          source: 'rqa',
          quality,
          evidence: evidenceForQuality(quality),
          note,
        };
      };
      const key = (s: string) => s.toLowerCase().replace(/\s+/g, '');
      const hits = decoded.filter((a) => key(a.c) === civic);
      const variants = /^\d+$/.test(civic) ? decoded.filter((a) => key(a.c) !== civic && key(a.c).startsWith(civic) && !/^\d/.test(key(a.c).slice(civic.length))) : [];
      for (const a of [...hits, ...variants]) exact.push(make(a));
      if (!hits.length && !variants.length && decoded.length) {
        let best = decoded[0]!;
        for (const a of decoded) if (Math.abs(Number.parseInt(a.c, 10) - want) < Math.abs(Number.parseInt(best.c, 10) - want)) best = a;
        nearest.push({ r: make(best, 'nearest_civic'), d: Math.abs(Number.parseInt(best.c, 10) - want) });
      }
    });
    if (exact.length) return exact;
    // The typed number is not listed: offer the closest listed numbers, clearly labelled.
    return nearest.sort((a, b) => a.d - b.d).slice(0, 3).map((n) => n.r);
  }
}

/** Score a shard row for a parsed query; null when it does not match. */
export function scoreRow(row: StreetRow | PlaceRow, pq: ParsedQuery, muniFolded: string[], near?: LonLat): number | null {
  const toks = row[4] ? row[4].split(' ') : [];
  let score = 0;
  const used = new Set<number>();
  for (const q of pq.required) {
    let best = -1;
    let bestPts = 0;
    toks.forEach((t, i) => {
      if (used.has(i)) return;
      const pts = t === q ? 3 : t.startsWith(q) ? 1 : 0;
      if (pts > bestPts) {
        bestPts = pts;
        best = i;
      }
    });
    if (best < 0) return null;
    used.add(best);
    score += bestPts + (best === 0 ? 0.5 : 0);
  }
  score -= 0.3 * (toks.length - used.size);

  if (pq.locality) {
    const muni = muniFolded[row[3]] ?? '';
    if (!(muni === pq.locality || muni.startsWith(`${pq.locality}`))) return null;
    score += 2;
  }
  if (row[0] === 's') {
    const [, , , , , generic, dir, count] = row;
    if (pq.generics.length) score += pq.generics.includes(generic) ? 2 : -1;
    if (pq.direction) score += dir === pq.direction ? 2 : dir ? -2 : 0;
    score += Math.min(1.5, Math.log10(count + 1) / 2);
  } else {
    // Street-type words in a place name ("Parc La Fontaine", "Place des Arts") count as a bonus.
    for (const g of pq.generics) if (toks.some((t) => fold(t) === g)) score += 1;
    score += KIND_BONUS[row[5]] ?? 0;
  }
  if (near) {
    // Proximity tie-breaker (at most -0.5, reached 40 km away): never outweighs a name match.
    const [lonE5, latE5] = row[0] === 's' ? [row[8], row[9]] : [row[6], row[7]];
    const dx = (lonE5 / 1e5 - near.lon) * 78.7; // km per degree of longitude at 45° N
    const dy = (latE5 / 1e5 - near.lat) * 111.2;
    score -= Math.min(0.5, Math.hypot(dx, dy) / 80);
  }
  return score;
}
