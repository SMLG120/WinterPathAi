import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';
// Map e2e fixtures (long route + multi-part coverage, overlay outage); inert unless localStorage `wp-mock-fixture` is set.
import { mapFixtureHandlers } from '@/features/map/fixtures/handlers';

export const worker = setupWorker(...mapFixtureHandlers, ...handlers);
