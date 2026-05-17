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
POLYGLOT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "polyglot-mini"


@pytest.fixture
def indexed(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    if os.environ.get("CBV_RUN_REAL_EMBEDDER") != "1":
        monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    ns = argparse.Namespace(source=str(FIXTURE), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "simple-python"


@pytest.fixture
def indexed_polyglot(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    ns = argparse.Namespace(source=str(POLYGLOT_FIXTURE), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "polyglot-mini"


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


def test_symbol_graph_is_populated(indexed):
    from cbv import db, paths

    conn = db.open_db(paths.repo_dir(indexed) / "index.sqlite")
    nodes_symbol = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind != 'block'").fetchone()[0]
    nodes_block = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'block'").fetchone()[0]
    edges_symbol = conn.execute(
        "SELECT COUNT(*) FROM edges "
        "WHERE kind IN ('defines','calls','imports','inherits','references',"
        "'contains','tests','documents','mentions')"
    ).fetchone()[0]
    edges_flow = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind IN ('controls','dataflow','guards')"
    ).fetchone()[0]

    assert nodes_symbol > 0
    assert edges_symbol > 0
    assert conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind IN ('file','class','function','method')"
    ).fetchone()[0] > 0
    assert conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind IN ('contains','calls','imports','references')"
    ).fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind='calls'").fetchone()[0] > 0
    assert int(db.read_meta(conn, "total_nodes_symbol")) == nodes_symbol
    assert int(db.read_meta(conn, "total_nodes_block")) == nodes_block
    assert int(db.read_meta(conn, "total_edges_symbol")) == edges_symbol
    assert int(db.read_meta(conn, "total_edges_flow")) == edges_flow


def test_polyglot_fixture_indexes_query_backed_symbol_edges(indexed_polyglot):
    from cbv import db, paths

    conn = db.open_db(paths.repo_dir(indexed_polyglot) / "index.sqlite")

    assert conn.execute("SELECT COUNT(*) FROM nodes WHERE kind='variable'").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind='inherits'").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind='references'").fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind='calls'").fetchone()[0] > 0


def test_vectorize_warns_on_supported_query_failure_and_preserves_file_node(
    monkeypatch,
    tmp_path,
    capsys,
):
    from cbv import db, symbols

    source_dir = tmp_path / "query-failure-src"
    source_dir.mkdir()
    (source_dir / "broken.py").write_text(
        "def route():\n    return 1\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "index-out"
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")

    def fail_query_captures(language, tree):
        raise RuntimeError("forced query failure")

    monkeypatch.setattr(symbols, "_query_captures", fail_query_captures)

    ns = argparse.Namespace(source=str(source_dir), output_dir=str(output_dir), max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    summary = json.loads(
        [line for line in capsys.readouterr().out.splitlines() if line.strip()][-1]
    )

    assert rc == 0
    assert "symbol extraction failed for broken.py: forced query failure" in summary["warnings"]
    conn = db.open_db(output_dir / "index.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0
    non_block_rows = conn.execute(
        "SELECT kind, name, short_name FROM nodes WHERE kind != 'block'"
    ).fetchall()
    block_rows = conn.execute(
        "SELECT name FROM nodes WHERE kind = 'block'"
    ).fetchall()
    assert non_block_rows == [("file", "broken.py", "broken.py")]
    assert block_rows == []


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


def test_indexed_chunks_carry_their_file_category(tmp_path, monkeypatch):
    """Chunks from a docs file are stored with category='docs', code with 'source'."""
    import sqlite3
    from cbv.commands import vectorize as vec
    from cbv import cli

    src = tmp_path / "repo"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (src / "README.md").write_text("# project\n\nsome prose here\n", encoding="utf-8")

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    out = tmp_path / "index"
    ns = cli.build_parser().parse_args(
        ["vectorize", str(src), "--output-dir", str(out)]
    )
    vec.run(ns)

    conn = sqlite3.connect(out / "index.sqlite")
    try:
        cats = dict(conn.execute(
            "SELECT file_path, category FROM chunks GROUP BY file_path"
        ).fetchall())
    finally:
        conn.close()
    assert cats["pkg/app.py"] == "source"
    assert cats["README.md"] == "docs"
