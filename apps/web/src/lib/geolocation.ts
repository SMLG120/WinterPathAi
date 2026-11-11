import type { LonLat } from '@/api/types';

export type GeoFailure = 'denied' | 'unavailable' | 'unsupported';

/**
 * One-shot browser geolocation. Only call after an explicit user action and
 * in-app explanation. The result is never logged or persisted.
 */
export function getCurrentLonLat(timeoutMs = 10_000): Promise<LonLat> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      reject('unsupported' satisfies GeoFailure);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lon: pos.coords.longitude, lat: pos.coords.latitude }),
      (err) => reject((err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable') satisfies GeoFailure),
      { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 60_000 },
    );
  });
}
