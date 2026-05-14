"""SQLite + sqlite-vec + FTS5 schema and helpers.

One database file per indexed repo. Three logical tables:

- `chunks`       : canonical record for each code chunk.
- `chunks_fts`   : FTS5 virtual table over content+name+file_path (BM25 search).
- `vec_chunks`   : sqlite-vec virtual table holding embedding vectors.

The vec_chunks rowid matches chunks.id, so we can join cleanly.
"""

from __future__ import annotations

import os
import sqlite3
import struct
from typing import Iterable, List, Optional, Sequence

import sqlite_vec


EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5


def open_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


def init_schema(conn: sqlite3.Connection, embedding_dim: int = EMBEDDING_DIM) -> None:
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path     TEXT    NOT NULL,
            language      TEXT    NOT NULL,
            kind          TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            start_line    INTEGER NOT NULL,
            end_line      INTEGER NOT NULL,
            content       TEXT    NOT NULL,
            content_hash  TEXT    NOT NULL
        );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_name ON chunks(name);")

    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            name,
            file_path,
            tokenize = 'unicode61 remove_diacritics 2'
        );
    """)

    cur.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            embedding FLOAT[{embedding_dim}]
        );
    """)

    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value;",
        (key, value),
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def reset_index(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM chunks;")
    cur.execute("DELETE FROM chunks_fts;")
    cur.execute("DELETE FROM vec_chunks;")
    cur.execute("DELETE FROM sqlite_sequence WHERE name='chunks';")
    conn.commit()


def insert_chunks(
    conn: sqlite3.Connection,
    rows: Sequence[dict],
    embeddings: Sequence[Sequence[float]],
) -> List[int]:
    if len(rows) != len(embeddings):
        raise ValueError("rows and embeddings must be the same length")

    cur = conn.cursor()
    cur.execute("BEGIN;")
    ids: List[int] = []
    try:
        for row, vec in zip(rows, embeddings):
            cur.execute(
                """
                INSERT INTO chunks(file_path, language, kind, name, start_line, end_line, content, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    row["file_path"],
                    row["language"],
                    row["kind"],
                    row["name"],
                    row["start_line"],
                    row["end_line"],
                    row["content"],
                    row["content_hash"],
                ),
            )
            chunk_id = cur.lastrowid
            ids.append(chunk_id)

            cur.execute(
                "INSERT INTO chunks_fts(rowid, content, name, file_path) VALUES (?, ?, ?, ?);",
                (chunk_id, row["content"], row["name"], row["file_path"]),
            )

            cur.execute(
                "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?);",
                (chunk_id, _pack_floats(vec)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return ids


def _pack_floats(vec: Sequence[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


# ---------------------------------------------------------------------------
# Search helpers used by query.py
# ---------------------------------------------------------------------------

def fts_search(conn: sqlite3.Connection, query: str, limit: int) -> List[tuple]:
    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        return []
    try:
        rows = conn.execute(
            """
            SELECT rowid, bm25(chunks_fts) AS score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?;
            """,
            (sanitized, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(int(r[0]), float(r[1])) for r in rows]


def vec_search(conn: sqlite3.Connection, embedding: Sequence[float], limit: int) -> List[tuple]:
    rows = conn.execute(
        """
        SELECT rowid, distance
        FROM vec_chunks
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance;
        """,
        (_pack_floats(embedding), limit),
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]


def get_chunk(conn: sqlite3.Connection, chunk_id: int) -> Optional[dict]:
    row = conn.execute(
        """
        SELECT id, file_path, language, kind, name, start_line, end_line, content
        FROM chunks
        WHERE id = ?;
        """,
        (chunk_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "file_path": row[1],
        "language": row[2],
        "kind": row[3],
        "name": row[4],
        "start_line": row[5],
        "end_line": row[6],
        "content": row[7],
    }


def _sanitize_fts_query(query: str) -> str:
    """Strip FTS5 special chars and quote tokens as literal terms."""
    bad_chars = '"()[]{}^*:'
    cleaned: List[str] = []
    for tok in query.split():
        t = "".join(ch for ch in tok if ch not in bad_chars)
        if not any(ch.isalnum() for ch in t):
            continue
        cleaned.append(f'"{t}"')
    return " OR ".join(cleaned)
