from __future__ import annotations

import re

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def route(query: str, forced: str = "auto") -> str:
    if forced in {"fast", "full"}:
        return forced
    q = query.strip()
    lowered = q.lower()
    if q.startswith("regex:"):
        return "fast"
    for prefix in ("find ", "where is "):
        if lowered.startswith(prefix) and IDENT.match(q[len(prefix):].strip()):
            return "fast"
    if IDENT.match(q):
        return "fast"
    if len(q.split()) < 4 and all(IDENT.match(part) for part in q.split()):
        return "fast"
    return "full"
