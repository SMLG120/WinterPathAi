import { describe, expect, it } from 'vitest';
import { bboxArea, clipToPilot, formatBbox, isInPilot, isQueryableBbox, isValidLonLat, type Bbox } from './geo';
import { switchLangPath } from './i18n-routing';
import { isStale } from './format';

describe('geo helpers (EPSG:4326, [lon, lat])', () => {
  it('clips a large viewport to the pilot bbox so it is queryable', () => {
    const city: Bbox = [-73.7, 45.4, -73.5, 45.6];
    expect(isQueryableBbox(city)).toBe(false);
    const c = clipToPilot(city)!;
    expect(c).toEqual([-73.588, 45.496, -73.562, 45.513]);
    expect(isQueryableBbox(c)).toBe(true);
    expect(bboxArea(c)).toBeLessThanOrEqual(0.0025);
  });

  it('returns null when viewport is outside the pilot', () => {
    expect(clipToPilot([-73.7, 45.6, -73.65, 45.65])).toBeNull();
  });

  it('formats bbox to match the contract pattern', () => {
    const s = formatBbox([-73.588, 45.496, -73.562, 45.513]);
    expect(s).toMatch(/^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$/);
    expect(s.startsWith('-73.58800,45.49600')).toBe(true);
  });

  it('pilot containment and coordinate validity', () => {
    expect(isInPilot({ lon: -73.5772, lat: 45.5048 })).toBe(true);
    expect(isInPilot({ lon: 45.5048, lat: -73.5772 })).toBe(false); // swapped order is rejected
    expect(isValidLonLat({ lon: 200, lat: 0 })).toBe(false);
    expect(isValidLonLat({ lon: Number.NaN, lat: 0 })).toBe(false);
  });
});

describe('language routing', () => {
  it('switches the prefix and preserves the route', () => {
    expect(switchLangPath('/en/plan', 'fr')).toBe('/fr/plan');
    expect(switchLangPath('/fr/how-it-works', 'en')).toBe('/en/how-it-works');
    expect(switchLangPath('/en', 'fr')).toBe('/fr');
    expect(switchLangPath('/plan', 'fr')).toBe('/fr/plan');
  });
});

describe('freshness', () => {
  it('flags data older than 6 h as stale; null is not stale but "never"', () => {
    const now = Date.parse('2026-01-10T12:00:00Z');
    expect(isStale('2026-01-10T05:00:00Z', now)).toBe(true);
    expect(isStale('2026-01-10T10:00:00Z', now)).toBe(false);
    expect(isStale(null, now)).toBe(false);
  });
});
