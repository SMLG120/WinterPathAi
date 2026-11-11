import { describe, expect, it } from 'vitest';
import i18n from '@/i18n';
import { reportSchema, toReportCreate } from './reportSchema';
import { pilotSchema, toPilotRequest } from './pilotSchema';

const t = i18n.getFixedT('en');
const ok = { category: 'ice' as const, lat: '45.5048', lon: '-73.5772', consent: true, description: '' };

describe('report form schema', () => {
  it('accepts a valid report and builds a contract body with location_consent=true', () => {
    const r = reportSchema(t).safeParse(ok);
    expect(r.success).toBe(true);
    expect(toReportCreate(ok, 'fr')).toEqual({
      category: 'ice',
      location: { lat: 45.5048, lon: -73.5772 },
      location_consent: true,
      locale: 'fr',
    });
  });
  it('requires explicit consent', () => {
    const r = reportSchema(t).safeParse({ ...ok, consent: false });
    expect(r.success).toBe(false);
    expect(JSON.stringify(r.error?.issues)).toContain('consent');
  });
  it('limits description to 280 chars', () => {
    expect(reportSchema(t).safeParse({ ...ok, description: 'x'.repeat(281) }).success).toBe(false);
    expect(reportSchema(t).safeParse({ ...ok, description: 'x'.repeat(280) }).success).toBe(true);
  });
  it('rejects locations outside the pilot area and invalid coordinates', () => {
    expect(reportSchema(t).safeParse({ ...ok, lat: '45.60' }).success).toBe(false);
    expect(reportSchema(t).safeParse({ ...ok, lat: 'abc' }).success).toBe(false);
  });
  it('accepts comma decimal separator (fr-CA input)', () => {
    expect(reportSchema(t).safeParse({ ...ok, lat: '45,5048', lon: '-73,5772' }).success).toBe(true);
  });
});

describe('pilot form schema', () => {
  const base = { organization: 'Org', contact_name: '', contact_email: 'a@example.org', segment: 'campus' as const, message: '', consent: true };
  it('builds a minimal PilotRequest (no empty optional fields)', () => {
    expect(pilotSchema(t).safeParse(base).success).toBe(true);
    expect(toPilotRequest(base, 'en')).toEqual({ organization: 'Org', contact_email: 'a@example.org', segment: 'campus', consent: true, locale: 'en' });
  });
  it('requires consent and a valid email', () => {
    expect(pilotSchema(t).safeParse({ ...base, consent: false }).success).toBe(false);
    expect(pilotSchema(t).safeParse({ ...base, contact_email: 'nope' }).success).toBe(false);
  });
});
