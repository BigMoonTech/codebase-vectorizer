"""Tests for cbv.commands.query — BM25 + dense + RRF, plus legacy detector."""
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
from cbv.commands import query as query_cmd, vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def indexed_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "auth.py").write_text(
        "def authenticate_user(username, password):\n"
        "    return check_credentials(username, password)\n"
    )
    (src / "router.py").write_text(
        "def route_request(req):\n"
        "    if req.path.startswith('/api'):\n"
        "        return api_handler(req)\n"
        "    return static_handler(req)\n"
    )
    (src / "db.py").write_text(
        "def query_user(uid):\n"
        "    return fetch('SELECT * FROM users WHERE id = ?', uid)\n"
    )
    ns = argparse.Namespace(source=str(src), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "upstream"


@pytest.fixture
def empty_indexed_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    src = tmp_path / "empty"
    src.mkdir()
    ns = argparse.Namespace(source=str(src), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "empty"


@pytest.fixture
def long_content_indexed_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    src = tmp_path / "long"
    src.mkdir()
    prefix = "x" * 220
    (src / "late.py").write_text(
        "def late_match():\n"
        f"    data = '{prefix} TAILTOKEN'\n"
        "    return data\n"
    )
    ns = argparse.Namespace(source=str(src), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "long"


def test_query_returns_lane_shape_without_explicit_lane(indexed_repo, capsys):
    ns = argparse.Namespace(
        repo=indexed_repo,
        question="how does login authenticate users",
        top_k=3,
    )
    rc = query_cmd.run(ns)
    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["repo"] == indexed_repo
    assert blob["query"] == "how does login authenticate users"
    assert blob["pipeline_used"] == "full"
    assert "results" in blob and isinstance(blob["results"], list)
    assert "refined_queries" in blob
    assert blob["reranker_model"] == "stub://lexical-overlap-reranker"
    assert isinstance(blob["expansion_size"], int)


def test_query_results_have_required_fields(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="authenticate user", top_k=3)
    query_cmd.run(ns)
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["results"], "expected at least one result"
    r = blob["results"][0]
    for k in ("rank", "file_absolute", "file_relative", "start_line",
              "end_line", "kind", "score", "preview", "why_this_was_returned"):
        assert k in r, f"missing key {k!r}"


def test_query_top_k_caps_result_count(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="route request handler", top_k=1)
    query_cmd.run(ns)
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert len(blob["results"]) <= 1


def test_query_reranks_candidate_rows_before_top_k(indexed_repo, capsys, monkeypatch):
    monkeypatch.setenv("CBV_STUB_RERANKER", "1")
    ns = argparse.Namespace(
        repo=indexed_repo,
        question="fetch SELECT users",
        top_k=1,
        lane="full",
    )

    rc = query_cmd.run(ns)

    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["reranker_model"] == "stub://lexical-overlap-reranker"
    assert len(blob["results"]) == 1
    assert blob["results"][0]["file_relative"] == "db.py"
    assert blob["results"][0]["score"] >= 1.0
    assert blob["refined_queries"] == []


def test_fast_lane_does_not_instantiate_reranker(indexed_repo, capsys, monkeypatch):
    def fail_make_reranker():
        raise AssertionError("fast lane must not instantiate reranker")

    monkeypatch.setattr(query_cmd.reranker, "make_reranker", fail_make_reranker)
    ns = argparse.Namespace(
        repo=indexed_repo,
        question="authenticate_user",
        top_k=1,
        lane="fast",
    )

    rc = query_cmd.run(ns)

    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["pipeline_used"] == "fast"
    assert blob["reranker_model"] is None
    assert blob["refined_queries"] == []
    assert len(blob["results"]) <= 1


def test_full_lane_empty_candidates_does_not_instantiate_reranker(
    empty_indexed_repo,
    capsys,
    monkeypatch,
):
    def fail_make_reranker():
        raise AssertionError("empty full lane must not instantiate reranker")

    monkeypatch.setattr(query_cmd.reranker, "make_reranker", fail_make_reranker)
    ns = argparse.Namespace(
        repo=empty_indexed_repo,
        question="anything to search",
        top_k=3,
        lane="full",
    )

    rc = query_cmd.run(ns)

    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["pipeline_used"] == "full"
    assert blob["results"] == []
    assert blob["refined_queries"] == ["anything to search"]
    assert blob["reranker_model"] is None


def test_full_lane_rejects_mismatched_reranker_score_count(
    indexed_repo,
    capsys,
    monkeypatch,
):
    class ShortScoreReranker:
        model_id = "fake://short-score"

        def score(self, query, passages):
            return [0.0]

    monkeypatch.setattr(
        query_cmd.reranker,
        "make_reranker",
        lambda: ShortScoreReranker(),
    )
    ns = argparse.Namespace(
        repo=indexed_repo,
        question="fetch SELECT users",
        top_k=1,
        lane="full",
    )

    rc = query_cmd.run(ns)

    assert rc == 2
    err = capsys.readouterr().err
    assert "reranker returned 1 scores for" in err


def test_full_lane_reranks_using_full_content_not_display_preview(
    long_content_indexed_repo,
    capsys,
    monkeypatch,
):
    seen_passages = []

    class RecordingReranker:
        model_id = "fake://recording"

        def score(self, query, passages):
            seen_passages.extend(passages)
            return [1.0 for _ in passages]

    monkeypatch.setattr(
        query_cmd.reranker,
        "make_reranker",
        lambda: RecordingReranker(),
    )
    ns = argparse.Namespace(
        repo=long_content_indexed_repo,
        question="TAILTOKEN",
        top_k=1,
        lane="full",
    )

    rc = query_cmd.run(ns)

    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["results"], "expected the long chunk to be returned"
    assert seen_passages
    assert any("TAILTOKEN" in passage for passage in seen_passages)
    assert all(len(passage) > 200 for passage in seen_passages)
    assert "TAILTOKEN" not in blob["results"][0]["preview"]
    assert len(blob["results"][0]["preview"]) <= 203


def test_refined_queries_return_original_query_when_no_rows():
    assert query_cmd._refined_queries("where is auth", []) == ["where is auth"]


def test_refined_queries_suggest_low_confidence_named_results():
    rows = [
        {"name": "first_match", "score": 0.5},
        {"name": "second_match", "score": 0.2},
        {"name": "third_match", "score": 0.1},
        {"name": "fourth_match", "score": 0.0},
    ]

    assert query_cmd._refined_queries("where is auth", rows) == [
        "where is auth first_match",
        "where is auth second_match",
        "where is auth third_match",
    ]


def test_refined_queries_empty_when_top_score_confident():
    assert query_cmd._refined_queries(
        "where is auth",
        [{"name": "first_match", "score": 1.0}],
    ) == []


def test_query_missing_repo_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "empty_home"))
    ns = argparse.Namespace(repo="nonexistent", question="anything", top_k=3)
    rc = query_cmd.run(ns)
    assert rc != 0
    err = capsys.readouterr().err
    assert "No index found" in err
    assert "nonexistent" in err


def test_query_blank_question_returns_clean_error(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="   ", top_k=3, lane="auto")
    rc = query_cmd.run(ns)
    assert rc == 2
    err = capsys.readouterr().err
    assert "query question must not be empty" in err


def test_query_legacy_schema_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    # Create a fake v0.3.0-shaped index: chunks table, no meta.
    legacy_dir = tmp_path / "home" / "repos" / "oldrepo"
    legacy_dir.mkdir(parents=True)
    db_path = legacy_dir / "index.sqlite"
    raw = sqlite3.connect(db_path)
    raw.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    raw.commit()
    raw.close()

    ns = argparse.Namespace(repo="oldrepo", question="x", top_k=3)
    rc = query_cmd.run(ns)
    assert rc != 0
    err = capsys.readouterr().err
    assert "older codebase-vectorizer index" in err


def test_symbol_helpers_tolerate_blank_query():
    conn = sqlite3.connect(":memory:")
    try:
        assert query_cmd._symbol_exact(conn, "   ", limit=10) == {}
        assert query_cmd._trigram(conn, "   ", limit=10) == {}
    finally:
        conn.close()


def test_graph_expand_ignores_contains_edges():
    conn = _graph_conn()
    try:
        _insert_node(conn, node_id=1, kind="file", chunk_id=10)
        _insert_node(conn, node_id=2, kind="function", chunk_id=20)
        _insert_node(conn, node_id=3, kind="function", chunk_id=30)
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            (1, 2, "contains", 1.0),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            (1, 3, "contains", 1.0),
        )

        assert query_cmd._graph_expand(conn, [20]) == {}
    finally:
        conn.close()


def test_graph_expand_uses_max_score_for_duplicate_neighbor_chunks():
    conn = _graph_conn()
    try:
        _insert_node(conn, node_id=1, kind="function", chunk_id=10)
        _insert_node(conn, node_id=2, kind="function", chunk_id=20)
        _insert_node(conn, node_id=3, kind="function", chunk_id=20)
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            (1, 2, "calls", 3.0),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            (1, 3, "references", 1.0),
        )

        assert query_cmd._graph_expand(conn, [10]) == {20: 3.0}
    finally:
        conn.close()


def test_graph_expand_ties_use_chunk_id_order_before_limit():
    conn = _graph_conn()
    try:
        _insert_node(conn, node_id=1, kind="function", chunk_id=10)
        _insert_node(conn, node_id=2, kind="function", chunk_id=30)
        _insert_node(conn, node_id=3, kind="function", chunk_id=20)
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            (1, 2, "calls", 2.0),
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            (1, 3, "calls", 2.0),
        )

        assert query_cmd._graph_expand(conn, [10], per_node=1) == {20: 2.0}
    finally:
        conn.close()


def _graph_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE chunks ("
        "id INTEGER PRIMARY KEY, "
        "category TEXT NOT NULL DEFAULT 'source')"
    )
    conn.execute(
        "CREATE TABLE nodes ("
        "id INTEGER PRIMARY KEY, "
        "kind TEXT NOT NULL, "
        "chunk_id INTEGER)"
    )
    conn.execute(
        "CREATE TABLE edges ("
        "src INTEGER NOT NULL, "
        "dst INTEGER NOT NULL, "
        "kind TEXT NOT NULL, "
        "weight REAL DEFAULT 1.0)"
    )
    return conn


def _insert_node(conn, *, node_id: int, kind: str, chunk_id: int):
    # Ensure the corresponding chunks row exists (category defaults to 'source').
    conn.execute(
        "INSERT OR IGNORE INTO chunks (id) VALUES (?)",
        (chunk_id,),
    )
    conn.execute(
        "INSERT INTO nodes (id, kind, chunk_id) VALUES (?, ?, ?)",
        (node_id, kind, chunk_id),
    )


def test_query_symbol_token_strips_trailing_punctuation():
    from cbv.commands.query import _query_symbol_token

    assert _query_symbol_token("how does the codebase call UMAP?") == "UMAP"
    assert _query_symbol_token("where is cluster_embeddings,") == "cluster_embeddings"
    assert _query_symbol_token("find Foo") == "Foo"
    assert _query_symbol_token("") == ""


def test_rrf_applies_per_ranking_weights():
    from cbv.commands.query import _rrf

    # Two rankings, each with one unique chunk at rank 1. Equal weights -> tie.
    equal = _rrf([{1: 9.0}, {2: 9.0}], k=60, source_names=["a", "b"])
    assert {cid for cid, _, _ in equal} == {1, 2}
    assert equal[0][1] == equal[1][1]

    # Down-weighting the second ranking puts chunk 1 strictly ahead.
    weighted = _rrf(
        [{1: 9.0}, {2: 9.0}], k=60, source_names=["a", "b"], weights=[1.0, 0.1]
    )
    assert weighted[0][0] == 1
    assert weighted[0][1] > weighted[1][1]
