import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { loadMotionFeatures, useMotionReady } from './motionReady';

describe('motionReady', () => {
  it('is false until the async animation features have loaded, then true', async () => {
    const { result } = renderHook(() => useMotionReady());
    expect(result.current).toBe(false);
    let features: unknown;
    await act(async () => {
      features = await loadMotionFeatures();
    });
    expect(features).toBeTruthy();
    expect(result.current).toBe(true);
  });
});
