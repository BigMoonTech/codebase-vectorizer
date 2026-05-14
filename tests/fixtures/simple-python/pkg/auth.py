"""Authentication helpers."""
from __future__ import annotations

from pkg.db import fetch_one
from pkg.utils import constant_time_compare


def authenticate_user(username: str, password_hash: str) -> bool:
    """Return True iff the credentials match a row in the users table."""
    row = fetch_one("SELECT password_hash FROM users WHERE username = ?",
                    (username,))
    if row is None:
        return False
    return constant_time_compare(row[0], password_hash)


def issue_session_token(user_id: int) -> str:
    """Create an opaque session token for the given user id."""
    import secrets
    return secrets.token_urlsafe(32)
