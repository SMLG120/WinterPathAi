import { describe, expect, it } from 'vitest';
import { parseQuery } from './query';

const munis = new Set(['montreal', 'laval', 'longueuil', 'brossard', 'st lambert']);
const pq = (q: string) => parseQuery(q, (s) => munis.has(s));

describe('parseQuery', () => {
  it('civic + abbreviated type + particle + direction', () => {
    expect(pq('1455 boul De Maisonneuve O')).toEqual({ civic: '1455', required: ['maisonneuve'], generics: ['boulevard'], direction: 'o', locality: null });
  });
  it('locality after a comma', () => {
    expect(pq('1555 boul Chomedey, Laval')).toMatchObject({ civic: '1555', required: ['chomedey'], locality: 'laval' });
    expect(pq('10 rue Victoria, Saint-Lambert')).toMatchObject({ locality: 'st lambert' });
  });
  it('trailing known municipality without a comma', () => {
    expect(pq('1455 de maisonneuve montreal')).toMatchObject({ required: ['maisonneuve'], locality: 'montreal' });
    // "rue Laval" is a street name: nothing else would be left.
    expect(pq('rue laval')).toMatchObject({ required: ['laval'], locality: null });
  });
  it('St: Saint in front, Street at the end', () => {
    expect(pq('1200 Ste-Catherine St W')).toMatchObject({ civic: '1200', required: ['st', 'catherine'], generics: ['rue'], direction: 'o' });
    expect(pq('Peel St')).toMatchObject({ required: ['peel'], generics: ['rue'] });
    expect(pq('rue St')).toMatchObject({ required: ['st'] });
  });
  it('ordinals: 1re avenue is a street, not civic 1', () => {
    expect(pq('5664 1re avenue')).toMatchObject({ civic: '5664', required: ['1'], generics: ['avenue'] });
    expect(pq('2e avenue')).toMatchObject({ civic: null, required: ['2'] });
    expect(pq('Première Avenue')).toMatchObject({ required: ['1'] });
  });
  it('civic with suffix or range; civic at the end', () => {
    expect(pq('1455A rue Peel').civic).toBe('1455a');
    expect(pq('1455-1457 rue Peel').civic).toBe('1455');
    expect(pq('rue Peel 1455')).toMatchObject({ civic: '1455', required: ['peel'] });
  });
  it('only street-type words: all but the first become required', () => {
    expect(pq('avenue du parc')).toMatchObject({ required: ['parc'], generics: ['avenue'] });
    expect(pq('parc')).toMatchObject({ required: ['parc'], generics: [] });
  });
  it('a last single letter after a type word is a name being typed, not a direction', () => {
    expect(pq('rue s')).toMatchObject({ required: ['s'], direction: null });
  });
});
