"""Tests for cbv.commands.vectorize — exercises the full pipeline with the
StubEmbedder and a tmp source tree."""
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

from cbv import cache, chunker, paths  # noqa: E402
from cbv.commands import vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    yield tmp_path


@pytest.fixture
def source_repo(tmp_home):
    src = tmp_home / "upstream"
    src.mkdir()
    (src / "main.py").write_text("def main():\n    print('hello')\n")
    (src / "lib.py").write_text(
        "def helper(x):\n"
        "    helper_value = helper(x)\n"
        "    id = db\n"
        "    return helper_value\n"
    )
    (src / "README.md").write_text("# upstream\n\nThis is a test repo.\n")
    return src


def test_vectorize_creates_index_sqlite(tmp_home, source_repo, capsys):
    ns = argparse.Namespace(
        source=str(source_repo), output_dir=None, max_file_mb=1.5,
    )
    rc = vec_cmd.run(ns)
    assert rc == 0
    repo_dir = paths.repo_dir("upstream")
    assert (repo_dir / "index.sqlite").exists()
    assert (repo_dir / "manifest.json").exists()
    assert (repo_dir / "source" / "main.py").exists()


def test_vectorize_populates_chunks(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    db_path = paths.repo_dir("upstream") / "index.sqlite"
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert n >= 3  # at least one chunk per file


def test_vectorize_populates_vec_chunks(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    db_path = paths.repo_dir("upstream") / "index.sqlite"
    from cbv import db
    conn = db.open_db(db_path)
    chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vec_n = conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    assert vec_n == chunks_n


def test_vectorize_populates_fts(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    rows = conn.execute(
        "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'helper'"
    ).fetchone()[0]
    assert rows >= 1


def test_vectorize_computes_nonzero_pagerank_for_symbol_nodes(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)

    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    try:
        nonzero = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind != 'block' AND pagerank > 0.0"
        ).fetchone()[0]
    finally:
        conn.close()

    assert nonzero > 0


def test_vectorize_propagates_pagerank_warnings(tmp_home, source_repo, monkeypatch, capsys):
    def fake_compute_pagerank(conn, warnings=None):
        if warnings is not None:
            warnings.append("pagerank failed to converge; using uniform scores")
        return 0

    monkeypatch.setattr(vec_cmd.graph, "compute_pagerank", fake_compute_pagerank)

    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )
    manifest = json.loads((paths.repo_dir("upstream") / "manifest.json").read_text())

    assert "pagerank failed to converge; using uniform scores" in blob["warnings"]
    assert "pagerank failed to converge; using uniform scores" in manifest["warnings"]


def test_vectorize_treats_architecture_write_failure_as_non_critical(
    tmp_home,
    source_repo,
    monkeypatch,
    capsys,
):
    original_write_text = Path.write_text

    def fail_architecture_write(self, *args, **kwargs):
        if self.name == "ARCHITECTURE.md":
            raise OSError("readonly artifact path")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_architecture_write)

    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )
    manifest = json.loads((paths.repo_dir("upstream") / "manifest.json").read_text())

    assert rc == 0
    assert any("ARCHITECTURE.md generation failed" in warning for warning in blob["warnings"])
    assert any("ARCHITECTURE.md generation failed" in warning for warning in manifest["warnings"])


def test_vectorize_persists_bench_failure_warning_to_manifest(
    tmp_home,
    source_repo,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        vec_cmd.bench_cmd,
        "run_bench",
        lambda repo, emit=False: (
            2,
            {
                "repo": repo,
                "mrr_at_10": 0.0,
                "ndcg_at_10": 0.0,
                "recall_at_5": 0.0,
                "recall_at_10": 0.0,
                "queries": 0,
            },
            "bad benchmark row",
        ),
    )

    ns = argparse.Namespace(
        source=str(source_repo),
        output_dir=None,
        max_file_mb=1.5,
        bench=True,
    )
    rc = vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )
    manifest = json.loads((paths.repo_dir("upstream") / "manifest.json").read_text())

    assert rc == 0
    assert "bench failed: bad benchmark row" in blob["warnings"]
    assert "bench failed: bad benchmark row" in manifest["warnings"]


def test_vectorize_populates_symbol_trigrams(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    try:
        row = conn.execute(
            "SELECT SUM(occurrences) FROM symbol_trigrams "
            "WHERE trigram = 'hel' AND symbol = 'helper'"
        ).fetchone()
        assert row[0] == 4
        row = conn.execute(
            "SELECT SUM(occurrences) FROM symbol_trigrams "
            "WHERE trigram = ' db' AND symbol = 'db'"
        ).fetchone()
        assert row[0] == 1
    finally:
        conn.close()


def test_vectorize_preserves_file_nodes_and_warns_when_symbol_parse_fails(
    tmp_home,
    source_repo,
    monkeypatch,
    capsys,
):
    from cbv import db, parser

    real_parse = parser.parse

    def fail_lib_parse(content, language):
        if b"def helper" in content:
            return None
        return real_parse(content, language)

    monkeypatch.setattr(parser, "parse", fail_lib_parse)
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )

    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    rows = conn.execute(
        "SELECT kind, name, short_name, chunk_id FROM nodes WHERE name = 'lib.py'"
    ).fetchall()
    lib_chunk_id = conn.execute(
        "SELECT id FROM chunks WHERE file_path = 'lib.py'"
    ).fetchone()[0]

    assert rows == [("file", "lib.py", "lib.py", lib_chunk_id)]
    assert any(
        warning.startswith("symbol extraction failed for lib.py:")
        for warning in blob["warnings"]
    )


def test_vectorize_creates_file_node_for_empty_indexable_file(tmp_home, source_repo):
    (source_repo / "empty.py").write_text("")

    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)

    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    rows = conn.execute(
        "SELECT kind, name, short_name, chunk_id FROM nodes WHERE name = 'empty.py'"
    ).fetchall()
    chunk_rows = conn.execute(
        "SELECT id FROM chunks WHERE file_path = 'empty.py'"
    ).fetchall()

    assert chunk_rows == []
    assert rows == [("file", "empty.py", "empty.py", None)]


def test_vectorize_writes_meta(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    assert db.read_meta(conn, "schema_version") == "1.0"
    assert db.read_meta(conn, "embedder_dim") == "1536"
    assert db.read_meta(conn, "embedder_model") == "stub://sha256"
    assert db.read_meta(conn, "embedder_quant") == "int8"
    assert int(db.read_meta(conn, "total_chunks")) >= 3
    assert int(db.read_meta(conn, "total_nodes_symbol")) > 0
    assert int(db.read_meta(conn, "total_edges_symbol")) > 0
    # Remaining future-slice keys must exist with zero/empty sentinels.
    assert db.read_meta(conn, "total_clusters") == "0"
    assert db.read_meta(conn, "reranker_model") == ""


def test_vectorize_prints_v1_summary_json(tmp_home, source_repo, capsys):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    out = capsys.readouterr().out
    # The last non-empty line is the JSON blob.
    line = [l for l in out.strip().splitlines() if l.strip()][-1]
    blob = json.loads(line)
    assert blob["repo_name"] == "upstream"
    assert blob["files_indexed"] >= 3
    assert blob["chunks_indexed"] >= 3
    assert blob["nodes_symbol"] > 0
    assert blob["nodes_block"] > 0
    assert blob["edges_symbol"] > 0
    assert blob["edges_flow"] > 0
    assert blob["clusters_indexed"] == 0
    assert "warnings" in blob and isinstance(blob["warnings"], list)
    assert "elapsed_seconds" in blob


def test_vectorize_populates_embedding_cache_on_first_run(tmp_home, source_repo, capsys):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)

    vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )
    manifest = json.loads((paths.repo_dir("upstream") / "manifest.json").read_text())

    assert paths.embedding_cache_path().exists()
    conn = sqlite3.connect(paths.embedding_cache_path())
    try:
        cache_rows = conn.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE model_id = ?",
            ("stub://sha256",),
        ).fetchone()[0]
    finally:
        conn.close()
    index_conn = sqlite3.connect(paths.repo_dir("upstream") / "index.sqlite")
    try:
        distinct_cached_chunks = index_conn.execute(
            "SELECT COUNT(DISTINCT content_hash) FROM chunks"
        ).fetchone()[0]
    finally:
        index_conn.close()

    assert cache_rows == distinct_cached_chunks
    assert blob["embedding_cache_hit_rate"] == 0.0
    assert manifest["embedding_cache_hit_rate"] == 0.0


def test_vectorize_reuses_embedding_cache_on_second_identical_run(
    tmp_home,
    source_repo,
    capsys,
):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)

    vec_cmd.run(ns)
    capsys.readouterr()
    vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )
    manifest = json.loads((paths.repo_dir("upstream") / "manifest.json").read_text())

    assert blob["embedding_cache_hit_rate"] == 1.0
    assert manifest["embedding_cache_hit_rate"] == 1.0


def test_vectorize_no_cache_does_not_create_embedding_cache(tmp_home, source_repo, capsys):
    ns = argparse.Namespace(
        source=str(source_repo),
        output_dir=None,
        max_file_mb=1.5,
        no_cache=True,
    )

    vec_cmd.run(ns)
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )
    manifest = json.loads((paths.repo_dir("upstream") / "manifest.json").read_text())

    assert not paths.embedding_cache_path().exists()
    assert blob["embedding_cache_hit_rate"] == 0.0
    assert manifest["embedding_cache_hit_rate"] == 0.0


def test_vectorize_replaces_wrong_length_cached_embedding(
    tmp_home,
    source_repo,
    capsys,
):
    first_chunk = next(iter(chunker.chunk_file(source_repo / "main.py")))
    cache_conn = cache.open_cache(paths.embedding_cache_path())
    try:
        cache.put(
            cache_conn,
            first_chunk.content_hash,
            "stub://sha256",
            np.array([1, 2, 3], dtype=np.int8),
        )
        cache_conn.commit()
    finally:
        cache_conn.close()

    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    assert vec_cmd.run(ns) == 0
    blob = json.loads(
        [l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1]
    )

    cache_conn = cache.open_cache(paths.embedding_cache_path())
    try:
        cached = cache.get(cache_conn, first_chunk.content_hash, "stub://sha256")
    finally:
        cache_conn.close()

    assert blob["embedding_cache_hit_rate"] == 0.0
    assert cached is not None
    assert cached.dtype == np.int8
    assert cached.shape == (1536,)
