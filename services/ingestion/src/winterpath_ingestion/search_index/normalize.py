"""Text normalisation shared by the index builder and the web client.

The browser implementation (`apps/web/src/features/search/normalize.ts`) must produce the same
tokens. Both test suites run the shared vectors in
`apps/web/src/features/search/normalize.vectors.json`.

Rules (format `winterpath-search/1`):
1. Unicode NFD, drop combining marks, lower-case; oe/ae ligatures and sharp s expanded.
2. Every character outside `[a-z0-9]` becomes a separator (hyphens, apostrophes, periods...).
3. Token canonicalisation:
   - `saint`, `sainte`, `ste` -> `st` (`st` itself stays `st`);
   - ordinals: `1re`, `1er`, `1ere`, `2e`, `2eme`, `3ieme`, `2nd`, `3rd`, `4th`, `1st` -> digits;
     French ordinal words `premier`..`dixieme` -> digits;
   - articles `de du des la le les l d au aux of the` are dropped.
Generic street types and directions are NOT removed here: the query parser decides (see
`apps/web/src/features/search/query.ts`); the index stores them in separate fields.
"""

from __future__ import annotations

import re
import unicodedata

KEY_LEN = 2

ARTICLES = frozenset({"de", "du", "des", "la", "le", "les", "l", "d", "au", "aux", "of", "the"})
SAINTS = frozenset({"saint", "sainte", "ste", "st"})
ORDINAL_WORDS = {
    "premier": "1",
    "premiere": "1",
    "deuxieme": "2",
    "troisieme": "3",
    "quatrieme": "4",
    "cinquieme": "5",
    "sixieme": "6",
    "septieme": "7",
    "huitieme": "8",
    "neuvieme": "9",
    "dixieme": "10",
}
_ORDINAL = re.compile(r"^(\d+)(?:e|er|re|ere|eme|ieme|nd|rd|th|st)$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Canonical generic (street type) for each spelling, used for the RQA `generique_odonyme`
# and for query tokens.
GENERICS = {
    "rue": "rue",
    "street": "rue",
    "boulevard": "boulevard",
    "boul": "boulevard",
    "blvd": "boulevard",
    "bd": "boulevard",
    "avenue": "avenue",
    "av": "avenue",
    "ave": "avenue",
    "chemin": "chemin",
    "ch": "chemin",
    "road": "chemin",
    "rd": "chemin",
    "place": "place",
    "pl": "place",
    "cote": "cote",
    "montee": "montee",
    "rang": "rang",
    "route": "route",
    "autoroute": "autoroute",
    "terrasse": "terrasse",
    "croissant": "croissant",
    "crescent": "croissant",
    "cres": "croissant",
    "allee": "allee",
    "square": "square",
    "carre": "carre",
    "promenade": "promenade",
    "impasse": "impasse",
    "cour": "cour",
    "court": "cour",
    "voie": "voie",
    "ruelle": "ruelle",
    "passage": "passage",
    "parc": "parc",
    "drive": "drive",
    "lane": "lane",
    "circle": "cercle",
    "cercle": "cercle",
    "esplanade": "esplanade",
    "quai": "quai",
    "sentier": "sentier",
}

DIRECTIONS = {
    "ouest": "o",
    "o": "o",
    "west": "o",
    "w": "o",
    "est": "e",
    "e": "e",
    "east": "e",
    "nord": "n",
    "n": "n",
    "north": "n",
    "sud": "s",
    "s": "s",
    "south": "s",
}


def fold(text: str) -> str:
    """Accent- and case-folded text with separators collapsed to single spaces."""
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("œ", "oe").replace("æ", "ae").replace("ß", "ss")
    return _NON_ALNUM.sub(" ", t).strip()


def canon_token(tok: str) -> str | None:
    """Canonical form of one folded token; None when the token is an article."""
    if tok in ARTICLES:
        return None
    if tok in SAINTS:
        return "st"
    if tok in ORDINAL_WORDS:
        return ORDINAL_WORDS[tok]
    m = _ORDINAL.match(tok)
    if m:
        return str(int(m.group(1)))
    return tok


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in fold(text).split():
        c = canon_token(raw)
        if c is not None:
            out.append(c)
    return out


def generic(text: str) -> str:
    """Canonical generic for an RQA `generique_odonyme` value ('' when unknown/empty)."""
    t = fold(text).replace(" ", "")
    return GENERICS.get(t, t)


def direction(text: str) -> str:
    """'o' | 'e' | 'n' | 's' | '' for an RQA `point_cardinal_odonyme` value."""
    return DIRECTIONS.get(fold(text), "")


def shard_key(token: str) -> str:
    return token[:KEY_LEN]
