import { z } from 'zod';
import type { TFunction } from 'i18next';
import type { PilotRequest } from '@/api/types';

export const PILOT_SEGMENTS = ['university', 'campus', 'municipality', 'property_manager', 'other'] as const;

export function pilotSchema(t: TFunction) {
  return z.object({
    organization: z.string().trim().min(1, { message: t('pilot:form.required') }).max(120),
    contact_name: z.string().trim().max(120),
    contact_email: z.string().trim().email({ message: t('pilot:form.invalidEmail') }),
    segment: z.enum(PILOT_SEGMENTS, { message: t('pilot:form.required') }),
    message: z.string().max(1000),
    consent: z.boolean().refine((v) => v === true, { message: t('pilot:form.consentRequired') }),
  });
}

export type PilotFormValues = z.input<ReturnType<typeof pilotSchema>>;

export function toPilotRequest(v: PilotFormValues, locale: 'en' | 'fr'): PilotRequest {
  const body: PilotRequest = {
    organization: v.organization.trim(),
    contact_email: v.contact_email.trim(),
    segment: v.segment as PilotRequest['segment'],
    consent: true,
    locale,
  };
  if (v.contact_name.trim()) body.contact_name = v.contact_name.trim();
  if (v.message.trim()) body.message = v.message.trim();
  return body;
}
