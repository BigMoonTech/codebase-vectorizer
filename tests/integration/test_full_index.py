"""End-to-end test: index simple-python fixture, run queries, assert results.

Default mode uses StubEmbedder (fast, deterministic). Setting
CBV_RUN_REAL_EMBEDDER=1 reruns with the real Jina embedder — that path
is exercised manually and is not required for Slice 1 to land.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv.commands import query as query_cmd, vectorize as vec_cmd  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "simple-python"


@pytest.fixture
def indexed(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    if os.environ.get("CBV_RUN_REAL_EMBEDDER") != "1":
        monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    ns = argparse.Namespace(source=str(FIXTURE), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "simple-python"


def test_index_files_count_matches_fixture(indexed):
    """The fixture has 11 indexable files (after gitignore)."""
    from cbv import db, paths
    conn = db.open_db(paths.repo_dir(indexed) / "index.sqlite")
    n_files = conn.execute(
        "SELECT COUNT(DISTINCT file_path) FROM chunks"
    ).fetchone()[0]
    # 5 pkg/*.py + tests/test_auth.py + main.py + util.js + README.md + pyproject.toml + .gitignore
    assert n_files == 11


def test_javascript_file_produces_ast_chunks(indexed):
    from cbv import db, paths

    conn = db.open_db(paths.repo_dir(indexed) / "index.sqlite")
    rows = conn.execute(
        "SELECT language, kind, name, ast_path "
        "FROM chunks WHERE file_path = 'util.js' ORDER BY start_byte"
    ).fetchall()

    assert rows == [
        ("javascript", "function", "camelCase", "module/function[camelCase]"),
        ("javascript", "function", "snakeCase", "module/function[snakeCase]"),
    ]


def test_query_for_authenticate_finds_auth_py(indexed, capsys):
    ns = argparse.Namespace(repo=indexed, question="authenticate user credentials", top_k=5)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    # At least one result should be from pkg/auth.py within the top-5.
    found = any("pkg/auth.py" in r["file_relative"] for r in blob["results"])
    assert found, f"results: {[r['file_relative'] for r in blob['results']]}"


def test_query_for_routing_finds_router_py(indexed, capsys):
    ns = argparse.Namespace(repo=indexed, question="route_request POST login handler", top_k=5)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    found = any("pkg/router.py" in r["file_relative"] for r in blob["results"])
    assert found, f"results: {[r['file_relative'] for r in blob['results']]}"


def test_query_for_db_finds_db_py(indexed, capsys):
    ns = argparse.Namespace(repo=indexed, question="SQLite fetch_one query helper", top_k=5)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    found = any("pkg/db.py" in r["file_relative"] for r in blob["results"])
    assert found, f"results: {[r['file_relative'] for r in blob['results']]}"


def test_query_result_line_ranges_valid(indexed, capsys):
    """Every returned (start_line, end_line) range must be valid and content
    at that range must be readable from the file."""
    ns = argparse.Namespace(repo=indexed, question="authenticate", top_k=3)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    for r in blob["results"]:
        f = Path(r["file_absolute"])
        assert f.exists(), f"{f} not found"
        lines = f.read_text(encoding="utf-8").splitlines()
        assert 1 <= r["start_line"] <= r["end_line"] <= len(lines)
