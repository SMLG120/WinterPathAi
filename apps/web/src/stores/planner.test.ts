import { beforeEach, describe, expect, it } from 'vitest';
import { usePlannerStore } from './planner';

const A = { lon: -73.577, lat: 45.505 };
const B = { lon: -73.57, lat: 45.502 };
const C = { lon: -73.575, lat: 45.5 };

describe('planner store', () => {
  beforeEach(() => usePlannerStore.getState().reset());

  it('map clicks fill origin, then destination, then replace destination', () => {
    const s = usePlannerStore.getState();
    s.pickFromMap(A);
    s.pickFromMap(B);
    expect(usePlannerStore.getState()).toMatchObject({ origin: A, destination: B });
    s.pickFromMap(C);
    expect(usePlannerStore.getState()).toMatchObject({ origin: A, destination: C });
  });

  it('explicit picking target wins and is cleared after the click', () => {
    const s = usePlannerStore.getState();
    s.setPoint('origin', A);
    s.setPoint('destination', B);
    s.setPicking('origin');
    s.pickFromMap(C);
    expect(usePlannerStore.getState()).toMatchObject({ origin: C, destination: B, picking: null });
  });

  it('swap exchanges points', () => {
    const s = usePlannerStore.getState();
    s.setPoint('origin', A);
    s.setPoint('destination', B);
    s.swap();
    expect(usePlannerStore.getState()).toMatchObject({ origin: B, destination: A });
  });

  it('never persists coordinates to storage (no location tracking)', () => {
    localStorage.clear();
    usePlannerStore.getState().setPoint('origin', A);
    const dump = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(dump).not.toContain('45.505');
    expect(dump).not.toContain('-73.577');
  });

  it('defaults: standard profile, avoid unverified reports (contract default)', () => {
    expect(usePlannerStore.getState()).toMatchObject({ profile: 'standard', avoidUnverifiedReports: true });
  });
});
