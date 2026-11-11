import type { DataSource } from '@/api/types';
import { useDataSources } from '@/api/queries';

/**
 * Sources whose data becomes closures / 311 hazards (map overlay and route avoidance).
 * When one of them isn't `active` (e.g. the free-tier demo runs API_STORE_BACKEND=memory and
 * /data-sources reports them `disabled`), an empty hazard list means "not loaded", never "none".
 */
export const HAZARD_SOURCE_IDS = ['mtl-entraves', 'mtl-311'] as const;

export type HazardCoverage =
  | { state: 'complete' }
  /** /data-sources still loading or failed: we can't tell, so we never say "none". */
  | { state: 'unchecked' }
  | { state: 'partial'; gaps: { name: string; status: DataSource['status'] }[] };

export function hazardCoverage(sources: DataSource[] | undefined): HazardCoverage {
  if (!sources) return { state: 'unchecked' };
  const gaps = HAZARD_SOURCE_IDS.map((id) => {
    const s = sources.find((x) => x.id === id);
    return s ? { name: s.name, status: s.status } : { name: id, status: 'disabled' as const };
  }).filter((g) => g.status !== 'active');
  return gaps.length ? { state: 'partial', gaps } : { state: 'complete' };
}

export function useHazardCoverage(): HazardCoverage {
  const q = useDataSources();
  return hazardCoverage(q.isSuccess ? q.data : undefined);
}
