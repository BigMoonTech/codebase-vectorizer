from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import cache  # noqa: E402


def test_open_cache_creates_parent_and_table(tmp_path):
    cache_path = tmp_path / "state" / "embedding_cache.sqlite"

    conn = cache.open_cache(cache_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'embedding_cache'"
        ).fetchone()
    finally:
        conn.close()

    assert cache_path.exists()
    assert row == ("embedding_cache",)


def test_put_and_get_round_trip_int8_embedding(tmp_path):
    conn = cache.open_cache(tmp_path / "embedding_cache.sqlite")
    embedding = np.array([-128, -1, 0, 1, 127], dtype=np.int8)

    try:
        cache.put(conn, "hash-a", "model-a", embedding)
        conn.commit()
        cached = cache.get(conn, "hash-a", "model-a")
    finally:
        conn.close()

    assert cached is not None
    assert cached.dtype == np.int8
    np.testing.assert_array_equal(cached, embedding)


def test_get_returns_none_for_different_model(tmp_path):
    conn = cache.open_cache(tmp_path / "embedding_cache.sqlite")
    try:
        cache.put(conn, "hash-a", "model-a", np.array([1, 2, 3], dtype=np.int8))
        conn.commit()

        assert cache.get(conn, "hash-a", "model-b") is None
    finally:
        conn.close()


def test_put_updates_existing_content_hash(tmp_path):
    conn = cache.open_cache(tmp_path / "embedding_cache.sqlite")
    try:
        cache.put(conn, "hash-a", "model-a", np.array([1, 2, 3], dtype=np.int8))
        cache.put(conn, "hash-a", "model-b", np.array([4, 5, 6], dtype=np.int8))
        conn.commit()

        assert cache.get(conn, "hash-a", "model-a") is None
        np.testing.assert_array_equal(
            cache.get(conn, "hash-a", "model-b"),
            np.array([4, 5, 6], dtype=np.int8),
        )
        rows = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
    finally:
        conn.close()

    assert rows == 1


def test_open_cache_returns_sqlite_connection(tmp_path):
    conn = cache.open_cache(tmp_path / "embedding_cache.sqlite")
    try:
        assert isinstance(conn, sqlite3.Connection)
    finally:
        conn.close()
