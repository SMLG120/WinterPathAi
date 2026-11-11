/** Mock-only geometry helpers. The real app never computes routes in the browser. */
export type Pos = [number, number];

export function haversineM([lon1, lat1]: Pos, [lon2, lat2]: Pos): number {
  const R = 6_371_008.8;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

export function lineLength(coords: Pos[]): number {
  let d = 0;
  for (let i = 1; i < coords.length; i++) d += haversineM(coords[i - 1]!, coords[i]!);
  return d;
}

export function geomIntersectsBbox(coords: Pos[], [w, s, e, n]: [number, number, number, number]): boolean {
  const xs = coords.map((c) => c[0]);
  const ys = coords.map((c) => c[1]);
  return Math.max(...xs) >= w && Math.min(...xs) <= e && Math.max(...ys) >= s && Math.min(...ys) <= n;
}

/** Approximate point-to-segment distance in metres (local equirectangular; fine at block scale). */
export function pointSegmentM(p: Pos, a: Pos, b: Pos): number {
  const k = Math.cos((p[1] * Math.PI) / 180) * 111_320;
  const toXY = (q: Pos) => [(q[0] - p[0]) * k, (q[1] - p[1]) * 110_540] as const;
  const [ax, ay] = toXY(a);
  const [bx, by] = toXY(b);
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

export function nearestLineM(p: Pos, lines: Pos[][]): number {
  let best = Infinity;
  for (const l of lines) for (let i = 1; i < l.length; i++) best = Math.min(best, pointSegmentM(p, l[i - 1]!, l[i]!));
  return best;
}
