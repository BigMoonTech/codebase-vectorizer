"""Tiny SQLite wrapper for the fixture."""
from __future__ import annotations

import sqlite3
from typing import Iterable, Optional, Tuple


def open_conn(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path)


def fetch_one(sql: str, params: Iterable = ()) -> Optional[Tuple]:
    conn = open_conn(":memory:")
    return conn.execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable = ()) -> None:
    conn = open_conn(":memory:")
    with conn:
        conn.execute(sql, tuple(params))
