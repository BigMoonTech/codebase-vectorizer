from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import graph  # noqa: E402
from cbv.symbols import SymbolEdge, SymbolNode  # noqa: E402


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE nodes (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            short_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            start_line INTEGER,
            end_line INTEGER,
            signature TEXT,
            parent_id INTEGER,
            chunk_id INTEGER,
            pagerank REAL DEFAULT 0.0
        );
        CREATE TABLE edges (
            src INTEGER NOT NULL,
            dst INTEGER NOT NULL,
            kind TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            metadata TEXT,
            PRIMARY KEY (src, dst, kind)
        );
        """
    )
    return conn


def test_insert_nodes_sets_parent_id_from_parent_name():
    conn = _conn()
    nodes = [
        SymbolNode(
            kind="file",
            name="pkg/router.py",
            short_name="router.py",
            file_path="pkg/router.py",
            start_line=1,
            end_line=1,
        ),
        SymbolNode(
            kind="class",
            name="pkg/router.py::Controller",
            short_name="Controller",
            file_path="pkg/router.py",
            start_line=1,
            end_line=5,
            parent_name="pkg/router.py",
        ),
        SymbolNode(
            kind="function",
            name="pkg/router.py::Controller::route",
            short_name="route",
            file_path="pkg/router.py",
            start_line=2,
            end_line=5,
            parent_name="pkg/router.py::Controller",
        ),
    ]

    ids = graph.insert_nodes(conn, nodes)

    parent_id = conn.execute(
        "SELECT parent_id FROM nodes WHERE name = ?",
        ("pkg/router.py::Controller::route",),
    ).fetchone()[0]
    assert parent_id == ids["pkg/router.py::Controller"]


def test_insert_edges_resolves_dst_by_short_name():
    conn = _conn()
    ids = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/router.py",
                short_name="router.py",
                file_path="pkg/router.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/router.py::route",
                short_name="route",
                file_path="pkg/router.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/router.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/auth.py::authenticate_user",
                short_name="authenticate_user",
                file_path="pkg/auth.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/auth.py",
            ),
        ],
    )

    written = graph.insert_edges(
        conn,
        [
            SymbolEdge(
                kind="calls",
                src_name="pkg/router.py::route",
                dst_name="authenticate_user",
                weight=0.9,
            )
        ],
        ids,
    )

    assert written == 1
    assert conn.execute(
        "SELECT src, dst, kind, weight FROM edges"
    ).fetchall() == [
        (
            ids["pkg/router.py::route"],
            ids["pkg/auth.py::authenticate_user"],
            "calls",
            0.9,
        )
    ]


def test_insert_edges_drops_ambiguous_short_name_edges():
    conn = _conn()
    ids = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/router.py",
                short_name="router.py",
                file_path="pkg/router.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/router.py::route",
                short_name="route",
                file_path="pkg/router.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/router.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/a.py::helper",
                short_name="helper",
                file_path="pkg/a.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/a.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/b.py::helper",
                short_name="helper",
                file_path="pkg/b.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/b.py",
            ),
        ],
    )

    written = graph.insert_edges(
        conn,
        [
            SymbolEdge(
                kind="calls",
                src_name="pkg/router.py::route",
                dst_name="helper",
            ),
            SymbolEdge(
                kind="calls",
                src_name="pkg/router.py::route",
                dst_name="pkg/b.py::helper",
            ),
        ],
        ids,
    )

    assert written == 1
    assert conn.execute("SELECT dst FROM edges").fetchall() == [
        (ids["pkg/b.py::helper"],)
    ]


def test_insert_edges_filters_short_name_resolution_by_compatible_kind():
    conn = _conn()
    ids = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/router.py",
                short_name="router.py",
                file_path="pkg/router.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/router.py::route",
                short_name="route",
                file_path="pkg/router.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/router.py",
            ),
            SymbolNode(
                kind="class",
                name="pkg/auth.py::Auth",
                short_name="Auth",
                file_path="pkg/auth.py",
                start_line=1,
                end_line=10,
                parent_name="pkg/auth.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/auth.py::authenticate_user",
                short_name="authenticate_user",
                file_path="pkg/auth.py",
                start_line=12,
                end_line=15,
                parent_name="pkg/auth.py",
            ),
            SymbolNode(
                kind="method",
                name="pkg/auth.py::Auth::login",
                short_name="login",
                file_path="pkg/auth.py",
                start_line=2,
                end_line=5,
                parent_name="pkg/auth.py::Auth",
            ),
        ],
    )

    written = graph.insert_edges(
        conn,
        [
            SymbolEdge(
                kind="calls",
                src_name="pkg/router.py::route",
                dst_name="Auth",
            ),
            SymbolEdge(
                kind="calls",
                src_name="pkg/router.py::route",
                dst_name="authenticate_user",
            ),
            SymbolEdge(
                kind="calls",
                src_name="pkg/router.py::route",
                dst_name="login",
            ),
        ],
        ids,
    )

    assert written == 2
    assert sorted(conn.execute("SELECT dst FROM edges").fetchall()) == sorted(
        [
            (ids["pkg/auth.py::authenticate_user"],),
            (ids["pkg/auth.py::Auth::login"],),
        ]
    )


def test_insert_edges_prefers_same_directory_for_compatible_short_name():
    conn = _conn()
    ids = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/a.py",
                short_name="a.py",
                file_path="pkg/a.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/a.py::route",
                short_name="route",
                file_path="pkg/a.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/a.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/helper.py::helper",
                short_name="helper",
                file_path="pkg/helper.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/helper.py",
            ),
            SymbolNode(
                kind="function",
                name="other/helper.py::helper",
                short_name="helper",
                file_path="other/helper.py",
                start_line=1,
                end_line=3,
                parent_name="other/helper.py",
            ),
        ],
    )

    written = graph.insert_edges(
        conn,
        [
            SymbolEdge(
                kind="calls",
                src_name="pkg/a.py::route",
                dst_name="helper",
            )
        ],
        ids,
    )

    assert written == 1
    assert conn.execute("SELECT dst FROM edges").fetchall() == [
        (ids["pkg/helper.py::helper"],)
    ]


def test_insert_edges_drops_unresolved_and_self_edges():
    conn = _conn()
    ids = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/router.py",
                short_name="router.py",
                file_path="pkg/router.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/router.py::route",
                short_name="route",
                file_path="pkg/router.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/router.py",
            ),
        ],
    )

    written = graph.insert_edges(
        conn,
        [
            SymbolEdge(kind="calls", src_name="pkg/router.py::route", dst_name="missing"),
            SymbolEdge(kind="calls", src_name="pkg/router.py::route", dst_name="route"),
        ],
        ids,
    )

    assert written == 0
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 0


def test_compute_pagerank_excludes_block_nodes_and_flow_edges():
    conn = _conn()
    source = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/a.py",
                short_name="a.py",
                file_path="pkg/a.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/a.py::source",
                short_name="source",
                file_path="pkg/a.py",
                start_line=1,
                end_line=3,
                parent_name="pkg/a.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/a.py::target",
                short_name="target",
                file_path="pkg/a.py",
                start_line=5,
                end_line=7,
                parent_name="pkg/a.py",
            ),
            SymbolNode(
                kind="block",
                name="pkg/a.py::source::block_1",
                short_name="block_1",
                file_path="pkg/a.py",
                start_line=2,
                end_line=2,
                parent_name="pkg/a.py::source",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'calls', 3.0)",
        (source["pkg/a.py::source"], source["pkg/a.py::target"]),
    )
    conn.execute(
        "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'controls', 99.0)",
        (source["pkg/a.py::target"], source["pkg/a.py::source"]),
    )
    conn.execute(
        "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'contains', 1.0)",
        (source["pkg/a.py::source"], source["pkg/a.py::source::block_1"]),
    )

    count = graph.compute_pagerank(conn)

    assert count == 3
    rows = dict(conn.execute("SELECT name, pagerank FROM nodes").fetchall())
    assert rows["pkg/a.py::target"] > rows["pkg/a.py::source"]
    assert rows["pkg/a.py::source::block_1"] == 0.0


def test_compute_pagerank_warns_and_uses_uniform_scores_when_networkx_does_not_converge(
    monkeypatch,
):
    import networkx as nx

    conn = _conn()
    ids = graph.insert_nodes(
        conn,
        [
            SymbolNode(
                kind="file",
                name="pkg/a.py",
                short_name="a.py",
                file_path="pkg/a.py",
                start_line=1,
                end_line=1,
            ),
            SymbolNode(
                kind="function",
                name="pkg/a.py::source",
                short_name="source",
                file_path="pkg/a.py",
                start_line=2,
                end_line=4,
                parent_name="pkg/a.py",
            ),
            SymbolNode(
                kind="function",
                name="pkg/a.py::target",
                short_name="target",
                file_path="pkg/a.py",
                start_line=6,
                end_line=8,
                parent_name="pkg/a.py",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'calls', 1.0)",
        (ids["pkg/a.py::source"], ids["pkg/a.py::target"]),
    )

    def fail_to_converge(*args, **kwargs):
        raise nx.PowerIterationFailedConvergence(100)

    monkeypatch.setattr(nx, "pagerank", fail_to_converge)
    warnings = []

    count = graph.compute_pagerank(conn, warnings=warnings)

    assert count == 3
    assert warnings == ["pagerank failed to converge; using uniform scores"]
    rows = dict(conn.execute("SELECT name, pagerank FROM nodes").fetchall())
    assert rows == {
        "pkg/a.py": 1 / 3,
        "pkg/a.py::source": 1 / 3,
        "pkg/a.py::target": 1 / 3,
    }
