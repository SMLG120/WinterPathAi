import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PointInput } from '@/features/plan/PointInput';
import { usePlannerStore } from '@/stores/planner';
import { SearchBox } from './SearchBox';
import { StaticIndexProvider } from './staticProvider';
import { testFetch } from './testIndex';
import { SearchProviderContext } from './useSearch';

function setup(o?: Parameters<typeof testFetch>[0]) {
  const t = testFetch(o);
  const provider = new StaticIndexProvider('/search/', t.fetch);
  const user = userEvent.setup();
  render(
    <SearchProviderContext.Provider value={provider}>
      <SearchBox />
    </SearchProviderContext.Provider>,
  );
  return { user, calls: t.calls, input: screen.getByRole('combobox', { name: /search an address or place/i }) };
}

describe('SearchBox — combobox semantics and keyboard', () => {
  beforeEach(() => usePlannerStore.getState().reset());

  it('exposes an ARIA combobox controlling a listbox', async () => {
    const { user, input } = setup();
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(input).toHaveAttribute('aria-autocomplete', 'list');
    const listId = input.getAttribute('aria-controls')!;
    await user.type(input, 'gare');
    const list = await screen.findByRole('listbox');
    expect(list.id).toBe(listId);
    expect(input).toHaveAttribute('aria-expanded', 'true');
    const options = within(list).getAllByRole('option');
    expect(options[0]).toHaveTextContent('Gare Centrale');
    expect(options[0]).toHaveTextContent('OpenStreetMap');
    expect(options[0]).toHaveTextContent('Unverified report');
  });

  it('Up/Down move aria-activedescendant (wrapping), Enter chooses → start set with its label', async () => {
    const { user, input } = setup();
    await user.type(input, 'maisonneuve');
    const options = await screen.findAllByRole('option');
    expect(options.length).toBe(3);
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute('aria-activedescendant', options[0]!.id);
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowUp}');
    expect(input).toHaveAttribute('aria-activedescendant', options[2]!.id);
    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute('aria-activedescendant', options[0]!.id);

    await user.clear(input);
    await user.type(input, '1455 boul de maisonneuve o');
    await screen.findByText('1455 Boulevard De Maisonneuve Ouest');
    await user.keyboard('{ArrowDown}{Enter}');
    const s = usePlannerStore.getState();
    expect(s.origin).toEqual({ lon: -73.579, lat: 45.4973 });
    expect(s.labels.origin).toMatchObject({ text: '1455 Boulevard De Maisonneuve Ouest', source: 'rqa', quality: 'building', evidence: 'confirmed' });
    expect(input).toHaveValue('1455 Boulevard De Maisonneuve Ouest');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByTestId('search-status')).toHaveTextContent('Start set to 1455 Boulevard De Maisonneuve Ouest');
    // The next result fills the destination.
    expect(screen.getByTestId('search-fill-destination')).toBeChecked();
  });

  it('Escape closes the list, a second Escape clears the text', async () => {
    const { user, input } = setup();
    await user.type(input, 'gare');
    await screen.findByRole('listbox');
    await user.keyboard('{Escape}');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(input).toHaveValue('gare');
    await user.keyboard('{Escape}');
    expect(input).toHaveValue('');
  });

  it('the chosen fill target receives the point (destination)', async () => {
    const { user, input } = setup();
    await user.click(screen.getByTestId('search-fill-destination'));
    await user.type(input, 'universite mcgill');
    await user.click(await screen.findByText('Université McGill'));
    const s = usePlannerStore.getState();
    expect(s.origin).toBeNull();
    expect(s.destination).toEqual({ lon: -73.57871, lat: 45.50689 });
    expect(s.labels.destination).toMatchObject({ source: 'osm', evidence: 'unverified_report', kind: 'place' });
  });

  it('a street (no civic number) completes the text and sets no point', async () => {
    const { user, input } = setup();
    await user.type(input, 'maisonneuve, laval');
    await user.click(await screen.findByText('Rue Maisonneuve'));
    expect(input).toHaveValue('Rue Maisonneuve, Laval');
    expect(usePlannerStore.getState().origin).toBeNull();
  });
});

describe('SearchBox — states', () => {
  beforeEach(() => usePlannerStore.getState().reset());

  it('debounces: typing a word issues one index lookup', async () => {
    const { user, input, calls } = setup();
    await user.type(input, 'gare centrale');
    await screen.findByRole('listbox');
    expect(calls).toEqual(['/search/manifest.json', '/search/v/test/s/ga.json']);
  });

  it('loading state while the index answers', async () => {
    const { user, input } = setup({ delayMs: 400 });
    await user.type(input, 'gare');
    expect(await screen.findByText('Searching…')).toBeInTheDocument();
    await screen.findByRole('listbox', undefined, { timeout: 3000 });
  });

  it('empty state names the query', async () => {
    const { user, input } = setup();
    await user.type(input, 'zzqx');
    expect(await screen.findByText(/No address or place matches “zzqx”/)).toBeInTheDocument();
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('too short and invalid coordinates have their own messages', async () => {
    const { user, input } = setup();
    await user.type(input, 'g');
    expect(await screen.findByText(/at least two letters/)).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, '145.5, -273.5');
    expect(await screen.findByText(/not valid coordinates/)).toBeInTheDocument();
  });

  it('error state: index unavailable → message + Retry refetches', async () => {
    const { user, input, calls } = setup({ manifest: null });
    await user.type(input, 'gare');
    expect(await screen.findByText(/Search is unavailable right now/)).toBeInTheDocument();
    const before = calls.length;
    await user.click(screen.getByTestId('search-retry'));
    await waitFor(() => expect(calls.length).toBeGreaterThan(before));
    expect(await screen.findByText(/Search is unavailable right now/)).toBeInTheDocument();
  });

  it('typed coordinates are offered as a point', async () => {
    const { user, input } = setup();
    await user.type(input, '45.5048, -73.5772');
    const opt = await screen.findByRole('option');
    expect(opt).toHaveTextContent('Coordinates you typed');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(usePlannerStore.getState().origin).toEqual({ lat: 45.5048, lon: -73.5772 });
  });

  it('shows the RQA and OSM attribution', () => {
    setup();
    expect(screen.getByTestId('search-attribution')).toHaveTextContent(/Référentiel québécois des adresses.*CC BY 4\.0.*OpenStreetMap contributors \(ODbL\)/);
  });
});

describe('PointInput shows where a searched point came from', () => {
  beforeEach(() => usePlannerStore.getState().reset());

  it('label, position quality, evidence and the "not a confirmed endpoint" note', () => {
    usePlannerStore.getState().setPoint('destination', { lon: -73.579, lat: 45.4973 }, {
      text: '1455 Boulevard De Maisonneuve Ouest',
      detail: 'Montréal',
      kind: 'address',
      source: 'rqa',
      quality: 'uncertain',
      evidence: 'unknown',
    });
    render(<PointInput which="destination" />);
    const box = screen.getByTestId('point-destination-label');
    expect(box).toHaveTextContent('1455 Boulevard De Maisonneuve Ouest');
    expect(box).toHaveTextContent('uncertain position');
    expect(box).toHaveTextContent('Unknown');
    expect(box).toHaveTextContent(/not a confirmed walking endpoint/);
  });

  it('setting the point another way (map, coordinates) drops the label', () => {
    const s = usePlannerStore.getState();
    s.setPoint('origin', { lon: -73.5, lat: 45.5 }, { text: 'X', detail: '', kind: 'place', source: 'osm', evidence: 'unverified_report' });
    s.setPicking('origin');
    s.pickFromMap({ lon: -73.51, lat: 45.51 });
    expect(usePlannerStore.getState().labels.origin).toBeNull();
    s.setPoint('destination', { lon: -73.5, lat: 45.5 }, { text: 'Y', detail: '', kind: 'place', source: 'osm', evidence: 'unverified_report' });
    s.swap();
    expect(usePlannerStore.getState().labels).toMatchObject({ origin: { text: 'Y' }, destination: null });
    usePlannerStore.getState().setPoint('origin', { lon: -73.52, lat: 45.52 });
    expect(usePlannerStore.getState().labels.origin).toBeNull();
  });
});
