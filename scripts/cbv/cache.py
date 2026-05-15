from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np


_CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS embedding_cache ("
    "content_hash TEXT NOT NULL, "
    "embedding BLOB NOT NULL, "
    "model_id TEXT NOT NULL, "
    "created_at INTEGER NOT NULL, "
    "PRIMARY KEY (content_hash, model_id))"
)


def open_cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE_SQL)
    if _primary_key_columns(conn) == ["content_hash", "model_id"]:
        return

    with conn:
        conn.execute("ALTER TABLE embedding_cache RENAME TO embedding_cache_old")
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(
            "INSERT OR REPLACE INTO embedding_cache "
            "(content_hash, embedding, model_id, created_at) "
            "SELECT content_hash, embedding, model_id, created_at "
            "FROM embedding_cache_old "
            "WHERE content_hash IS NOT NULL AND model_id IS NOT NULL"
        )
        conn.execute("DROP TABLE embedding_cache_old")


def _primary_key_columns(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("PRAGMA table_info(embedding_cache)").fetchall()
    return [
        row[1]
        for row in sorted(
            (row for row in rows if row[5]),
            key=lambda row: row[5],
        )
    ]


def get(
    conn: sqlite3.Connection,
    content_hash: str,
    model_id: str,
) -> np.ndarray | None:
    row = conn.execute(
        "SELECT embedding FROM embedding_cache WHERE content_hash = ? AND model_id = ?",
        (content_hash, model_id),
    ).fetchone()
    if row is None:
        return None
    return np.frombuffer(row[0], dtype=np.int8).copy()


def put(
    conn: sqlite3.Connection,
    content_hash: str,
    model_id: str,
    embedding: np.ndarray,
) -> None:
    conn.execute(
        "INSERT INTO embedding_cache (content_hash, embedding, model_id, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(content_hash, model_id) DO UPDATE SET "
        "embedding = excluded.embedding, created_at = excluded.created_at",
        (content_hash, embedding.astype("int8").tobytes(), model_id, int(time.time())),
    )
