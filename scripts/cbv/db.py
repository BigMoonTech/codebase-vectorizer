"""Database access for codebase-vectorizer v1.0.

Every DDL string in SCHEMA matches the authoritative spec at
specs/2026-05-14-codebase-vectorizer-v1.0-design.md § "Storage schema".

This module:
  - opens a sqlite3 connection with the sqlite-vec extension loaded,
  - creates the full v1.0 schema (all ten tables) in one transaction,
  - exposes read/write helpers for the meta key/value store,
  - exposes assert_schema_v1() for the spec-mandated legacy detector.

Slice 1 only WRITES to chunks / chunks_fts / vec_chunks / meta. The rest
of the tables exist for later slices; they remain empty until then.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

import sqlite_vec


class LegacySchemaError(RuntimeError):
    """Raised when an index's meta.schema_version is missing or not '1.0'.

    Spec § "Detected legacy index handling".
    """


SCHEMA_VERSION = "1.0"


# --- DDL ---------------------------------------------------------------------

DDL_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    language TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT,
    ast_path TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count INTEGER NOT NULL
);
"""

DDL_CHUNKS_IDX = """
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind);
"""

# FTS5 with porter stemmer + unicode61 with code-friendly separator chars.
# Tokenize option is SQL-quoted; doubled single quotes inside escape one quote.
DDL_CHUNKS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content=chunks,
    content_rowid=id,
    tokenize='porter unicode61 separators ''.,;:()[]{}<>!?'''
);
"""

# Sync triggers — standard FTS5 external-content pattern.
DDL_CHUNKS_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

DDL_SYMBOL_TRIGRAMS = """
CREATE TABLE IF NOT EXISTS symbol_trigrams (
    trigram TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (trigram, chunk_id, symbol),
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_trigrams ON symbol_trigrams(trigram);
CREATE INDEX IF NOT EXISTS idx_symbols ON symbol_trigrams(symbol);
"""

# sqlite-vec ANN index. INT8 quantized, cosine distance. Dimension 1536
# matches jina-code-embeddings-1.5b. Slice 1's only embedder; alternate
# embedders ship in later slices via separately-typed tables.
DDL_VEC_CHUNKS = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding INT8[1536] distance_metric=cosine
);
"""

DDL_NODES = """
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT,
    parent_id INTEGER,
    chunk_id INTEGER,
    pagerank REAL DEFAULT 0.0,
    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_short ON nodes(short_name);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_chunk ON nodes(chunk_id);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_pr ON nodes(pagerank DESC);
"""

DDL_EDGES = """
CREATE TABLE IF NOT EXISTS edges (
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    kind TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    PRIMARY KEY (src, dst, kind),
    FOREIGN KEY (src) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (dst) REFERENCES nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, kind);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, kind);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
"""

DDL_CLUSTERS = """
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    summary TEXT NOT NULL,
    centroid BLOB NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunk_clusters (
    chunk_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    membership REAL NOT NULL,
    PRIMARY KEY (chunk_id, cluster_id),
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cc_cluster ON chunk_clusters(cluster_id);
"""

DDL_MERKLE = """
CREATE TABLE IF NOT EXISTS merkle_files (
    file_path TEXT PRIMARY KEY,
    blob_sha TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    last_indexed_at INTEGER NOT NULL
);
"""

DDL_META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ALL_DDL = [
    DDL_CHUNKS, DDL_CHUNKS_IDX,
    DDL_CHUNKS_FTS, DDL_CHUNKS_FTS_TRIGGERS,
    DDL_SYMBOL_TRIGRAMS,
    DDL_VEC_CHUNKS,
    DDL_NODES, DDL_EDGES,
    DDL_CLUSTERS,
    DDL_MERKLE,
    DDL_META,
]


# --- API ---------------------------------------------------------------------

def open_db(path: Path) -> sqlite3.Connection:
    """Open a sqlite3 connection with sqlite-vec loaded.

    The caller is responsible for closing the connection.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create every v1.0 table (idempotent)."""
    with conn:
        for stmt in ALL_DDL:
            conn.executescript(stmt)


def read_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def assert_schema_v1(conn: sqlite3.Connection) -> None:
    """Raise LegacySchemaError if the index isn't a v1.0 index.

    Two failure modes are treated identically:
      (a) the meta table doesn't exist (very old indexes)
      (b) meta.schema_version != "1.0"
    """
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    version = read_meta(conn, "schema_version") if has_meta else None
    if version != SCHEMA_VERSION:
        raise LegacySchemaError(
            f"Detected an older codebase-vectorizer index "
            f"(schema_version={version!r}, expected {SCHEMA_VERSION!r}). "
            f"The current schema requires re-indexing — different embedder "
            f"dimensions and additional tables. Run "
            f"`run.sh vectorize <repo>` (or run.ps1 on Windows) to upgrade."
        )


def insert_embedding(
    conn: sqlite3.Connection, chunk_id: int, int8_vec
) -> None:
    """Insert a 1536-dim INT8 embedding into vec_chunks for chunk_id.

    `int8_vec` is a numpy ndarray (or any iterable) of int8 values whose
    length matches the column dimension (1536 for v1.0).

    sqlite-vec 0.1.x interprets raw bytes / `sqlite_vec.serialize_int8()`
    output as float32 for INT8 columns, so we use the `vec_int8(?)` SQL
    function with a JSON array string. This is the only insertion path
    that works reliably across sqlite-vec 0.1.6 - 0.1.9.
    """
    try:
        values = int8_vec.tolist()
    except AttributeError:
        values = list(int8_vec)
    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, vec_int8(?))",
        (chunk_id, json.dumps(values)),
    )


def vec_int8_param(int8_vec) -> str:
    """Return the JSON string form of an int8 vector for use with `vec_int8(?)`.

    Use in queries like:
        WHERE embedding MATCH vec_int8(?) AND k = ?
    """
    try:
        values = int8_vec.tolist()
    except AttributeError:
        values = list(int8_vec)
    return json.dumps(values)
