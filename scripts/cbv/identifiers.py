from __future__ import annotations

import re
from collections import defaultdict
from typing import Set

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+[0-9]*|[0-9]+")


def extract_identifiers(text: str) -> Set[str]:
    found: set[str] = set()
    for match in IDENT_RE.finditer(text):
        found.update(_symbols_for_token(match.group(0)))
    return found


def trigrams(symbol: str) -> set[str]:
    s = f"  {symbol.lower()} "
    if len(s) < 3:
        return set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def symbol_trigram_rows(chunk_id: int, content: str) -> list[tuple[str, int, str, int]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for match in IDENT_RE.finditer(content):
        for symbol in _symbols_for_token(match.group(0)):
            for gram in trigrams(symbol):
                counts[(gram, symbol)] += 1
    return [
        (gram, chunk_id, symbol, occurrences)
        for (gram, symbol), occurrences in sorted(counts.items())
    ]


def _symbols_for_token(token: str) -> set[str]:
    symbols = {token}
    for part in token.split("_"):
        if len(part) >= 2:
            symbols.add(part)
        for camel in CAMEL_RE.findall(part):
            if len(camel) >= 2:
                symbols.add(camel)
    return symbols
