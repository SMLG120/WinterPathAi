import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { act } from 'react';
import i18n from '@/i18n';
import { EVIDENCE_STATES } from '@/api/types';
import { EvidenceBadge, SimulatedBanner } from './EvidenceBadge';
import { EVIDENCE_GLYPH } from './glyphs';

describe('EvidenceBadge', () => {
  it.each(EVIDENCE_STATES)('%s renders icon glyph AND text label (never colour alone)', (state) => {
    const { container } = render(<EvidenceBadge state={state} />);
    const badge = container.querySelector(`[data-evidence="${state}"]`)!;
    expect(badge).toBeInTheDocument();
    expect(badge.textContent).toContain(EVIDENCE_GLYPH[state]);
    expect(badge.textContent).toContain(i18n.t(`common:evidence.${state}`));
  });

  it('each state has a distinct glyph', () => {
    expect(new Set(Object.values(EVIDENCE_GLYPH)).size).toBe(EVIDENCE_STATES.length);
  });

  it('simulated is labelled SIMULATED in EN and SIMULÉ in FR', async () => {
    render(<EvidenceBadge state="simulated" />);
    expect(screen.getByText('SIMULATED')).toBeInTheDocument();
    await act(() => i18n.changeLanguage('fr'));
    expect(screen.getByText('SIMULÉ')).toBeInTheDocument();
    await act(() => i18n.changeLanguage('en'));
  });

  it('withDescription shows that unknown is not zero risk', () => {
    render(<EvidenceBadge state="unknown" withDescription />);
    expect(screen.getByText(/never treated as zero risk/i)).toBeInTheDocument();
  });

  it('SimulatedBanner is a visible note', () => {
    render(<SimulatedBanner>demo</SimulatedBanner>);
    expect(screen.getByRole('note')).toHaveTextContent('SIMULATED — demo');
  });
});
