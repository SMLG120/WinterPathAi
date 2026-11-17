import { describe, expect, it } from 'vitest';
import { fetchAllSegments, SEGMENT_MAX_PAGES } from './queries';
import type { SegmentCollection } from './types';

const page = (ids: number[], next: string | null) =>
  ({ type: 'FeatureCollection', features: ids.map((id) => ({ id })), next_cursor: next }) as unknown as SegmentCollection;

describe('fetchAllSegments (code review, PR #1)', () => {
  it('follows next_cursor and merges pages in order', async () => {
    const seen: (string | undefined)[] = [];
    const pages: Record<string, SegmentCollection> = { '': page([1, 2], 'c1'), c1: page([3], 'c2'), c2: page([4], null) };
    const out = await fetchAllSegments(async (c) => (seen.push(c), pages[c ?? '']!));
    expect(seen).toEqual([undefined, 'c1', 'c2']);
    expect(out.features.map((f) => (f as unknown as { id: number }).id)).toEqual([1, 2, 3, 4]);
    expect(out.next_cursor).toBeNull();
  });

  it('stops at the page cap and leaves next_cursor set (truncated)', async () => {
    let n = 0;
    const out = await fetchAllSegments(async () => page([++n], `c${n}`));
    expect(n).toBe(SEGMENT_MAX_PAGES);
    expect(out.features).toHaveLength(SEGMENT_MAX_PAGES);
    expect(out.next_cursor).not.toBeNull();
  });
});
