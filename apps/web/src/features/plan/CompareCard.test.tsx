import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { CompareCard } from './CompareCard';
import { RouteError } from './RouteError';
import { mockCompare } from '@/mocks/routes';
import { ApiRequestError } from '@/api/client';

const A = { lon: -73.5772, lat: 45.5048 };
const B = { lon: -73.5745, lat: 45.504 };

function data() {
  const r = mockCompare({ origin: A, destination: B, locale: 'en' }, new Date());
  if (r.status !== 200) throw new Error('expected 200');
  return r.body;
}

describe('CompareCard', () => {
  it('shows both routes with distance, time, unknown share and evidence-labelled explanations', () => {
    render(<CompareCard data={data()} selected="winter_aware" onSelect={vi.fn()} />);
    for (const v of ['shortest', 'winter_aware']) {
      const card = screen.getByTestId(`route-${v}`);
      expect(within(card).getByText('Distance')).toBeInTheDocument();
      expect(within(card).getByText('Walking time')).toBeInTheDocument();
      expect(within(card).getByText('No condition data')).toBeInTheDocument();
      expect(card.querySelectorAll('[data-evidence="simulated"]').length).toBeGreaterThan(0);
      expect(card.querySelectorAll('[data-evidence="unknown"]').length).toBeGreaterThan(0);
    }
    expect(screen.getAllByRole('note')[0]).toHaveTextContent('SIMULATED');
    expect(screen.getByText(/Risk layer/)).toHaveTextContent('None — risk is unknown');
  });

  it('lists step-by-step directions (map alternative)', () => {
    render(<CompareCard data={data()} selected="winter_aware" onSelect={vi.fn()} />);
    const steps = screen.getByTestId('steps-winter_aware');
    expect(within(steps).getAllByRole('listitem').length).toBeGreaterThan(1);
  });
});

describe('RouteError', () => {
  it('NO_ROUTE explains the step-free hard constraint', () => {
    render(<RouteError error={new ApiRequestError(404, { code: 'NO_ROUTE', message: 'x' }, null)} />);
    expect(screen.getByRole('alert')).toHaveTextContent('No route found');
    expect(screen.getByRole('alert')).toHaveTextContent(/step-free/);
  });
  it('OUTSIDE_COVERAGE points to the pilot area', () => {
    render(<RouteError error={new ApiRequestError(422, { code: 'OUTSIDE_COVERAGE', message: 'x' }, null)} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Outside the pilot area');
  });
  it('OFF_NETWORK names the point and the snap distance', () => {
    render(
      <RouteError
        error={new ApiRequestError(422, { code: 'OFF_NETWORK', message: 'x', details: { which: 'destination', max_snap_distance_m: 75, nearest_network_m: 412.3 } }, null)}
      />,
    );
    const a = screen.getByRole('alert');
    expect(a).toHaveTextContent('Too far from the walking network');
    expect(a).toHaveTextContent('Your destination is inside the pilot area but more than 75 m');
    expect(a).toHaveTextContent('about 412 m away');
  });
  it('legacy snap error (OUTSIDE_COVERAGE + snap details) gets the same network copy', () => {
    render(
      <RouteError error={new ApiRequestError(422, { code: 'OUTSIDE_COVERAGE', message: 'x', details: { which: 'origin', max_snap_distance_m: 75 } }, null)} />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Your start is inside the pilot area');
  });
  it('RATE_LIMITED shows Retry-After', () => {
    render(<RouteError error={new ApiRequestError(429, { code: 'RATE_LIMITED', message: 'x' }, '30')} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Try again in 30 seconds');
  });
  it('network failure gets generic copy', () => {
    render(<RouteError error={new ApiRequestError(0, undefined, null)} />);
    expect(screen.getByRole('alert')).toHaveTextContent("Couldn't compute routes");
  });
});
