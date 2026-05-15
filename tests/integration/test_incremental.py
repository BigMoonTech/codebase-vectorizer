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


def test_noop_update_preserves_embedder_metadata_when_unchanged(
    incremental_source,
    tmp_path,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_meta = {
            "model": db.read_meta(conn, "embedder_model"),
            "dim": db.read_meta(conn, "embedder_dim"),
            "quant": db.read_meta(conn, "embedder_quant"),
        }
    finally:
        conn.close()

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_meta = {
            "model": db.read_meta(conn, "embedder_model"),
            "dim": db.read_meta(conn, "embedder_dim"),
            "quant": db.read_meta(conn, "embedder_quant"),
        }
    finally:
        conn.close()

    assert after_meta == before_meta


def test_noop_update_with_current_clusters_does_not_reembed_for_clustering(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        chunk_id = conn.execute(
            "SELECT id FROM chunks WHERE file_path = 'zzz_stable.py' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        with conn:
            conn.execute(
                "INSERT INTO clusters (id, label, summary, centroid, size) "
                "VALUES (1, 'existing', 'Existing cluster.', ?, 1)",
                (np.ones(1536, dtype="float32").tobytes(),),
            )
            conn.execute(
                "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (?, 1, 0.9)",
                (chunk_id,),
            )
            db.write_meta(conn, "total_clusters", "1")
    finally:
        conn.close()

    def fail_make_embedder():
        raise AssertionError("make_embedder should not be called for no-op update")

    monkeypatch.setattr(vec_cmd.embedder, "make_embedder", fail_make_embedder)

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        cluster_count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    finally:
        conn.close()

    assert cluster_count == 1


def test_changed_update_reuses_stored_vectors_for_cluster_planning(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    (incremental_source / "changed.py").write_text(
        "def changed():\n"
        "    return 'after-token-for-cluster-vector-reuse'\n",
        encoding="utf-8",
    )

    class CountingEmbedder(vec_cmd.embedder.StubEmbedder):
        def __init__(self):
            super().__init__()
            self.batch_sizes: list[int] = []

        def embed(self, texts):
            self.batch_sizes.append(len(texts))
            return super().embed(texts)

    counting_embedder = CountingEmbedder()
    cluster_shapes: list[tuple[tuple[int, ...], str]] = []

    def record_cluster_embeddings(embeddings, **kwargs):
        cluster_shapes.append((embeddings.shape, str(embeddings.dtype)))
        return vec_cmd.clusters.ClusterResult(
            [-1 for _ in range(len(embeddings))],
            [0.0 for _ in range(len(embeddings))],
            embeddings,
        )

    monkeypatch.setattr(
        vec_cmd.embedder,
        "make_embedder",
        lambda: counting_embedder,
    )
    monkeypatch.setattr(
        vec_cmd.clusters,
        "cluster_embeddings",
        record_cluster_embeddings,
    )

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()

    assert counting_embedder.batch_sizes == [1]
    assert cluster_shapes == [((chunk_count, counting_embedder.dim), "float32")]


def test_cluster_backend_failure_preserves_existing_clusters_on_update(
    incremental_source,
    tmp_path,
    monkeypatch,
    capsys,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        chunk_id = conn.execute(
            "SELECT id FROM chunks WHERE file_path = 'zzz_stable.py' ORDER BY id LIMIT 1"
        ).fetchone()[0]
        with conn:
            conn.execute(
                "INSERT INTO clusters (id, label, summary, centroid, size) "
                "VALUES (1, 'existing', 'Existing cluster.', ?, 1)",
                (np.ones(1536, dtype="float32").tobytes(),),
            )
            conn.execute(
                "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (?, 1, 0.9)",
                (chunk_id,),
            )
            db.write_meta(conn, "total_clusters", "1")
        before_chunks = conn.execute(
            "SELECT file_path, content FROM chunks ORDER BY file_path, id"
        ).fetchall()
        before_merkle = conn.execute(
            "SELECT file_path, blob_sha, size_bytes FROM merkle_files ORDER BY file_path"
        ).fetchall()
        before_nodes = conn.execute(
            "SELECT kind, name, file_path, chunk_id FROM nodes ORDER BY id"
        ).fetchall()
        before_edges = conn.execute(
            "SELECT src, dst, kind, weight, metadata FROM edges ORDER BY src, dst, kind"
        ).fetchall()
        before_meta = {
            key: db.read_meta(conn, key)
            for key in ("total_chunks", "total_clusters", "merkle_root_sha")
        }
    finally:
        conn.close()

    (incremental_source / "changed.py").write_text(
        "def changed():\n"
        "    return 'after-token'\n",
        encoding="utf-8",
    )

    def fail_cluster_embeddings(embeddings, **kwargs):
        raise RuntimeError("umap failed")

    monkeypatch.setattr(vec_cmd.clusters, "cluster_embeddings", fail_cluster_embeddings)

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
        after_chunks = conn.execute(
            "SELECT file_path, content FROM chunks ORDER BY file_path, id"
        ).fetchall()
        after_merkle = conn.execute(
            "SELECT file_path, blob_sha, size_bytes FROM merkle_files ORDER BY file_path"
        ).fetchall()
        after_nodes = conn.execute(
            "SELECT kind, name, file_path, chunk_id FROM nodes ORDER BY id"
        ).fetchall()
        after_edges = conn.execute(
            "SELECT src, dst, kind, weight, metadata FROM edges ORDER BY src, dst, kind"
        ).fetchall()
        cluster_rows = conn.execute("SELECT id, label FROM clusters").fetchall()
        member_rows = conn.execute("SELECT chunk_id, cluster_id, membership FROM chunk_clusters").fetchall()
        after_meta = {
            key: db.read_meta(conn, key)
            for key in ("total_chunks", "total_clusters", "merkle_root_sha")
        }
    finally:
        conn.close()

    assert after_chunks == before_chunks
    assert after_merkle == before_merkle
    assert after_nodes == before_nodes
    assert after_edges == before_edges
    assert cluster_rows == [(1, "existing")]
    assert member_rows == [(chunk_id, 1, 0.9)]
    assert after_meta == before_meta
    assert "concept clustering failed: umap failed" in capsys.readouterr().out


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


def test_update_partial_missing_merkle_row_rebuilds_without_duplicate_chunks(
    incremental_source,
    tmp_path,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        before_changed = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        conn.execute("DELETE FROM merkle_files WHERE file_path = 'changed.py'")
        conn.commit()
    finally:
        conn.close()

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        after_changed = conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        merkle_files = {
            row[0]
            for row in conn.execute("SELECT file_path FROM merkle_files")
        }
    finally:
        conn.close()

    assert after_total == before_total
    assert after_changed == before_changed
    assert merkle_files == {"changed.py", "removed.py", "zzz_stable.py"}


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


def test_update_embedding_insert_failure_rolls_back_destructive_changes(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    (incremental_source / "changed.py").write_text(
        "def before_symbol():\n"
        "    return 'before-token'\n",
        encoding="utf-8",
    )
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_changed_chunks = conn.execute(
            "SELECT content FROM chunks WHERE file_path = 'changed.py' ORDER BY id"
        ).fetchall()
        before_changed_sha = conn.execute(
            "SELECT blob_sha FROM merkle_files WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        before_counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "vec": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        }
        assert before_counts["nodes"] > 0
    finally:
        conn.close()

    (incremental_source / "changed.py").write_text(
        "def after_symbol():\n"
        "    return 'after-token'\n",
        encoding="utf-8",
    )

    def fail_insert_embedding(conn, chunk_id, int8_vec):
        raise RuntimeError("forced embedding insert failure")

    monkeypatch.setattr(vec_cmd.db, "insert_embedding", fail_insert_embedding)

    ns = argparse.Namespace(
        source=str(incremental_source),
        output_dir=str(output_dir),
        max_file_mb=1.5,
        no_cache=False,
        update=True,
    )
    with pytest.raises(RuntimeError, match="forced embedding insert failure"):
        vec_cmd.run(ns)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        after_changed_chunks = conn.execute(
            "SELECT content FROM chunks WHERE file_path = 'changed.py' ORDER BY id"
        ).fetchall()
        after_changed_sha = conn.execute(
            "SELECT blob_sha FROM merkle_files WHERE file_path = 'changed.py'"
        ).fetchone()[0]
        after_counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "vec": conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        }
        after_symbol_nodes = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE name LIKE '%after_symbol%'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert after_changed_chunks == before_changed_chunks
    assert "after-token" not in "\n".join(row[0] for row in after_changed_chunks)
    assert after_changed_sha == before_changed_sha
    assert after_counts == before_counts
    assert after_symbol_nodes == 0


def test_fresh_chunk_failure_is_retried_by_update(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    (incremental_source / "bad.py").write_text(
        "def bad():\n"
        "    return 'bad-token'\n",
        encoding="utf-8",
    )
    real_chunk_file = vec_cmd.chunker.chunk_file

    def fail_bad(path):
        if Path(path).name == "bad.py":
            raise RuntimeError("forced chunk failure")
        return real_chunk_file(path)

    monkeypatch.setattr(vec_cmd.chunker, "chunk_file", fail_bad)
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM merkle_files WHERE file_path = 'bad.py'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE file_path = 'bad.py'"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE file_path = 'bad.py'"
        ).fetchone()[0] == 0
    finally:
        conn.close()

    monkeypatch.setattr(vec_cmd.chunker, "chunk_file", real_chunk_file)
    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM merkle_files WHERE file_path = 'bad.py'"
        ).fetchone()[0] == 1
        bad_chunks = conn.execute(
            "SELECT content FROM chunks WHERE file_path = 'bad.py'"
        ).fetchall()
    finally:
        conn.close()

    assert bad_chunks
    assert "bad-token" in "\n".join(row[0] for row in bad_chunks)


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


def test_noop_update_rebuilds_for_compatible_embedder_metadata_change(
    incremental_source,
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "index"
    _run_vectorize(incremental_source, output_dir)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        before_chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()

    class ChangedStub(vec_cmd.embedder.StubEmbedder):
        model_id = "stub://changed-noop"

    monkeypatch.setattr(vec_cmd.embedder, "make_embedder", lambda: ChangedStub())

    _run_vectorize(incremental_source, output_dir, update=True)

    conn = db.open_db(output_dir / "index.sqlite")
    try:
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        files = {
            row[0]
            for row in conn.execute("SELECT file_path FROM merkle_files")
        }
        assert db.read_meta(conn, "embedder_model") == "stub://changed-noop"
        assert db.read_meta(conn, "embedder_dim") == "1536"
        assert db.read_meta(conn, "embedder_quant") == "int8"
        assert files == {"changed.py", "removed.py", "zzz_stable.py"}
    finally:
        conn.close()

    cache_conn = sqlite3.connect(paths.embedding_cache_path())
    try:
        changed_cache_rows = cache_conn.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE model_id = ?",
            ("stub://changed-noop",),
        ).fetchone()[0]
    finally:
        cache_conn.close()

    assert chunk_count == before_chunk_count
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
