"""Tests for cbv.db — schema creation, meta helpers, legacy detection."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

# Whether the venv exports sqlite-vec for tests. Some unit tests run outside
# the plugin venv during development; skip those that need the extension.
try:
    import sqlite_vec  # noqa: F401
    HAVE_VEC = True
except ImportError:
    HAVE_VEC = False

from cbv import db  # noqa: E402

REQUIRED_TABLES = {
    "chunks", "chunks_fts", "symbol_trigrams",
    "vec_chunks",
    "nodes", "edges",
    "clusters", "chunk_clusters",
    "merkle_files",
    "meta",
}


@pytest.fixture
def conn(tmp_path):
    p = tmp_path / "test.sqlite"
    c = db.open_db(p)
    db.init_schema(c)
    yield c
    c.close()


def test_open_db_loads_sqlite_vec():
    """open_db enables the sqlite-vec extension."""
    if not HAVE_VEC:
        pytest.skip("sqlite-vec not installed in this environment")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        path = Path(f.name)
    try:
        c = db.open_db(path)
        ver = c.execute("SELECT vec_version()").fetchone()[0]
        assert isinstance(ver, str) and len(ver) > 0
        c.close()
    finally:
        path.unlink(missing_ok=True)


def test_init_schema_creates_every_v1_table(conn):
    if not HAVE_VEC:
        pytest.skip("sqlite-vec not installed")
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type IN ('table','virtual') OR name LIKE '%_fts'"
    ).fetchall()
    names = {r[0] for r in rows}
    missing = REQUIRED_TABLES - names
    assert not missing, f"missing tables: {missing}"


def test_chunks_columns_exact(conn):
    if not HAVE_VEC:
        pytest.skip()
    rows = conn.execute("PRAGMA table_info(chunks)").fetchall()
    names = [r[1] for r in rows]
    assert names == [
        "id", "file_path", "language", "kind", "name", "ast_path",
        "start_line", "end_line", "start_byte", "end_byte",
        "content", "content_hash", "token_count",
    ]


def test_write_and_read_meta(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "schema_version", "1.0")
    db.write_meta(conn, "total_chunks", "0")
    assert db.read_meta(conn, "schema_version") == "1.0"
    assert db.read_meta(conn, "total_chunks") == "0"
    assert db.read_meta(conn, "absent") is None


def test_write_meta_overwrites(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "total_chunks", "0")
    db.write_meta(conn, "total_chunks", "42")
    assert db.read_meta(conn, "total_chunks") == "42"


def test_assert_schema_v1_accepts_matching(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "schema_version", "1.0")
    db.assert_schema_v1(conn)  # no raise


def test_assert_schema_v1_raises_on_mismatch(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "schema_version", "0.9")
    with pytest.raises(db.LegacySchemaError) as exc:
        db.assert_schema_v1(conn)
    assert "older codebase-vectorizer index" in str(exc.value)


def test_assert_schema_v1_raises_when_meta_missing(tmp_path):
    """A pre-meta-table legacy DB (v0.3.0) raises the same error."""
    if not HAVE_VEC:
        pytest.skip()
    legacy = tmp_path / "legacy.sqlite"
    raw = sqlite3.connect(legacy)
    raw.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    raw.commit()
    raw.close()
    c = db.open_db(legacy)
    with pytest.raises(db.LegacySchemaError):
        db.assert_schema_v1(c)


def test_chunks_fts_sync_triggers(conn):
    """Inserting a chunk should be findable via FTS5 immediately."""
    if not HAVE_VEC:
        pytest.skip()
    conn.execute(
        "INSERT INTO chunks (file_path, language, kind, start_line, end_line, "
        "start_byte, end_byte, content, content_hash, token_count) "
        "VALUES ('x.py','python','window',1,5,0,42,'hello unique_token_xyz',"
        "'h0','4')"
    )
    conn.commit()
    rows = conn.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'unique_token_xyz'"
    ).fetchall()
    assert len(rows) == 1


def test_vec_chunks_insert_int8(conn):
    """vec_chunks accepts INT8 1536-dim payloads via vec_int8()."""
    if not HAVE_VEC:
        pytest.skip()
    import json
    import numpy as np
    conn.execute(
        "INSERT INTO chunks (file_path, language, kind, start_line, end_line, "
        "start_byte, end_byte, content, content_hash, token_count) "
        "VALUES ('y.py','python','window',1,2,0,1,'x','h1','1')"
    )
    chunk_id = conn.execute("SELECT id FROM chunks WHERE file_path='y.py'").fetchone()[0]
    # sqlite-vec INT8 columns require the vec_int8() SQL function for insertion;
    # raw bytes are interpreted as float32 by sqlite-vec v0.1.x.
    emb_json = json.dumps(np.full(1536, 5, dtype=np.int8).tolist())
    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, vec_int8(?))",
        (chunk_id, emb_json),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT chunk_id FROM vec_chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchall()
    assert rows == [(chunk_id,)]


def test_insert_embedding_helper(conn):
    """db.insert_embedding centralises the vec_int8 JSON dance."""
    if not HAVE_VEC:
        pytest.skip()
    import numpy as np
    conn.execute(
        "INSERT INTO chunks (file_path, language, kind, start_line, end_line, "
        "start_byte, end_byte, content, content_hash, token_count) "
        "VALUES ('z.py','python','window',1,1,0,1,'x','h2','1')"
    )
    chunk_id = conn.execute("SELECT id FROM chunks WHERE file_path='z.py'").fetchone()[0]
    arr = np.full(1536, 7, dtype=np.int8)
    db.insert_embedding(conn, chunk_id, arr)
    conn.commit()
    rows = conn.execute(
        "SELECT chunk_id FROM vec_chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchall()
    assert rows == [(chunk_id,)]


def test_vec_int8_param_returns_json_for_match_queries(conn):
    """db.vec_int8_param returns the JSON string used by `WHERE e MATCH vec_int8(?)`."""
    if not HAVE_VEC:
        pytest.skip()
    import numpy as np
    # Two rows with vectors that point in clearly different directions.
    # Cosine distance only cares about direction, so we need non-parallel
    # vectors to validate ordering.
    parallel = np.full(1536, 3, dtype=np.int8)
    alternating = np.tile(np.array([3, -3], dtype=np.int8), 768)
    for i, vec in enumerate([parallel, alternating], start=1):
        conn.execute(
            "INSERT INTO chunks (file_path, language, kind, start_line, end_line, "
            "start_byte, end_byte, content, content_hash, token_count) "
            "VALUES (?, 'python','window',1,1,0,1,'x',?,'1')",
            (f"f{i}.py", f"h{i}"),
        )
        cid = conn.execute(
            "SELECT id FROM chunks WHERE file_path = ?", (f"f{i}.py",)
        ).fetchone()[0]
        db.insert_embedding(conn, cid, vec)
    conn.commit()

    qparam = db.vec_int8_param(parallel)
    assert isinstance(qparam, str)
    assert qparam.startswith("[3, ") or qparam.startswith("[3,")
    rows = conn.execute(
        "SELECT chunk_id FROM vec_chunks "
        "WHERE embedding MATCH vec_int8(?) AND k = ? ORDER BY distance",
        (qparam, 2),
    ).fetchall()
    # The parallel row (chunk 1) should rank before the alternating one (chunk 2).
    assert rows[0][0] == 1
    assert rows[1][0] == 2
