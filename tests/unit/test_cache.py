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


def test_same_content_hash_can_store_separate_model_embeddings(tmp_path):
    conn = cache.open_cache(tmp_path / "embedding_cache.sqlite")
    model_a_embedding = np.array([1, 2, 3], dtype=np.int8)
    model_b_embedding = np.array([4, 5, 6], dtype=np.int8)

    try:
        cache.put(conn, "hash-a", "model-a", model_a_embedding)
        cache.put(conn, "hash-a", "model-b", model_b_embedding)
        conn.commit()

        np.testing.assert_array_equal(
            cache.get(conn, "hash-a", "model-a"),
            model_a_embedding,
        )
        np.testing.assert_array_equal(
            cache.get(conn, "hash-a", "model-b"),
            model_b_embedding,
        )
        rows = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
    finally:
        conn.close()

    assert rows == 2


def test_open_cache_migrates_stale_content_hash_primary_key_schema(tmp_path):
    cache_path = tmp_path / "embedding_cache.sqlite"
    stale_conn = sqlite3.connect(cache_path)
    try:
        stale_conn.execute(
            "CREATE TABLE embedding_cache ("
            "content_hash TEXT PRIMARY KEY, "
            "embedding BLOB NOT NULL, "
            "model_id TEXT NOT NULL, "
            "created_at INTEGER NOT NULL)"
        )
        stale_conn.execute(
            "INSERT INTO embedding_cache "
            "(content_hash, embedding, model_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            ("hash-a", np.array([1, 2, 3], dtype=np.int8).tobytes(), "model-a", 1),
        )
        stale_conn.commit()
    finally:
        stale_conn.close()

    conn = cache.open_cache(cache_path)
    model_b_embedding = np.array([4, 5, 6], dtype=np.int8)
    try:
        cache.put(conn, "hash-a", "model-b", model_b_embedding)
        conn.commit()

        np.testing.assert_array_equal(
            cache.get(conn, "hash-a", "model-a"),
            np.array([1, 2, 3], dtype=np.int8),
        )
        np.testing.assert_array_equal(
            cache.get(conn, "hash-a", "model-b"),
            model_b_embedding,
        )
        rows = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
    finally:
        conn.close()

    assert rows == 2


def test_put_updates_existing_content_hash_and_model(tmp_path):
    conn = cache.open_cache(tmp_path / "embedding_cache.sqlite")
    try:
        cache.put(conn, "hash-a", "model-a", np.array([1, 2, 3], dtype=np.int8))
        cache.put(conn, "hash-a", "model-a", np.array([4, 5, 6], dtype=np.int8))
        conn.commit()

        np.testing.assert_array_equal(
            cache.get(conn, "hash-a", "model-a"),
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
