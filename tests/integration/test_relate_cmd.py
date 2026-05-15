from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
import numpy as np

from cbv import clusters, db, paths  # noqa: E402
from cbv.commands import flow_cmd, graph_cmd, relate, vectorize as vec_cmd  # noqa: E402


FLOW_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "flow-heavy"

ALL_RELATE_VERBS = [
    "callers",
    "callees",
    "inheritance-chain",
    "neighbors",
    "concept-cluster",
    "pagerank-top",
    "shortest-path",
    "paths-through",
    "reaching-definitions",
    "reachable-uses",
    "conditions-for",
]


@pytest.fixture
def indexed_graph(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repo_dir = paths.repo_dir("graphrepo")
    conn = db.open_db(repo_dir / "index.sqlite")
    db.init_schema(conn)
    db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
    with conn:
        conn.executemany(
            "INSERT INTO chunks "
            "(id, file_path, language, kind, name, start_line, end_line, start_byte, end_byte, content, content_hash, token_count) "
            "VALUES (?, ?, 'python', 'function', ?, 1, 3, 0, 10, ?, ?, 3)",
            [
                (1, "pkg/auth.py", "authenticate_user", "def authenticate_user(): pass", "h1"),
                (2, "pkg/router.py", "_handle_login", "def _handle_login(): pass", "h2"),
                (3, "pkg/db.py", "fetch_one", "def fetch_one(): pass", "h3"),
                (4, "pkg/base.py", "BaseAuth", "class BaseAuth: pass", "h4"),
                (5, "pkg/child.py", "TokenAuth", "class TokenAuth(BaseAuth): pass", "h5"),
            ],
        )
        conn.executemany(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, chunk_id, pagerank) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "function", "pkg/auth.py::authenticate_user", "authenticate_user", "pkg/auth.py", 1, 0.80),
                (2, "function", "pkg/router.py::_handle_login", "_handle_login", "pkg/router.py", 2, 0.50),
                (3, "function", "pkg/db.py::fetch_one", "fetch_one", "pkg/db.py", 3, 0.30),
                (4, "class", "pkg/base.py::BaseAuth", "BaseAuth", "pkg/base.py", 4, 0.20),
                (5, "class", "pkg/child.py::TokenAuth", "TokenAuth", "pkg/child.py", 5, 0.10),
                (6, "block", "pkg/auth.py::authenticate_user#if", "if", "pkg/auth.py", 1, 0.99),
            ],
        )
        conn.executemany(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, ?, ?)",
            [
                (2, 1, "calls", 1.0),
                (1, 3, "calls", 1.0),
                (5, 4, "inherits", 1.0),
                (1, 6, "contains", 1.0),
            ],
        )
    conn.close()
    return "graphrepo"


@pytest.fixture
def indexed_flow(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    ns = argparse.Namespace(
        source=str(FLOW_FIXTURE),
        output_dir=None,
        max_file_mb=1.5,
        no_cache=True,
        update=False,
    )
    rc = vec_cmd.run(ns)
    out = capsys.readouterr().out
    summary = json.loads([line for line in out.splitlines() if line.strip()][-1])
    assert rc == 0
    return {"repo": "flow-heavy", "summary": summary}


def _index_source_tree(monkeypatch, tmp_path, capsys, repo_name: str, files: dict[str, str]) -> str:
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    source_dir = tmp_path / repo_name
    source_dir.mkdir()
    for rel_path, content in files.items():
        path = source_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    ns = argparse.Namespace(
        source=str(source_dir),
        output_dir=None,
        max_file_mb=1.5,
        no_cache=True,
        update=False,
    )
    rc = vec_cmd.run(ns)
    summary = json.loads([line for line in capsys.readouterr().out.splitlines() if line.strip()][-1])
    assert rc == 0
    assert summary["repo_name"] == repo_name
    return repo_name


def _run(ns, capsys):
    rc = relate.run(ns)
    captured = capsys.readouterr()
    return rc, json.loads(captured.out), captured.err


def _ns(repo, verb, query="", **kwargs):
    data = {"repo": repo, "relate_verb": verb, "query": query, "top_k": 10, "hops": 1}
    data.update(kwargs)
    return argparse.Namespace(**data)


def test_relate_missing_repo_returns_clean_code_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    rc = relate.run(_ns("missing", "callers", "x"))

    assert rc == 2
    assert "No index found for repo 'missing'." in capsys.readouterr().err


def test_relate_legacy_schema_returns_clean_code_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repo_dir = paths.repo_dir("legacy")
    conn = db.open_db(repo_dir / "index.sqlite")
    conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    conn.close()

    rc = relate.run(_ns("legacy", "callers", "x"))

    assert rc == 2
    assert "Detected an older codebase-vectorizer index" in capsys.readouterr().err


def test_callers_and_callees_use_symbol_edges_ranked_by_pagerank(indexed_graph, capsys):
    rc, callers, _ = _run(_ns(indexed_graph, "callers", "authenticate_user"), capsys)
    assert rc == 0
    assert callers["results"][0]["name"] == "pkg/router.py::_handle_login"
    assert callers["results"][0]["edge_kind"] == "calls"

    rc, callees, _ = _run(_ns(indexed_graph, "callees", "authenticate_user"), capsys)
    assert rc == 0
    assert callees["results"][0]["name"] == "pkg/db.py::fetch_one"
    assert callees["results"][0]["edge_kind"] == "calls"


def test_relate_run_accepts_direct_task_plan_namespace_shape(indexed_graph, capsys):
    ns = argparse.Namespace(repo=indexed_graph, verb="callers", args=["authenticate_user"], top_k=10, hops=1)

    rc, blob, _ = _run(ns, capsys)

    assert rc == 0
    assert blob["verb"] == "callers"
    assert blob["query"] == "authenticate_user"
    assert blob["results"][0]["name"] == "pkg/router.py::_handle_login"


def test_neighbors_and_graph_alias_walk_symbol_edges(indexed_graph, capsys):
    rc, blob, _ = _run(_ns(indexed_graph, "neighbors", "authenticate_user", hops=2), capsys)
    assert rc == 0
    assert [r["name"] for r in blob["results"]][:2] == [
        "pkg/router.py::_handle_login",
        "pkg/db.py::fetch_one",
    ]

    rc = graph_cmd.run(argparse.Namespace(repo=indexed_graph, query="authenticate_user", hops=1, top_k=10))
    alias_blob = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert alias_blob["verb"] == "neighbors"


def test_pagerank_top_excludes_block_nodes(indexed_graph, capsys):
    rc, blob, _ = _run(_ns(indexed_graph, "pagerank-top", "", top_k=3), capsys)

    assert rc == 0
    assert [r["name"] for r in blob["results"]] == [
        "pkg/auth.py::authenticate_user",
        "pkg/router.py::_handle_login",
        "pkg/db.py::fetch_one",
    ]


def test_shortest_path_between_symbols(indexed_graph, capsys):
    rc, blob, _ = _run(
        _ns(indexed_graph, "shortest-path", "pkg/router.py::_handle_login", target="fetch_one", hops=4),
        capsys,
    )

    assert rc == 0
    assert [r["name"] for r in blob["results"]] == [
        "pkg/router.py::_handle_login",
        "pkg/auth.py::authenticate_user",
        "pkg/db.py::fetch_one",
    ]


def test_concept_cluster_clean_fallback(indexed_graph, capsys):
    rc, blob, _ = _run(_ns(indexed_graph, "concept-cluster", "auth"), capsys)

    assert rc == 0
    assert blob["results"] == []
    assert "clusters not indexed" in blob["warnings"]


def test_concept_cluster_returns_member_chunks_ranked_by_membership(indexed_graph, capsys):
    conn = db.open_db(paths.repo_dir(indexed_graph) / "index.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO clusters (id, label, summary, centroid, size) "
            "VALUES (1, 'auth flows', 'Authentication entry points.', X'00', 1)"
        )
        conn.execute(
            "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (1, 1, 0.82)"
        )
    conn.close()

    rc, blob, _ = _run(_ns(indexed_graph, "concept-cluster", "auth"), capsys)

    assert rc == 0
    assert blob["warnings"] == []
    assert blob["results"][0]["label"] == "auth flows"
    assert blob["results"][0]["chunk_id"] == 1
    assert blob["results"][0]["file_path"] == "pkg/auth.py"
    assert blob["results"][0]["chunk_name"] == "authenticate_user"
    assert blob["results"][0]["membership"] == 0.82


def test_concept_cluster_falls_back_to_nearest_centroid(indexed_graph, monkeypatch, capsys):
    class FakeEmbedder:
        def embed(self, texts):
            return np.array([[0.95, 0.05, 0.0]], dtype="float32")

    monkeypatch.setattr(relate.embedder, "make_embedder", lambda: FakeEmbedder())

    conn = db.open_db(paths.repo_dir(indexed_graph) / "index.sqlite")
    with conn:
        conn.executemany(
            "INSERT INTO clusters (id, label, summary, centroid, size) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "payments", "Payment flows.", np.array([0.0, 1.0, 0.0], dtype="float32").tobytes(), 1),
                (2, "sessions", "Session handling.", np.array([1.0, 0.0, 0.0], dtype="float32").tobytes(), 1),
            ],
        )
        conn.executemany(
            "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (?, ?, ?)",
            [
                (3, 1, 0.93),
                (1, 2, 0.88),
            ],
        )
    conn.close()

    rc, blob, _ = _run(_ns(indexed_graph, "concept-cluster", "login", top_k=1), capsys)

    assert rc == 0
    assert blob["warnings"] == []
    assert blob["results"][0]["label"] == "sessions"
    assert blob["results"][0]["chunk_id"] == 1
    assert blob["results"][0]["score"] > 0.9


def test_vectorize_writes_concept_clusters_meta_and_label_warnings(
    monkeypatch,
    tmp_path,
    capsys,
):
    source_name = "clustered"
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    source_dir = tmp_path / source_name
    source_dir.mkdir()
    (source_dir / "auth.py").write_text("def authenticate_user():\n    return True\n", encoding="utf-8")
    (source_dir / "session.py").write_text("def create_session():\n    return 'token'\n", encoding="utf-8")
    (source_dir / "other.py").write_text("def unrelated():\n    return None\n", encoding="utf-8")

    def fake_cluster_embeddings(embeddings, **kwargs):
        return clusters.ClusterResult(
            labels=[0, 0, -1],
            memberships=[0.91, 0.83, 0.0],
            reduced=np.zeros((len(embeddings), 2), dtype="float32"),
        )

    class FailingLabeler:
        def label(self, samples):
            raise RuntimeError("offline")

    monkeypatch.setattr(vec_cmd.clusters, "cluster_embeddings", fake_cluster_embeddings)
    monkeypatch.setattr(vec_cmd.clusters, "LocalLLMClusterLabeler", FailingLabeler)

    ns = argparse.Namespace(
        source=str(source_dir),
        output_dir=None,
        max_file_mb=1.5,
        no_cache=True,
        update=False,
    )
    rc = vec_cmd.run(ns)
    summary = json.loads([line for line in capsys.readouterr().out.splitlines() if line.strip()][-1])

    conn = db.open_db(paths.repo_dir(source_name) / "index.sqlite")
    try:
        cluster_rows = conn.execute("SELECT id, label, summary, size, centroid FROM clusters").fetchall()
        member_rows = conn.execute(
            "SELECT chunk_id, cluster_id, membership FROM chunk_clusters ORDER BY membership DESC"
        ).fetchall()
        total_clusters = db.read_meta(conn, "total_clusters")
    finally:
        conn.close()
    manifest = json.loads((paths.repo_dir(source_name) / "manifest.json").read_text())

    assert rc == 0
    assert summary["clusters_indexed"] == 1
    assert summary["warnings"] == manifest["warnings"]
    assert any("LLM cluster labeling failed; used deterministic label: offline" in w for w in summary["warnings"])
    assert total_clusters == "1"
    assert len(cluster_rows) == 1
    assert cluster_rows[0][3] == 2
    assert np.frombuffer(cluster_rows[0][4], dtype="float32").shape == (1536,)
    assert len(member_rows) == 2
    assert all(row[2] > 0.1 for row in member_rows)


def test_flow_alias_clean_fallback(indexed_graph, capsys):
    rc = flow_cmd.run(argparse.Namespace(repo=indexed_graph, query="authenticate_user", top_k=10))

    assert rc == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["verb"] == "paths-through"
    assert blob["results"] == []
    assert "flow not indexed" in blob["warnings"]


def test_vectorize_indexes_flow_heavy_fixture_blocks_edges_and_meta(indexed_flow):
    repo = indexed_flow["repo"]
    summary = indexed_flow["summary"]
    conn = db.open_db(paths.repo_dir(repo) / "index.sqlite")
    try:
        function_id = conn.execute(
            "SELECT id FROM nodes WHERE kind = 'function' AND name = 'flow_app.py::decide'"
        ).fetchone()[0]
        block_rows = conn.execute(
            "SELECT id, name, short_name, parent_id, start_line, signature "
            "FROM nodes WHERE kind = 'block' AND file_path = 'flow_app.py' "
            "ORDER BY start_line, id"
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT edge.kind, edge.weight, edge.metadata, src.name, dst.name "
            "FROM edges edge "
            "JOIN nodes src ON src.id = edge.src "
            "JOIN nodes dst ON dst.id = edge.dst "
            "WHERE edge.kind IN ('controls', 'dataflow', 'guards') "
            "ORDER BY edge.kind, src.start_line, dst.start_line"
        ).fetchall()
        nodes_block = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'block'"
        ).fetchone()[0]
        edges_flow = conn.execute(
            "SELECT COUNT(*) FROM edges WHERE kind IN ('controls', 'dataflow', 'guards')"
        ).fetchone()[0]
        meta_nodes_block = db.read_meta(conn, "total_nodes_block")
        meta_edges_flow = db.read_meta(conn, "total_edges_flow")
    finally:
        conn.close()

    assert block_rows
    assert all(row[3] == function_id for row in block_rows)
    assert {"block_1", "block_2", "block_3"}.issubset({row[2] for row in block_rows})

    weights_by_kind = {row[0]: row[1] for row in edge_rows}
    assert weights_by_kind["controls"] == 0.5
    assert weights_by_kind["dataflow"] == 0.7
    assert weights_by_kind["guards"] == 0.3
    assert any(row[0] == "guards" and "user.is_admin" in (row[2] or "") for row in edge_rows)
    assert any(row[0] == "dataflow" and '"variable": "approved"' in (row[2] or "") for row in edge_rows)
    assert summary["nodes_block"] == nodes_block
    assert summary["edges_flow"] == edges_flow
    assert meta_nodes_block == str(nodes_block)
    assert meta_edges_flow == str(edges_flow)


def test_vectorize_indexes_tier_a_flow_fixture_blocks(indexed_flow):
    repo = indexed_flow["repo"]
    conn = db.open_db(paths.repo_dir(repo) / "index.sqlite")
    try:
        rows = conn.execute(
            "SELECT file_path, COUNT(*) FROM nodes "
            "WHERE kind = 'block' "
            "AND file_path IN ('flow_app.py', 'js_flow.js', 'ts_flow.ts', 'go_flow.go') "
            "GROUP BY file_path"
        ).fetchall()
        edge_rows = conn.execute(
            "SELECT src.file_path, edge.kind FROM edges edge "
            "JOIN nodes src ON src.id = edge.src "
            "WHERE edge.kind IN ('controls', 'guards', 'dataflow') "
            "AND src.file_path IN ('flow_app.py', 'js_flow.js', 'ts_flow.ts', 'go_flow.go')"
        ).fetchall()
    finally:
        conn.close()

    block_counts = {row[0]: row[1] for row in rows}
    assert {"flow_app.py", "js_flow.js", "ts_flow.ts", "go_flow.go"} <= set(block_counts)
    controls_by_file = {row[0] for row in edge_rows if row[1] == "controls"}
    assert {"flow_app.py", "js_flow.js", "ts_flow.ts", "go_flow.go"} <= controls_by_file


@pytest.mark.parametrize(
    ("verb", "query", "expected_kinds"),
    [
        ("paths-through", "decide", {"controls", "guards", "dataflow"}),
        ("reaching-definitions", "approved", {"dataflow"}),
        ("reachable-uses", "approved", {"dataflow"}),
        ("conditions-for", "approved", {"guards", "dataflow"}),
    ],
)
def test_flow_relate_verbs_return_indexed_flow_json(
    indexed_flow,
    capsys,
    verb,
    query,
    expected_kinds,
):
    rc, blob, _ = _run(_ns(indexed_flow["repo"], verb, query), capsys)

    assert rc == 0
    assert blob["warnings"] == []
    assert blob["results"]
    returned_kinds = {result["edge_kind"] for result in blob["results"]}
    assert returned_kinds & expected_kinds
    first = blob["results"][0]
    assert {"src", "dst", "function", "edge_kind", "metadata", "weight"}.issubset(first)
    assert first["function"]["name"] == "flow_app.py::decide"
    assert first["src"]["file_path"] == "flow_app.py"
    assert first["dst"]["file_path"] == "flow_app.py"
    assert first["file_relative"] == "flow_app.py"
    assert isinstance(first["path"], list)
    assert isinstance(first["guards"], list)
    assert isinstance(first["variables"], list)
    assert first["score"] == 1.0

    if "dataflow" in expected_kinds:
        assert any(
            result["edge_kind"] == "dataflow"
            and result["metadata"].get("variable") == "approved"
            for result in blob["results"]
        )
    if "guards" in expected_kinds:
        if verb == "conditions-for":
            assert any(
                result["edge_kind"] == "dataflow"
                and "user.is_admin" in json.dumps(result["guards"])
                for result in blob["results"]
            )
        else:
            assert any(
                result["edge_kind"] == "guards"
                and "user.is_admin" in json.dumps(result["metadata"])
                for result in blob["results"]
            )


def test_flow_relate_verbs_return_semantic_paths_and_slices(
    monkeypatch,
    tmp_path,
    capsys,
):
    repo = _index_source_tree(
        monkeypatch,
        tmp_path,
        capsys,
        "branch-flow",
        {
            "branch.py": (
                "def choose(flag):\n"
                "    x = 0\n"
                "    if flag:\n"
                "        x = 1\n"
                "    return x\n"
            )
        },
    )

    rc, paths_blob, _ = _run(
        _ns(repo, "paths-through", "choose", target="2:5", hops=6),
        capsys,
    )
    assert rc == 0
    assert paths_blob["warnings"] == []
    assert any(
        result["path"][0] == "entry"
        and result["path"][-1] == "exit"
        and len(result["path"]) >= 4
        and "flag" in result["guards"]
        for result in paths_blob["results"]
    )

    rc, out_of_range_blob, _ = _run(
        _ns(repo, "paths-through", "choose", target="99:100", hops=6),
        capsys,
    )
    assert rc == 0
    assert out_of_range_blob["warnings"] == []
    assert out_of_range_blob["results"] == []

    rc, reaching_blob, _ = _run(_ns(repo, "reaching-definitions", "x@5"), capsys)
    assert rc == 0
    reaching_lines = {
        result["metadata"].get("definition_line")
        for result in reaching_blob["results"]
        if result["edge_kind"] == "dataflow"
    }
    assert reaching_lines == {2, 4}
    assert all(len(result["path"]) >= 2 for result in reaching_blob["results"])

    rc, uses_blob, _ = _run(_ns(repo, "reachable-uses", "x@2"), capsys)
    assert rc == 0
    assert any(
        result["metadata"].get("use_line") == 5
        and result["path"][-1].startswith("block_")
        for result in uses_blob["results"]
    )

    rc, conditions_blob, _ = _run(_ns(repo, "conditions-for", "x@5"), capsys)
    assert rc == 0
    assert any(
        "flag" in result["guards"] and "x" in result["variables"]
        for result in conditions_blob["results"]
    )
    assert all(
        result["src"]["short_name"] in result["path"]
        and result["dst"]["short_name"] in result["path"]
        for result in conditions_blob["results"]
    )
    assert any(
        result["metadata"].get("definition_line") == 4
        and result["path"].index(result["src"]["short_name"])
        < result["path"].index(result["dst"]["short_name"])
        and "flag" in result["guards"]
        for result in conditions_blob["results"]
    )

    rc, symbol_conditions_blob, _ = _run(_ns(repo, "conditions-for", "x", hops=6), capsys)
    assert rc == 0
    assert symbol_conditions_blob["warnings"] == []
    assert symbol_conditions_blob["results"]
    assert all(
        result["edge_kind"] == "dataflow"
        and result["src"]["short_name"] in result["path"]
        and result["dst"]["short_name"] in result["path"]
        for result in symbol_conditions_blob["results"]
    )
    assert any(
        result["metadata"].get("definition_line") == 4
        and "flag" in result["guards"]
        for result in symbol_conditions_blob["results"]
    )


def test_flow_dataflow_metadata_aggregates_duplicate_logical_edges(
    monkeypatch,
    tmp_path,
    capsys,
):
    repo = _index_source_tree(
        monkeypatch,
        tmp_path,
        capsys,
        "same-edge-flow",
        {
            "pairs.py": (
                "def pair(left_source, right_source):\n"
                "    left, right = left_source, right_source\n"
                "    return left + right\n"
            )
        },
    )

    conn = db.open_db(paths.repo_dir(repo) / "index.sqlite")
    try:
        rows = conn.execute(
            "SELECT edge.metadata "
            "FROM edges edge "
            "JOIN nodes src ON src.id = edge.src "
            "JOIN nodes dst ON dst.id = edge.dst "
            "WHERE edge.kind = 'dataflow' "
            "AND src.name = 'pairs.py::pair#block_1' "
            "AND dst.name = 'pairs.py::pair#block_2'"
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    metadata = json.loads(rows[0][0])
    assert {item["variable"] for item in metadata["items"]} == {"left", "right"}

    rc, left_blob, _ = _run(_ns(repo, "reaching-definitions", "left"), capsys)
    assert rc == 0
    assert any("left" in json.dumps(result["metadata"]) for result in left_blob["results"])

    rc, right_blob, _ = _run(_ns(repo, "reaching-definitions", "right"), capsys)
    assert rc == 0
    assert any("right" in json.dumps(result["metadata"]) for result in right_blob["results"])


def test_flow_metadata_exact_match_is_not_lost_after_substring_prefilter_limit(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repo_dir = paths.repo_dir("metadata-limit")
    conn = db.open_db(repo_dir / "index.sqlite")
    db.init_schema(conn)
    db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
    with conn:
        conn.execute(
            "INSERT INTO nodes "
            "(id, kind, name, short_name, file_path, start_line, end_line) "
            "VALUES (1, 'function', 'pkg/flow.py::choose', 'choose', 'pkg/flow.py', 1, 120)"
        )
        node_rows = []
        edge_rows = []
        next_id = 2
        for idx in range(8):
            src_id = next_id
            dst_id = next_id + 1
            next_id += 2
            start_line = 2 + (idx * 2)
            node_rows.extend(
                [
                    (
                        src_id,
                        "block",
                        f"pkg/flow.py::choose#decoy_src_{idx}",
                        f"decoy_src_{idx}",
                        "pkg/flow.py",
                        start_line,
                        start_line,
                        1,
                    ),
                    (
                        dst_id,
                        "block",
                        f"pkg/flow.py::choose#decoy_dst_{idx}",
                        f"decoy_dst_{idx}",
                        "pkg/flow.py",
                        start_line + 1,
                        start_line + 1,
                        1,
                    ),
                ]
            )
            edge_rows.append(
                (
                    src_id,
                    dst_id,
                    "dataflow",
                    0.7,
                    json.dumps(
                        {
                            "variable": f"x_decoy_{idx}",
                            "definition_line": start_line,
                            "use_line": start_line + 1,
                        },
                        sort_keys=True,
                    ),
                )
            )
        node_rows.extend(
            [
                (
                    next_id,
                    "block",
                    "pkg/flow.py::choose#exact_src",
                    "exact_src",
                    "pkg/flow.py",
                    100,
                    100,
                    1,
                ),
                (
                    next_id + 1,
                    "block",
                    "pkg/flow.py::choose#exact_dst",
                    "exact_dst",
                    "pkg/flow.py",
                    101,
                    101,
                    1,
                ),
            ]
        )
        edge_rows.append(
            (
                next_id,
                next_id + 1,
                "dataflow",
                0.7,
                json.dumps(
                    {
                        "variable": "x",
                        "definition_line": 100,
                        "use_line": 101,
                    },
                    sort_keys=True,
                ),
            )
        )
        conn.executemany(
            "INSERT INTO nodes "
            "(id, kind, name, short_name, file_path, start_line, end_line, parent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            node_rows,
        )
        conn.executemany(
            "INSERT INTO edges (src, dst, kind, weight, metadata) VALUES (?, ?, ?, ?, ?)",
            edge_rows,
        )
    conn.close()

    for verb in ("reaching-definitions", "conditions-for"):
        rc, blob, _ = _run(_ns("metadata-limit", verb, "x", top_k=1, hops=4), capsys)

        assert rc == 0
        assert [result["metadata"].get("variable") for result in blob["results"]] == ["x"]


def test_vectorize_warns_when_flow_extraction_returns_no_blocks_for_supported_function(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    source_dir = tmp_path / "flow-warning"
    source_dir.mkdir()
    (source_dir / "broken.py").write_text(
        "def broken():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    real_extract_flow = vec_cmd.flow.extract_flow

    def empty_flow(language, file_path, source):
        if file_path == "broken.py":
            return [], []
        return real_extract_flow(language, file_path, source)

    monkeypatch.setattr(vec_cmd.flow, "extract_flow", empty_flow)

    ns = argparse.Namespace(
        source=str(source_dir),
        output_dir=None,
        max_file_mb=1.5,
        no_cache=True,
        update=False,
    )
    rc = vec_cmd.run(ns)
    summary = json.loads([line for line in capsys.readouterr().out.splitlines() if line.strip()][-1])

    conn = db.open_db(paths.repo_dir("flow-warning") / "index.sqlite")
    try:
        file_rows = conn.execute(
            "SELECT kind, name FROM nodes WHERE name = 'broken.py'"
        ).fetchall()
        function_rows = conn.execute(
            "SELECT kind, name FROM nodes WHERE name = 'broken.py::broken'"
        ).fetchall()
        block_rows = conn.execute(
            "SELECT name FROM nodes WHERE kind = 'block' AND file_path = 'broken.py'"
        ).fetchall()
        orphan_blocks = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'block' AND parent_id IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    assert rc == 0
    assert any(
        warning.startswith("flow extraction produced no blocks for broken.py")
        for warning in summary["warnings"]
    )
    assert file_rows == [("file", "broken.py")]
    assert function_rows == [("function", "broken.py::broken")]
    assert block_rows == []
    assert orphan_blocks == 0


def test_vectorize_warns_when_flow_nodes_are_skipped_for_missing_parent_symbol(
    monkeypatch,
    tmp_path,
    capsys,
):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    source_dir = tmp_path / "flow-parent-warning"
    source_dir.mkdir()
    (source_dir / "kept.py").write_text(
        "def kept():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    def mismatched_flow(language, file_path, source):
        return [
            vec_cmd.flow.FlowNode(
                name=f"{file_path}::missing#block_1",
                short_name="block_1",
                file_path=file_path,
                start_line=2,
                end_line=2,
                signature="return 1",
                parent_symbol=f"{file_path}::missing",
            )
        ], []

    monkeypatch.setattr(vec_cmd.flow, "extract_flow", mismatched_flow)

    ns = argparse.Namespace(
        source=str(source_dir),
        output_dir=None,
        max_file_mb=1.5,
        no_cache=True,
        update=False,
    )
    rc = vec_cmd.run(ns)
    summary = json.loads([line for line in capsys.readouterr().out.splitlines() if line.strip()][-1])

    conn = db.open_db(paths.repo_dir("flow-parent-warning") / "index.sqlite")
    try:
        function_rows = conn.execute(
            "SELECT kind, name FROM nodes WHERE name = 'kept.py::kept'"
        ).fetchall()
        block_rows = conn.execute(
            "SELECT name FROM nodes WHERE kind = 'block' AND file_path = 'kept.py'"
        ).fetchall()
        orphan_blocks = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE kind = 'block' AND parent_id IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    assert rc == 0
    assert function_rows == [("function", "kept.py::kept")]
    assert block_rows == []
    assert orphan_blocks == 0
    assert any(
        warning.startswith("flow nodes skipped for kept.py: 1 missing parent symbol")
        for warning in summary["warnings"]
    )


def test_flow_blocks_parent_to_method_and_nested_function_symbols(
    monkeypatch,
    tmp_path,
    capsys,
):
    repo = _index_source_tree(
        monkeypatch,
        tmp_path,
        capsys,
        "scope-flow",
        {
            "scopes.py": (
                "class Alpha:\n"
                "    def render(self, value):\n"
                "        local = value\n"
                "        return local\n"
                "\n"
                "class Beta:\n"
                "    def render(self, value):\n"
                "        local = value\n"
                "        return local\n"
                "\n"
                "def outer(value):\n"
                "    def inner(delta):\n"
                "        result = value + delta\n"
                "        return result\n"
                "    return inner(value)\n"
            )
        },
    )

    conn = db.open_db(paths.repo_dir(repo) / "index.sqlite")
    try:
        symbol_rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT name, id FROM nodes "
                "WHERE kind IN ('function', 'method') "
                "AND name IN (?, ?, ?)",
                (
                    "scopes.py::Alpha::render",
                    "scopes.py::Beta::render",
                    "scopes.py::outer::inner",
                ),
            ).fetchall()
        }
        block_rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT name, parent_id FROM nodes "
                "WHERE kind = 'block' "
                "AND name IN (?, ?, ?)",
                (
                    "scopes.py::Alpha::render#block_1",
                    "scopes.py::Beta::render#block_1",
                    "scopes.py::outer::inner#block_1",
                ),
            ).fetchall()
        }
        legacy_method_blocks = conn.execute(
            "SELECT COUNT(*) FROM nodes "
            "WHERE kind = 'block' AND name = 'scopes.py::render#block_1'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert block_rows["scopes.py::Alpha::render#block_1"] == symbol_rows["scopes.py::Alpha::render"]
    assert block_rows["scopes.py::Beta::render#block_1"] == symbol_rows["scopes.py::Beta::render"]
    assert block_rows["scopes.py::outer::inner#block_1"] == symbol_rows["scopes.py::outer::inner"]
    assert symbol_rows["scopes.py::Alpha::render"] != symbol_rows["scopes.py::Beta::render"]
    assert legacy_method_blocks == 0


def test_flow_queries_return_indexed_flow_edges(indexed_graph, capsys):
    conn = db.open_db(paths.repo_dir(indexed_graph) / "index.sqlite")
    with conn:
        conn.execute(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, chunk_id, pagerank) "
            "VALUES (7, 'block', 'pkg/auth.py::authenticate_user#return', 'return', 'pkg/auth.py', 1, 0.0)"
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (6, 7, 'controls', 1.0)"
        )
    conn.close()

    rc, blob, _ = _run(_ns(indexed_graph, "paths-through", "pkg/auth.py::authenticate_user#if"), capsys)

    assert rc == 0
    assert blob["warnings"] == []
    assert blob["results"][0]["name"] == "pkg/auth.py::authenticate_user#return"
    assert blob["results"][0]["edge_kind"] == "controls"


def test_paths_through_function_returns_child_block_flow_edges(indexed_graph, capsys):
    conn = db.open_db(paths.repo_dir(indexed_graph) / "index.sqlite")
    with conn:
        conn.execute("UPDATE nodes SET parent_id = 1 WHERE id = 6")
        conn.execute(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, parent_id, chunk_id, pagerank) "
            "VALUES (7, 'block', 'pkg/auth.py::authenticate_user#return', 'return', 'pkg/auth.py', 1, 1, 0.0)"
        )
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (6, 7, 'controls', 1.0)"
        )
    conn.close()

    rc, blob, _ = _run(_ns(indexed_graph, "paths-through", "authenticate_user"), capsys)

    assert rc == 0
    assert blob["warnings"] == []
    assert blob["results"][0]["name"] == "pkg/auth.py::authenticate_user#return"
    assert blob["results"][0]["edge_kind"] == "controls"


def test_inheritance_chain_deduplicates_duplicate_ancestors(indexed_graph, capsys):
    conn = db.open_db(paths.repo_dir(indexed_graph) / "index.sqlite")
    with conn:
        conn.executemany(
            "INSERT INTO nodes (id, kind, name, short_name, file_path, chunk_id, pagerank) "
            "VALUES (?, 'class', ?, ?, ?, NULL, 0.0)",
            [
                (8, "pkg/mixin.py::AuthMixin", "AuthMixin", "pkg/mixin.py"),
                (9, "pkg/root.py::RootAuth", "RootAuth", "pkg/root.py"),
            ],
        )
        conn.executemany(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'inherits', ?)",
            [
                (5, 8, 1.0),
                (4, 9, 1.0),
                (8, 9, 1.0),
            ],
        )
    conn.close()

    rc, blob, _ = _run(_ns(indexed_graph, "inheritance-chain", "TokenAuth"), capsys)

    assert rc == 0
    assert [r["name"] for r in blob["results"]].count("pkg/root.py::RootAuth") == 1


@pytest.mark.parametrize("verb", ALL_RELATE_VERBS)
def test_all_verbs_return_consistent_json_shape(indexed_graph, verb, capsys):
    kwargs = {"target": "fetch_one"} if verb == "shortest-path" else {}
    query = "" if verb == "pagerank-top" else "authenticate_user"

    rc, blob, _ = _run(_ns(indexed_graph, verb, query, **kwargs), capsys)

    assert rc == 0
    assert set(blob) == {"repo", "verb", "query", "results", "warnings"}
    assert blob["repo"] == indexed_graph
    assert blob["verb"] == verb
    assert isinstance(blob["results"], list)
    assert isinstance(blob["warnings"], list)
