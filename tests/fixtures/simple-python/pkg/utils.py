"""Small helpers."""
from __future__ import annotations

import hmac


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to avoid timing attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def slugify(s: str) -> str:
    """Lowercase, replace spaces with dashes, drop non-alnum."""
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")
