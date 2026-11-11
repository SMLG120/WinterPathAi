import { z } from 'zod';

// The production CSP has no 'unsafe-eval': skip zod's `new Function` probe (it would log a CSP violation).
z.config({ jitless: true });
import type { TFunction } from 'i18next';
import type { ReportCategory, ReportCreate } from '@/api/types';
import { isInPilot } from '@/lib/geo';

export const REPORT_CATEGORIES: ReportCategory[] = ['snow', 'ice', 'obstructed_ramp', 'construction', 'other'];
export const MAX_DESCRIPTION = 280;

const toNum = (s: string) => Number.parseFloat(s.trim().replace(',', '.'));

export function reportSchema(t: TFunction) {
  const coord = (min: number, max: number) =>
    z
      .string()
      .trim()
      .refine((s) => s !== '' && Number.isFinite(toNum(s)) && toNum(s) >= min && toNum(s) <= max, {
        message: t('reports:validation.coords'),
      });
  return z
    .object({
      category: z.enum(REPORT_CATEGORIES as [ReportCategory, ...ReportCategory[]], { message: t('reports:validation.category') }),
      lat: coord(-90, 90),
      lon: coord(-180, 180),
      consent: z.boolean().refine((v) => v === true, { message: t('reports:validation.consent') }),
      description: z.string().max(MAX_DESCRIPTION, { message: t('reports:validation.tooLong') }),
    })
    .refine((v) => !Number.isFinite(toNum(v.lat)) || !Number.isFinite(toNum(v.lon)) || isInPilot({ lat: toNum(v.lat), lon: toNum(v.lon) }), {
      message: t('reports:validation.outside'),
      path: ['lat'],
    });
}

export type ReportFormValues = z.input<ReturnType<typeof reportSchema>>;

export function toReportCreate(v: ReportFormValues, locale: 'en' | 'fr'): ReportCreate {
  const body: ReportCreate = {
    category: v.category as ReportCategory,
    location: { lat: toNum(v.lat), lon: toNum(v.lon) },
    location_consent: true,
    locale,
  };
  const d = v.description.trim();
  if (d) body.description = d;
  return body;
}
