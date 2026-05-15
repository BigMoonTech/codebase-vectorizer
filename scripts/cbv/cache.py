from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np


def open_cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS embedding_cache ("
        "content_hash TEXT NOT NULL, "
        "embedding BLOB NOT NULL, "
        "model_id TEXT NOT NULL, "
        "created_at INTEGER NOT NULL, "
        "PRIMARY KEY (content_hash, model_id))"
    )
    return conn


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
