import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ConditionExplainer } from './ConditionExplainer';

describe('ConditionExplainer', () => {
  it('is a keyboard-operable tablist whose panel carries the lens evidence label', () => {
    render(<ConditionExplainer />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(5);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveAttribute('data-lens', 'steps');
    // OSM step-free tags are community-mapped: unverified, never "confirmed".
    expect(screen.getByRole('tabpanel').querySelector('[data-evidence="unverified_report"]')).not.toBeNull();
    expect(screen.getByRole('tabpanel').textContent).toMatch(/community-mapped/);
    expect(screen.getByRole('tabpanel').textContent).not.toMatch(/confirm/i);

    fireEvent.keyDown(tabs[0]!, { key: 'ArrowRight' });
    expect(screen.getByRole('tabpanel')).toHaveAttribute('data-lens', 'closure');
    expect(screen.getByRole('tab', { name: 'Sidewalk work' })).toHaveFocus();
    expect(screen.getByRole('tabpanel').querySelector('[data-evidence="confirmed"]')).not.toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: '311 reports' }));
    expect(screen.getByRole('tabpanel').querySelector('[data-evidence="unverified_report"]')).not.toBeNull();

    // Snow-loading schedules never produce a sidewalk evidence state, and never say "cleared" affirmatively.
    fireEvent.click(screen.getByRole('tab', { name: 'Snow removal' }));
    const panel = screen.getByRole('tabpanel');
    expect(panel.querySelector('[data-evidence]')).toBeNull();
    expect(panel.textContent).toMatch(/does not certify/);

    fireEvent.keyDown(screen.getByRole('tab', { name: 'Snow removal' }), { key: 'End' });
    expect(screen.getByRole('tabpanel')).toHaveAttribute('data-lens', 'weather');
    expect(screen.getByRole('tabpanel').textContent).toMatch(/Unknown, never low/);
    expect(screen.getByRole('tabpanel').textContent).toMatch(/labelled heuristic/);
    expect(screen.getByRole('tabpanel').textContent).not.toMatch(/forecast/i);
  });

  it('without WebGL (jsdom) shows no 3D stage — the text panel stands alone', () => {
    render(<ConditionExplainer />);
    expect(screen.queryByTestId('explainer-stage')).toBeNull();
  });
});
