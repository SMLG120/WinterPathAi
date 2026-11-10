"""Detect precise coordinates in log text (privacy rule: never log > 3 decimal places).

Flags numbers with >= 4 decimals whose value lies in the Montréal region
(lon -80..-70, lat 40..50), whether they appear bare, quoted, or URL-encoded. The window
is regional on purpose: durations like `12.3456` ms must not cause false positives, while any
coordinate the pilot could plausibly produce is caught.
"""

from __future__ import annotations

import re
from urllib.parse import unquote_plus

_NUM = re.compile(r"(?<![\w.])-?\d{1,3}\.\d{4,}(?![\d])")


def precise_coordinates(text: str) -> list[str]:
    hits: list[str] = []
    for candidate in (text, unquote_plus(text)):
        for m in _NUM.finditer(candidate):
            v = float(m.group())
            if -80.0 <= v <= -70.0 or 40.0 <= v <= 50.0:
                hits.append(m.group())
    return sorted(set(hits))
