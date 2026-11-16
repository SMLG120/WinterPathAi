/**
 * Text normalisation for place search — format `winterpath-search/1`.
 *
 * MUST stay identical to the index builder
 * (services/ingestion/src/winterpath_ingestion/search_index/normalize.py). Both test suites run
 * the shared vectors in ./normalize.vectors.json.
 */

export const KEY_LEN = 2;

const ARTICLES = new Set(['de', 'du', 'des', 'la', 'le', 'les', 'l', 'd', 'au', 'aux', 'of', 'the']);
const SAINTS = new Set(['saint', 'sainte', 'ste', 'st']);
const ORDINAL_WORDS: Record<string, string> = {
  premier: '1',
  premiere: '1',
  deuxieme: '2',
  troisieme: '3',
  quatrieme: '4',
  cinquieme: '5',
  sixieme: '6',
  septieme: '7',
  huitieme: '8',
  neuvieme: '9',
  dixieme: '10',
};
const ORDINAL = /^(\d+)(?:e|er|re|ere|eme|ieme|nd|rd|th|st)$/;

/** Spelling → canonical street type (generic). Same table as the builder. */
export const GENERICS: Record<string, string> = {
  rue: 'rue',
  street: 'rue',
  boulevard: 'boulevard',
  boul: 'boulevard',
  blvd: 'boulevard',
  bd: 'boulevard',
  avenue: 'avenue',
  av: 'avenue',
  ave: 'avenue',
  chemin: 'chemin',
  ch: 'chemin',
  road: 'chemin',
  rd: 'chemin',
  place: 'place',
  pl: 'place',
  cote: 'cote',
  montee: 'montee',
  rang: 'rang',
  route: 'route',
  autoroute: 'autoroute',
  terrasse: 'terrasse',
  croissant: 'croissant',
  crescent: 'croissant',
  cres: 'croissant',
  allee: 'allee',
  square: 'square',
  carre: 'carre',
  promenade: 'promenade',
  impasse: 'impasse',
  cour: 'cour',
  court: 'cour',
  voie: 'voie',
  ruelle: 'ruelle',
  passage: 'passage',
  parc: 'parc',
  drive: 'drive',
  lane: 'lane',
  circle: 'cercle',
  cercle: 'cercle',
  esplanade: 'esplanade',
  quai: 'quai',
  sentier: 'sentier',
};

export const DIRECTIONS: Record<string, 'o' | 'e' | 'n' | 's'> = {
  ouest: 'o',
  o: 'o',
  west: 'o',
  w: 'o',
  est: 'e',
  e: 'e',
  east: 'e',
  nord: 'n',
  n: 'n',
  north: 'n',
  sud: 's',
  s: 's',
  south: 's',
};

/** Accent- and case-folded text, separators collapsed to single spaces. */
export function fold(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replaceAll('œ', 'oe')
    .replaceAll('æ', 'ae')
    .replaceAll('ß', 'ss')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

/** Canonical form of one folded token; null for an article. */
export function canonToken(tok: string): string | null {
  if (ARTICLES.has(tok)) return null;
  if (SAINTS.has(tok)) return 'st';
  const w = ORDINAL_WORDS[tok];
  if (w) return w;
  const m = ORDINAL.exec(tok);
  if (m) return String(Number.parseInt(m[1]!, 10));
  return tok;
}

export function tokens(text: string): string[] {
  const out: string[] = [];
  for (const raw of fold(text).split(' ')) {
    if (!raw) continue;
    const c = canonToken(raw);
    if (c !== null) out.push(c);
  }
  return out;
}

export function shardKey(token: string): string {
  return token.slice(0, KEY_LEN);
}
