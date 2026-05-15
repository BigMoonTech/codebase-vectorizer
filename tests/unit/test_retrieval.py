from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import graph  # noqa: E402


def test_personalized_pagerank_boosts_seed_neighborhood_above_unrelated_nodes():
    conn = _graph_conn()
    try:
        _insert_node(conn, node_id=1, kind="function", chunk_id=10)
        _insert_node(conn, node_id=2, kind="function", chunk_id=20)
        _insert_node(conn, node_id=3, kind="function", chunk_id=30)
        _insert_node(conn, node_id=4, kind="block", chunk_id=40)
        _insert_edge(conn, src=1, dst=2, kind="calls", weight=3.0)
        _insert_edge(conn, src=3, dst=1, kind="controls", weight=99.0)
        _insert_edge(conn, src=1, dst=4, kind="contains", weight=99.0)

        scores = graph.personalized_pagerank(conn, [10], iterations=50)

        assert scores[20] > scores[30]
        assert 40 not in scores
    finally:
        conn.close()


def test_personalized_pagerank_returns_empty_for_no_matching_seed_nodes():
    conn = _graph_conn()
    try:
        _insert_node(conn, node_id=1, kind="function", chunk_id=10)

        assert graph.personalized_pagerank(conn, [99]) == {}
        assert graph.personalized_pagerank(conn, []) == {}
    finally:
        conn.close()


def test_personalized_pagerank_uses_seed_scores_when_networkx_does_not_converge(
    monkeypatch,
):
    import networkx as nx

    conn = _graph_conn()
    try:
        _insert_node(conn, node_id=1, kind="function", chunk_id=10)
        _insert_node(conn, node_id=2, kind="function", chunk_id=20)
        _insert_edge(conn, src=1, dst=2, kind="calls", weight=1.0)

        def fail_to_converge(*args, **kwargs):
            raise nx.PowerIterationFailedConvergence(1)

        monkeypatch.setattr(nx, "pagerank", fail_to_converge)

        assert graph.personalized_pagerank(conn, [10]) == {10: 1.0}
    finally:
        conn.close()


def _graph_conn():
    conn = sqlite3.connect(":memory:")
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
    conn.execute(
        "INSERT INTO nodes (id, kind, chunk_id) VALUES (?, ?, ?)",
        (node_id, kind, chunk_id),
    )


def _insert_edge(conn, *, src: int, dst: int, kind: str, weight: float):
    conn.execute(
        "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
        (src, dst, kind, weight),
    )
