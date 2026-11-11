import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Alerts } from './Winter';
import type { WeatherForecast } from '@/api/types';

// TEST-ONLY fake alert used to check rendering; never shown to users.
const fake: WeatherForecast = {
  issued_at: '2026-01-10T12:00:00Z',
  periods: [],
  evidence: { state: 'simulated', source_ids: ['test'], observed_at: null },
  alerts: [
    {
      id: 'test-1',
      headline: 'TEST ALERT HEADLINE — avertissement',
      text: 'Line one.\nLine two, exactly as given.',
      language: 'fr',
      severity: 'moderate',
      issued_at: '2026-01-10T12:00:00Z',
      expires_at: null,
    },
  ],
};

describe('Weather alerts', () => {
  it('reproduces alert text unaltered and tags its original language', () => {
    const { container } = render(<Alerts f={fake} />);
    expect(screen.getByText('TEST ALERT HEADLINE — avertissement')).toBeInTheDocument();
    const p = screen.getByText(/Line one\./);
    expect(p.textContent).toBe('Line one.\nLine two, exactly as given.');
    expect(container.querySelector('[lang="fr-CA"]')).not.toBeNull();
  });
  it('shows an explicit empty state', () => {
    render(<Alerts f={{ ...fake, alerts: [] }} />);
    expect(screen.getByTestId('alerts-none')).toBeInTheDocument();
  });
});
