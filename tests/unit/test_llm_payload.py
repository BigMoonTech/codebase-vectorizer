from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest  # noqa: E402

from cbv import db, paths  # noqa: E402
from cbv.commands import llm_payload  # noqa: E402


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    return tmp_path


def _seed_repo(name: str):
    repo_dir = paths.repo_dir(name)
    conn = db.open_db(repo_dir / "index.sqlite")
    db.init_schema(conn)
    db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
    with conn:
        conn.execute(
            "INSERT INTO chunks "
            "(id, file_path, language, kind, start_line, end_line, start_byte, end_byte, content, content_hash, token_count) "
            "VALUES (1, 'pkg/a.py', 'python', 'function', 1, 3, 0, 10, 'def login(): pass', 'h1', 3)"
        )
        conn.execute(
            "INSERT INTO chunks "
            "(id, file_path, language, kind, start_line, end_line, start_byte, end_byte, content, content_hash, token_count) "
            "VALUES (2, 'pkg/b.py', 'python', 'function', 1, 3, 0, 10, 'def logout(): pass', 'h2', 3)"
        )
        conn.execute(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, pagerank) "
            "VALUES (1, 'function', 'pkg/a.py::login', 'login', 'pkg/a.py', 0.5)"
        )
        conn.execute(
            "INSERT INTO clusters (id, label, summary, centroid, size) "
            "VALUES (3, 'cluster 3', 'Code related to cluster 3.', X'00', 2)"
        )
        conn.execute(
            "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (1, 3, 0.9)"
        )
        conn.execute(
            "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (2, 3, 0.6)"
        )
    conn.close()
    return repo_dir


def test_llm_payload_missing_repo_returns_code_2(tmp_home, capsys):
    rc = llm_payload.run(argparse.Namespace(repo="missing"))
    assert rc == 2
    assert "No index found for repo 'missing'." in capsys.readouterr().err


def test_llm_payload_emits_cluster_samples_and_architecture(tmp_home, capsys):
    _seed_repo("sample")
    rc = llm_payload.run(argparse.Namespace(repo="sample"))
    assert rc == 0
    blob = json.loads(capsys.readouterr().out)

    assert blob["repo"] == "sample"
    assert blob["architecture_path"].endswith("ARCHITECTURE.md")

    assert len(blob["clusters"]) == 1
    cluster = blob["clusters"][0]
    assert cluster["id"] == 3
    # samples come back ordered by descending membership
    assert cluster["samples"] == ["def login(): pass", "def logout(): pass"]

    arch = blob["architecture"]
    assert arch["repo_name"] == "sample"
    assert arch["counts"]["chunks"] == 2
    assert arch["counts"]["clusters"] == 1
    assert arch["languages"] == [{"language": "python", "chunks": 2}]
    assert arch["top_nodes"][0]["name"] == "pkg/a.py::login"


def test_llm_payload_returns_code_2_for_legacy_schema(tmp_home, capsys):
    repo_dir = paths.repo_dir("legacy")
    conn = db.open_db(repo_dir / "index.sqlite")
    conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    conn.close()

    rc = llm_payload.run(argparse.Namespace(repo="legacy"))
    assert rc == 2
    assert "Detected an older codebase-vectorizer index" in capsys.readouterr().err
