import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { DataSource } from '@/api/types';
import { dataSources } from '@/mocks/fixtures';
import { HazardList } from './HazardList';
import { HazardSourceNotice } from './HazardSourceNotice';
import { hazardCoverage } from './hazardCoverage';

const withStatus = (status: Record<string, DataSource['status']>): DataSource[] =>
  dataSources().map((s) => (status[s.id] ? { ...s, status: status[s.id]! } : s));

describe('hazardCoverage', () => {
  it('complete only when both closure and 311 sources are active', () => {
    expect(hazardCoverage(withStatus({ 'mtl-entraves': 'active', 'mtl-311': 'active' }))).toEqual({ state: 'complete' });
  });
  it('lists every hazard source that is not active, with its status', () => {
    expect(hazardCoverage(withStatus({ 'mtl-entraves': 'active', 'mtl-311': 'stale' }))).toEqual({
      state: 'partial',
      gaps: [{ name: 'Requêtes 311', status: 'stale' }],
    });
    // API_STORE_BACKEND=memory: the API reports both as disabled.
    expect(hazardCoverage(dataSources())).toMatchObject({ state: 'partial', gaps: [{ status: 'disabled' }, { status: 'disabled' }] });
  });
  it('a source missing from /data-sources counts as not loaded', () => {
    expect(hazardCoverage(dataSources().filter((s) => s.id !== 'mtl-entraves'))).toMatchObject({
      state: 'partial',
      gaps: [{ name: 'mtl-entraves', status: 'disabled' }, { status: 'disabled' }],
    });
  });
  it('/data-sources unknown (loading or failed) is "unchecked", never complete', () => {
    expect(hazardCoverage(undefined)).toEqual({ state: 'unchecked' });
  });
});

describe('HazardSourceNotice / HazardList', () => {
  const partial = hazardCoverage(dataSources());

  it('route context: says the routes could not avoid closures, labelled Unknown, naming each source', () => {
    render(<HazardSourceNotice coverage={partial} context="route" />);
    const n = screen.getByTestId('hazard-sources-route');
    expect(n).toHaveTextContent('These routes could not take closures or 311 reports into account');
    expect(n).toHaveTextContent('Entraves et travaux en cours: not loaded');
    expect(n).toHaveTextContent('Requêtes 311: not loaded');
    expect(n.querySelector('[data-evidence="unknown"]')).not.toBeNull();
  });

  it('renders nothing when every hazard source is loaded', () => {
    const { container } = render(<HazardSourceNotice coverage={{ state: 'complete' }} context="overlay" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('empty list says "none" only when coverage is complete', () => {
    const { rerender } = render(<HazardList hazards={[]} coverage={{ state: 'complete' }} />);
    expect(screen.getByText('No closures or reports in this view.')).toBeInTheDocument();
    for (const c of [partial, { state: 'unchecked' } as const]) {
      rerender(<HazardList hazards={[]} coverage={c} />);
      expect(screen.queryByText('No closures or reports in this view.')).toBeNull();
    }
  });

  it('unchecked: says it could not check the sources', () => {
    render(<HazardSourceNotice coverage={{ state: 'unchecked' }} context="overlay" />);
    expect(screen.getByTestId('hazard-sources-overlay')).toHaveTextContent("We couldn't check which closure and report sources are loaded.");
  });
});
