import type { LonLat } from '@/api/types';

/** Greater Montréal search area (same box as the index builder's OSM filter). */
export const SEARCH_AREA = { west: -74.02, south: 45.38, east: -73.3, north: 45.84 } as const;

export function inSearchArea(p: LonLat): boolean {
  return p.lon >= SEARCH_AREA.west && p.lon <= SEARCH_AREA.east && p.lat >= SEARCH_AREA.south && p.lat <= SEARCH_AREA.north;
}

export type CoordOrder = 'lat_lon' | 'lon_lat';
export type CoordCandidate = LonLat & { order: CoordOrder; inArea: boolean };
export type CoordParse =
  | { kind: 'none' }
  | { kind: 'out_of_range' }
  /** One reading, or several when the order cannot be decided (each is offered, labelled). */
  | { kind: 'coords'; candidates: CoordCandidate[]; ambiguous: boolean };

// A number with '.' or ',' decimals, optional degree sign and hemisphere letter.
const NUM = String.raw`([+-]?\d{1,3}(?:[.,]\d+)?)\s*°?\s*([NSEWO])?`;
const NUM_DOT = String.raw`([+-]?\d{1,3}(?:\.\d+)?)\s*°?\s*([NSEWO])?`;
const PATTERNS = [
  new RegExp(String.raw`^${NUM}\s*;\s*${NUM}$`, 'i'), // 45,50 ; -73,57
  new RegExp(String.raw`^${NUM_DOT}\s*,\s*${NUM_DOT}$`, 'i'), // 45.50, -73.57
  new RegExp(String.raw`^${NUM}\s+${NUM}$`, 'i'), // 45.50 -73.57 / 45,50 -73,57
];

// An integer written straight against an 'e' ("3e", "12E") is a French ordinal street ("3e Avenue"),
// not "3° East": the input stays an address query. "3 E", "3°E" and "3.0E" are still longitudes.
const ORDINAL = /(?:^|[\s;,])\d{1,3}e(?=$|[\s;,])/i;

type Part = { v: number; hemi: 'N' | 'S' | 'E' | 'W' | null; decimals: boolean };

function part(num: string, hemi: string | undefined): Part {
  const h = hemi?.toUpperCase();
  const hemiN = h === 'O' ? 'W' : ((h as Part['hemi']) ?? null);
  let v = Number.parseFloat(num.replace(',', '.'));
  if ((hemiN === 'S' || hemiN === 'W') && v > 0) v = -v;
  return { v, hemi: hemiN, decimals: /[.,]/.test(num) };
}

const validLat = (v: number) => Number.isFinite(v) && Math.abs(v) <= 90;
const validLon = (v: number) => Number.isFinite(v) && Math.abs(v) <= 180;

/**
 * Parse typed coordinates. Accepts "45.50, -73.57", "45.50 -73.57", "45,50; -73,57",
 * "45.5N 73.57W" and the lon/lat order "-73.57, 45.50".
 * Order rules (explicit, never guessed silently):
 *  1. hemisphere letters decide (N/S = latitude, E/W/O = longitude);
 *  2. otherwise a value beyond ±90 can only be a longitude;
 *  3. otherwise, if exactly one order falls inside Greater Montréal, that order is used;
 *  4. otherwise both readings are returned with `ambiguous: true` for the user to choose.
 * Needs a decimal part or a hemisphere letter, so "1455 12" stays an address query.
 */
export function parseCoordinates(input: string): CoordParse {
  const s = input.trim();
  let m: RegExpExecArray | null = null;
  for (const re of PATTERNS) {
    m = re.exec(s);
    if (m) break;
  }
  if (!m || ORDINAL.test(s)) return { kind: 'none' };
  const a = part(m[1]!, m[2]);
  const b = part(m[3]!, m[4]);
  if (!(a.decimals || b.decimals || a.hemi || b.hemi)) return { kind: 'none' };

  const make = (order: CoordOrder): CoordCandidate => {
    const p = order === 'lat_lon' ? { lat: a.v, lon: b.v } : { lat: b.v, lon: a.v };
    return { ...p, order, inArea: inSearchArea(p) };
  };
  const isLat = (x: Part) => x.hemi === 'N' || x.hemi === 'S';
  const isLon = (x: Part) => x.hemi === 'E' || x.hemi === 'W';

  let orders: CoordOrder[];
  if (isLat(a) || isLon(b)) orders = ['lat_lon'];
  else if (isLon(a) || isLat(b)) orders = ['lon_lat'];
  else orders = ['lat_lon', 'lon_lat'];

  const valid = orders.map(make).filter((c) => validLat(c.lat) && validLon(c.lon));
  if (valid.length === 0) return { kind: 'out_of_range' };
  if (valid.length === 1) return { kind: 'coords', candidates: valid, ambiguous: false };
  // Same numbers in both orders (e.g. "45.5, 45.5"): one reading.
  if (valid[0]!.lat === valid[1]!.lat && valid[0]!.lon === valid[1]!.lon) return { kind: 'coords', candidates: [valid[0]!], ambiguous: false };
  const inside = valid.filter((c) => c.inArea);
  if (inside.length === 1) return { kind: 'coords', candidates: inside, ambiguous: false };
  return { kind: 'coords', candidates: valid, ambiguous: true };
}
