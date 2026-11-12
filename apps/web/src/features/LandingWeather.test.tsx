import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { WeatherCurrent } from '@/api/types';

const state: { q: unknown } = { q: null };
vi.mock('@/api/queries', () => ({ useWeatherCurrent: () => state.q }));
const { LandingWeather } = await import('./LandingWeather');

const w: WeatherCurrent = {
  station_id: 'CWTA',
  station_name: 'Montréal/McTavish',
  observed_at: '2026-11-11T22:00:00Z',
  temperature_c: -3.4,
  wind_speed_kmh: null,
  snow_depth_cm: 2,
  evidence: { state: 'confirmed', source_ids: ['eccc-geomet'], observed_at: '2026-11-11T22:00:00Z', retrieved_at: '2026-11-11T22:05:00Z' },
};

describe('LandingWeather', () => {
  it('shows the observed values, keeps a missing value missing, and labels evidence', () => {
    state.q = { isPending: false, isError: false, isSuccess: true, data: w };
    render(<LandingWeather />);
    const el = screen.getByTestId('landing-weather');
    expect(el).toHaveTextContent('-3.4 °C');
    expect(el).toHaveTextContent('Wind: —');
    expect(el).toHaveTextContent('Montréal/McTavish');
    expect(el.querySelector('[data-evidence="confirmed"]')).not.toBeNull();
  });
  it('failure: a plain message and no numbers', () => {
    state.q = { isPending: false, isError: true, isSuccess: false, error: new Error('x') };
    render(<LandingWeather />);
    expect(screen.getByTestId('landing-weather-unavailable')).toBeInTheDocument();
    expect(screen.getByTestId('landing-weather').textContent).not.toMatch(/°C|km\/h/);
  });
  it('loading: skeleton, busy, no values', () => {
    state.q = { isPending: true, isError: false, isSuccess: false };
    render(<LandingWeather />);
    expect(screen.getByTestId('landing-weather')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByTestId('landing-weather').textContent).not.toMatch(/°C/);
  });
});
