import { canonToken, DIRECTIONS, fold, GENERICS, tokens } from './normalize';

export type ParsedQuery = {
  /** Civic number as typed, lower-case without spaces ("1455", "1455a"), or null. */
  civic: string | null;
  /** Tokens every result must match (prefix match). */
  required: string[];
  /** Street-type tokens, canonical ("boulevard"): a bonus when they match, never required. */
  generics: string[];
  /** Direction o/e/n/s when typed. */
  direction: 'o' | 'e' | 'n' | 's' | null;
  /** Folded locality (municipality) filter, e.g. "laval", "st lambert", or null. */
  locality: string | null;
};

// "1455", "1455a", "1455-1457" (first number kept). "2e" is an ordinal (2nd), not civic 2E.
const CIVIC = /^(\d{1,6})(?:-\d{1,6})?([a-df-z])?$/;

/** Folded municipality names that the index knows (manifest.municipalities), to detect a locality. */
export type LocalityMatcher = (folded: string) => boolean;

/**
 * Split a free-text query into civic number, required name tokens, optional street type,
 * direction and locality.
 * - A locality is the text after the last comma, or trailing words naming a known municipality
 *   when other name tokens remain ("1455 de maisonneuve montreal").
 * - "St" as the LAST name token after another name token is read as "Street" (Peel St);
 *   anywhere else it is "Saint".
 * - If only street-type words remain ("avenue du parc"), they become required, except the first.
 */
export function parseQuery(input: string, isLocality: LocalityMatcher = () => false): ParsedQuery {
  let text = input;
  let locality: string | null = null;
  const comma = text.lastIndexOf(',');
  if (comma >= 0) {
    const loc = fold(text.slice(comma + 1));
    text = text.slice(0, comma);
    if (loc) locality = tokens(loc).join(' ');
  }
  const raw = fold(text).split(' ').filter(Boolean);

  let civic: string | null = null;
  const firstCivic = raw[0] ? CIVIC.exec(raw[0]) : null;
  if (firstCivic && raw.length >= 1) {
    civic = (firstCivic[1]! + (firstCivic[2] ?? '')).toLowerCase();
    raw.shift();
  } else if (raw.length >= 2 && /^\d{1,6}$/.test(raw[raw.length - 1]!)) {
    // "rue peel 1455"
    civic = raw.pop()!;
  }

  // Canonical tokens with their raw spelling (for generic / direction detection).
  let toks = raw.flatMap((r) => {
    const c = canonToken(r);
    return c === null ? [] : [{ raw: r, c }];
  });

  if (!locality && isLocality) {
    for (let n = Math.min(3, toks.length - 1); n >= 1; n--) {
      const tail = toks.slice(-n).map((t) => t.c).join(' ');
      const head = toks.slice(0, -n);
      if (isLocality(tail) && head.some((t) => !(t.raw in GENERICS))) {
        locality = tail;
        toks = head;
        break;
      }
    }
  }

  let direction: ParsedQuery['direction'] = null;
  const generics: string[] = [];
  const required: string[] = [];
  const isDirWord = (r: string) => r.length > 1 && r in DIRECTIONS;
  toks.forEach((t, i) => {
    const last = i === toks.length - 1;
    // Direction: a full word anywhere after a name token, or a single letter that is not last
    // (a last single letter may still be the start of a word being typed: it is kept optional).
    const dirLetter = t.raw.length === 1 && t.raw in DIRECTIONS;
    if (i > 0 && (isDirWord(t.raw) || (dirLetter && !(last && required.length === 0)))) {
      direction = DIRECTIONS[t.raw]!; // soft: ranking bonus/penalty only
      return;
    }
    if (t.raw === 'st' && i > 0 && required.length > 0 && toks.slice(i + 1).every((x) => x.raw in DIRECTIONS)) {
      generics.push('rue'); // "Peel St", "Ste-Catherine St W"
      return;
    }
    if (t.raw in GENERICS) {
      generics.push(GENERICS[t.raw]!);
      return;
    }
    required.push(t.c);
  });
  if (required.length === 0 && generics.length > 1) {
    // "avenue du parc", "rue cote": the type is first, the rest are names.
    const words = toks.filter((t) => t.raw in GENERICS).map((t) => t.c);
    required.push(...words.slice(1));
    generics.splice(1);
  } else if (required.length === 0 && generics.length === 1 && toks.length === 1) {
    required.push(toks[0]!.c); // "parc", "cote": the user may be typing a name
    generics.length = 0;
  }
  return { civic, required, generics, direction, locality };
}
