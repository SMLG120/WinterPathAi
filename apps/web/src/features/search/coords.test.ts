import { describe, expect, it } from 'vitest';
import { parseCoordinates } from './coords';

describe('parseCoordinates', () => {
  it('lat, lon with dot decimals', () => {
    expect(parseCoordinates('45.50, -73.57')).toEqual({
      kind: 'coords',
      ambiguous: false,
      candidates: [{ lat: 45.5, lon: -73.57, order: 'lat_lon', inArea: true }],
    });
  });
  it('space separated, French decimal comma with semicolon or space', () => {
    for (const q of ['45.50 -73.57', '45,50; -73,57', '45,50 -73,57']) {
      const r = parseCoordinates(q);
      expect(r.kind === 'coords' && r.candidates[0]).toMatchObject({ lat: 45.5, lon: -73.57 });
    }
  });
  it('lon, lat order is detected when only that order lands in Greater Montréal', () => {
    const r = parseCoordinates('-73.57, 45.50');
    expect(r).toMatchObject({ kind: 'coords', ambiguous: false, candidates: [{ lat: 45.5, lon: -73.57, order: 'lon_lat' }] });
  });
  it('a value beyond ±90 can only be a longitude', () => {
    const r = parseCoordinates('120.5, 45.5');
    expect(r).toMatchObject({ kind: 'coords', ambiguous: false, candidates: [{ lon: 120.5, lat: 45.5, order: 'lon_lat', inArea: false }] });
  });
  it('hemisphere letters decide the order and the sign', () => {
    expect(parseCoordinates('73.57W 45.5N')).toMatchObject({ kind: 'coords', candidates: [{ lat: 45.5, lon: -73.57, order: 'lon_lat' }] });
    expect(parseCoordinates('45.5 N, 73.57 O')).toMatchObject({ kind: 'coords', candidates: [{ lat: 45.5, lon: -73.57, order: 'lat_lon' }] });
  });
  it('both orders valid and neither in the area → both offered, ambiguous', () => {
    const r = parseCoordinates('10.5, 20.25');
    expect(r).toMatchObject({ kind: 'coords', ambiguous: true });
    expect(r.kind === 'coords' && r.candidates.map((c) => c.order)).toEqual(['lat_lon', 'lon_lat']);
  });
  it('out of range in every order', () => {
    expect(parseCoordinates('145.5, -273.5')).toEqual({ kind: 'out_of_range' });
  });
  it('addresses and bare integers are not coordinates', () => {
    for (const q of ['1455 12', '1455 boul De Maisonneuve', 'Gare Centrale', '45', '']) expect(parseCoordinates(q)).toEqual({ kind: 'none' });
  });
});
