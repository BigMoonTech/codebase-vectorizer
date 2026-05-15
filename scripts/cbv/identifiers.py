from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable, Set

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+[0-9]*|[0-9]+")


def extract_identifiers(text: str) -> Set[str]:
    return set(_iter_symbols(text))


def trigrams(symbol: str) -> set[str]:
    if not symbol.strip():
        return set()
    s = f"  {symbol.lower()} "
    if len(s) < 3:
        return set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def symbol_trigram_rows(chunk_id: int, content: str) -> list[tuple[str, int, str, int]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for symbol in _iter_symbols(content):
        for gram in trigrams(symbol):
            counts[(gram, symbol)] += 1
    return [
        (gram, chunk_id, symbol, occurrences)
        for (gram, symbol), occurrences in sorted(counts.items())
    ]


def _iter_symbols(text: str) -> Iterable[str]:
    for match in IDENT_RE.finditer(text):
        yield from _symbols_for_token(match.group(0))


def _symbols_for_token(token: str) -> set[str]:
    symbols = {token} if _is_symbol_candidate(token) else set()
    for part in token.split("_"):
        if _is_symbol_candidate(part):
            symbols.add(part)
        for camel in CAMEL_RE.findall(part):
            if _is_symbol_candidate(camel):
                symbols.add(camel)
    return symbols


def _is_symbol_candidate(symbol: str) -> bool:
    return len(symbol) >= 2 and bool(symbol.strip("_"))
