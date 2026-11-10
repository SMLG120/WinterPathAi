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
