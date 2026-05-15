from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
import numpy as np

from cbv import db, paths  # noqa: E402
from cbv.commands import vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def incremental_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    src = tmp_path / "incremental-src"
    src.mkdir()
    (src / "changed.py").write_text(
        "def changed():\n"
        "    return 'before'\n",
        encoding="utf-8",
    )
    (src / "removed.py").write_text(
        "def removed():\n"
        "    return 'removed-token'\n",
        encoding="utf-8",
    )
    (src / "zzz_stable.py").write_text(
        "def stable():\n"
        "    return 'stable-token'\n",
        encoding="utf-8",
    )
    return src


def _run_vectorize(src: Path, output_dir: Path, *, update: bool = False) -> None:
    ns = argparse.Namespace(
        source=str(src),
        output_dir=str(output_dir),
        max_file_mb=1.5,
        no_cache=False,
        update=update,
    )
    assert vec_cmd.run(ns) == 0


def _chunk_rows(conn):
    return conn.execute(
        "SELECT id, file_path, content FROM chunks ORDER BY file_path, id"
    ).fetchall()


def test_fresh_vectorize_populates_merkle_table_and_root(incremental_source, tmp_path):
    output_dir = tmp_path / "index"

    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        files = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT file_path, blob_sha, size_bytes FROM merkle_files"
            )
        }
        root = db.read_meta(conn, "merkle_root_sha")
    finally:
        conn.close()

    assert set(files) == {"changed.py", "removed.py", "zzz_stable.py"}
    assert all(len(sha) == 64 and size > 0 for sha, size in files.values())
    assert root is not None
    assert len(root) == 64
    assert root != ""


def test_update_only_rechunks_added_and_modified_files(incremental_source, tmp_path):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_rows = _chunk_rows(conn)
        stable_id = conn.execute(
            "SELECT id FROM chunks WHERE file_path = 'zzz_stable.py'"
        ).fetchone()[0]
        old_root = db.read_meta(conn, "merkle_root_sha")
    finally:
        conn.close()

    (incremental_source / "aaa_added.py").write_text(
        "def added():\n"
        "    return 'added-token'\n",
        encoding="utf-8",
    )
    (incremental_source / "changed.py").write_text(
        "def changed():\n"
        "    return 'after-token'\n",
        encoding="utf-8",
    )
    (incremental_source / "removed.py").unlink()

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_rows = _chunk_rows(conn)
        current_files = {
            row[0]
            for row in conn.execute("SELECT file_path FROM merkle_files")
        }
        new_root = db.read_meta(conn, "merkle_root_sha")
        stable_id_after = conn.execute(
            "SELECT id FROM chunks WHERE file_path = 'zzz_stable.py'"
        ).fetchone()[0]
        vec_orphans = conn.execute(
            "SELECT COUNT(*) FROM vec_chunks "
            "WHERE chunk_id NOT IN (SELECT id FROM chunks)"
        ).fetchone()[0]
        trigram_orphans = conn.execute(
            "SELECT COUNT(*) FROM symbol_trigrams "
            "WHERE chunk_id NOT IN (SELECT id FROM chunks)"
        ).fetchone()[0]
        total_chunks = db.read_meta(conn, "total_chunks")
    finally:
        conn.close()

    assert stable_id_after == stable_id
    assert "stable-token" in "\n".join(row[2] for row in after_rows)
    assert "after-token" in "\n".join(row[2] for row in after_rows)
    assert "added-token" in "\n".join(row[2] for row in after_rows)
    assert "removed-token" not in "\n".join(row[2] for row in after_rows)
    assert current_files == {"aaa_added.py", "changed.py", "zzz_stable.py"}
    assert new_root != old_root
    assert total_chunks == str(len(after_rows))
    assert vec_orphans == 0
    assert trigram_orphans == 0
    assert before_rows != after_rows


def test_noop_update_preserves_existing_embedder_metadata(incremental_source, tmp_path):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        db.write_meta(conn, "embedder_model", "real://prior-model")
        db.write_meta(conn, "embedder_dim", "768")
        db.write_meta(conn, "embedder_quant", "float32")
    finally:
        conn.close()

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        assert db.read_meta(conn, "embedder_model") == "real://prior-model"
        assert db.read_meta(conn, "embedder_dim") == "768"
        assert db.read_meta(conn, "embedder_quant") == "float32"
    finally:
        conn.close()


def test_update_schema_v1_missing_merkle_preserves_existing_db(
    incremental_source,
    tmp_path,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.execute("CREATE TABLE preserve_me (value TEXT NOT NULL)")
        conn.execute("INSERT INTO preserve_me (value) VALUES ('kept')")
        conn.execute("DELETE FROM merkle_files")
        conn.commit()
    finally:
        conn.close()

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        preserved = conn.execute("SELECT value FROM preserve_me").fetchone()[0]
        merkle_count = conn.execute("SELECT COUNT(*) FROM merkle_files").fetchone()[0]
        distinct_files = conn.execute(
            "SELECT COUNT(DISTINCT file_path) FROM chunks"
        ).fetchone()[0]
    finally:
        conn.close()

    assert preserved == "kept"
    assert after_chunks == before_chunks
    assert merkle_count == distinct_files


def test_update_schema_v1_missing_merkle_chunk_failure_preserves_index(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "vec": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        }
        conn.execute("DELETE FROM merkle_files")
        conn.commit()
    finally:
        conn.close()

    real_chunk_file = vec_cmd.chunker.chunk_file

    def fail_changed(path):
        if Path(path).name == "changed.py":
            raise RuntimeError("forced chunk failure")
        return real_chunk_file(path)

    monkeypatch.setattr(vec_cmd.chunker, "chunk_file", fail_changed)

    ns = argparse.Namespace(
        source=str(incremental_source),
        output_dir=str(output_dir),
        max_file_mb=1.5,
        no_cache=False,
        update=True,
    )
    assert vec_cmd.run(ns) != 0

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "vec": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        }
        merkle_count = conn.execute("SELECT COUNT(*) FROM merkle_files").fetchone()[0]
    finally:
        conn.close()

    assert after_counts == before_counts
    assert merkle_count == 0


def test_update_preserves_modified_file_when_rechunk_fails(
    incremental_source,
    tmp_path,
    monkeypatch,
    capsys,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_content = conn.execute(
            "SELECT content FROM chunks WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        before_sha = conn.execute(
            "SELECT blob_sha FROM merkle_files WHERE file_path = 'changed.py'"
        ).fetchone()[0]
    finally:
        conn.close()

    (incremental_source / "changed.py").write_text(
        "def changed():\n"
        "    return 'after-token'\n",
        encoding="utf-8",
    )

    real_chunk_file = vec_cmd.chunker.chunk_file

    def fail_changed(path):
        if Path(path).name == "changed.py":
            raise RuntimeError("forced chunk failure")
        return real_chunk_file(path)

    monkeypatch.setattr(vec_cmd.chunker, "chunk_file", fail_changed)

    _run_vectorize(incremental_source, output_dir, update=True)
    summary = json.loads(
        [line for line in capsys.readouterr().out.splitlines() if line.strip()][-1]
    )

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_content = conn.execute(
            "SELECT content FROM chunks WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        after_sha = conn.execute(
            "SELECT blob_sha FROM merkle_files WHERE file_path = 'changed.py'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert after_content == before_content
    assert "after-token" not in after_content
    assert after_sha == before_sha
    assert summary["warnings"] == ["chunk failed for changed.py: forced chunk failure"]


def test_update_rebuilds_when_embedder_metadata_changes(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        conn.execute("CREATE TABLE preserve_me (value TEXT NOT NULL)")
        conn.execute("INSERT INTO preserve_me (value) VALUES ('kept')")
        conn.commit()
    finally:
        conn.close()

    class ChangedStub(vec_cmd.embedder.StubEmbedder):
        model_id = "stub://changed"

    monkeypatch.setattr(vec_cmd.embedder, "make_embedder", lambda: ChangedStub())
    (incremental_source / "changed.py").write_text(
        "def changed():\n"
        "    return 'after-token'\n",
        encoding="utf-8",
    )

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        files = {
            row[0]
            for row in conn.execute("SELECT file_path FROM merkle_files")
        }
        assert conn.execute("SELECT value FROM preserve_me").fetchone()[0] == "kept"
        assert db.read_meta(conn, "embedder_model") == "stub://changed"
        assert files == {"changed.py", "removed.py", "zzz_stable.py"}
        assert conn.execute(
            "SELECT COUNT(*) FROM vec_chunks "
            "WHERE chunk_id NOT IN (SELECT id FROM chunks)"
        ).fetchone()[0] == 0
    finally:
        conn.close()

    cache_conn = sqlite3.connect(paths.embedding_cache_path())
    try:
        changed_cache_rows = cache_conn.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE model_id = ?",
            ("stub://changed",),
        ).fetchone()[0]
    finally:
        cache_conn.close()

    assert changed_cache_rows == chunk_count


def test_update_incompatible_embedder_mismatch_preserves_existing_index(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "vec": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        }
        before_model = db.read_meta(conn, "embedder_model")
    finally:
        conn.close()

    class TinyEmbedder:
        model_id = "stub://tiny"
        dim = 8

        def embed(self, texts):
            return np.ones((len(texts), self.dim), dtype=np.float32)

    monkeypatch.setattr(vec_cmd.embedder, "make_embedder", lambda: TinyEmbedder())
    (incremental_source / "changed.py").write_text(
        "def changed():\n"
        "    return 'after-token'\n",
        encoding="utf-8",
    )

    ns = argparse.Namespace(
        source=str(incremental_source),
        output_dir=str(output_dir),
        max_file_mb=1.5,
        no_cache=False,
        update=True,
    )
    assert vec_cmd.run(ns) != 0

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "vec": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        }
        assert after_counts == before_counts
        assert db.read_meta(conn, "embedder_model") == before_model
    finally:
        conn.close()


def test_update_chunk_failure_excludes_failed_file_from_new_symbol_graph(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    (incremental_source / "changed.py").write_text(
        "def before_symbol():\n"
        "    return 'before'\n",
        encoding="utf-8",
    )
    _run_vectorize(incremental_source, output_dir)

    (incremental_source / "changed.py").write_text(
        "def after_symbol():\n"
        "    return 'after'\n",
        encoding="utf-8",
    )

    real_chunk_file = vec_cmd.chunker.chunk_file

    def fail_changed(path):
        if Path(path).name == "changed.py":
            raise RuntimeError("forced chunk failure")
        return real_chunk_file(path)

    monkeypatch.setattr(vec_cmd.chunker, "chunk_file", fail_changed)
    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        old_chunk = conn.execute(
            "SELECT content FROM chunks WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        assert "before_symbol" in old_chunk
        assert conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE name LIKE '%after_symbol%'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE file_path = 'changed.py'"
        ).fetchone()[0] == 0
    finally:
        conn.close()
