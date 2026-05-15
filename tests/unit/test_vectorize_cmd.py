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

from cbv import paths  # noqa: E402
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
    (src / "lib.py").write_text("def helper(x):\n    return x * 2\n")
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


def test_vectorize_populates_symbol_trigrams(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM symbol_trigrams WHERE symbol = 'helper'"
        ).fetchone()
        assert row[0] > 0
    finally:
        conn.close()


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
    # Future-slice keys must exist with zero/empty sentinels.
    assert db.read_meta(conn, "total_nodes_symbol") == "0"
    assert db.read_meta(conn, "total_edges_symbol") == "0"
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
    # Slice 1 placeholders.
    assert blob["nodes_symbol"] == 0
    assert blob["nodes_block"] == 0
    assert blob["edges_symbol"] == 0
    assert blob["edges_flow"] == 0
    assert blob["clusters_indexed"] == 0
    assert "warnings" in blob and isinstance(blob["warnings"], list)
    assert "elapsed_seconds" in blob
