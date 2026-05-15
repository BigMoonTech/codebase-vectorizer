from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import db, paths  # noqa: E402
from cbv.commands import stats  # noqa: E402


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    return tmp_path


def test_stats_missing_repo_returns_clean_code_2(tmp_home, capsys):
    rc = stats.run(argparse.Namespace(repo="missing", top_k=10))

    assert rc == 2
    err = capsys.readouterr().err
    assert "No index found for repo 'missing'." in err


def test_stats_prints_counts_and_top_nodes(tmp_home, capsys):
    repo_dir = paths.repo_dir("sample")
    conn = db.open_db(repo_dir / "index.sqlite")
    db.init_schema(conn)
    db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
    with conn:
        conn.execute(
            "INSERT INTO chunks "
            "(id, file_path, language, kind, start_line, end_line, start_byte, end_byte, content, content_hash, token_count) "
            "VALUES (1, 'pkg/a.py', 'python', 'function', 1, 3, 0, 10, 'def source(): pass', 'h1', 3)"
        )
        conn.execute(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, pagerank) "
            "VALUES (1, 'function', 'pkg/a.py::source', 'source', 'pkg/a.py', 0.25)"
        )
        conn.execute(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, pagerank) "
            "VALUES (2, 'function', 'pkg/a.py::target', 'target', 'pkg/a.py', 0.75)"
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (1, 2, 'calls', 3.0)"
        )
        conn.execute(
            "INSERT INTO clusters (id, label, summary, centroid, size) "
            "VALUES (1, 'auth', 'Authentication code.', X'00', 1)"
        )
    conn.close()

    rc = stats.run(argparse.Namespace(repo="sample", top_k=1))

    assert rc == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["repo"] == "sample"
    assert blob["counts"] == {
        "chunks": 1,
        "nodes": 2,
        "edges": 1,
        "clusters": 1,
    }
    assert blob["top_nodes"] == [
        {"name": "pkg/a.py::target", "kind": "function", "pagerank": 0.75}
    ]
    assert blob["clusters"] == [
        {"label": "auth", "summary": "Authentication code.", "size": 1}
    ]


def test_stats_returns_code_2_for_legacy_schema(tmp_home, capsys):
    repo_dir = paths.repo_dir("legacy")
    conn = db.open_db(repo_dir / "index.sqlite")
    conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    conn.close()

    rc = stats.run(argparse.Namespace(repo="legacy", top_k=10))

    assert rc == 2
    err = capsys.readouterr().err
    assert "Detected an older codebase-vectorizer index" in err


def test_stats_defaults_top_k_for_direct_namespace_call(tmp_home, capsys):
    repo_dir = paths.repo_dir("sample")
    conn = db.open_db(repo_dir / "index.sqlite")
    db.init_schema(conn)
    db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
    with conn:
        conn.execute(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, pagerank) "
            "VALUES (1, 'function', 'pkg/a.py::source', 'source', 'pkg/a.py', 0.25)"
        )
    conn.close()

    rc = stats.run(argparse.Namespace(repo="sample"))

    assert rc == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["top_nodes"] == [
        {"name": "pkg/a.py::source", "kind": "function", "pagerank": 0.25}
    ]
