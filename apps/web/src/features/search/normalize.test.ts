import { describe, expect, it } from 'vitest';
import { fold, shardKey, tokens } from './normalize';
import vectors from './normalize.vectors.json';

describe('normalize (shared vectors with the Python index builder)', () => {
  it.each(vectors)('$in', (v) => {
    expect(fold(v.in)).toBe(v.fold);
    expect(tokens(v.in)).toEqual(v.tokens);
  });
  it('shard key = first two characters', () => {
    expect(shardKey('maisonneuve')).toBe('ma');
    expect(shardKey('1')).toBe('1');
  });
});
