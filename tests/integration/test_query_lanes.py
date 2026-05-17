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


def _query_blob(capsys) -> dict:
    out = capsys.readouterr().out
    return json.loads([line for line in out.strip().splitlines() if line.strip()][-1])


def test_fast_lane_returns_fast_without_loading_dense_embedder(indexed, capsys, monkeypatch):
    def fail_make_embedder():
        raise AssertionError("fast lane must not load dense embedder")

    monkeypatch.setattr(query_cmd.embedder, "make_embedder", fail_make_embedder)

    ns = argparse.Namespace(
        repo=indexed,
        question="authenticate_user",
        top_k=5,
        lane="fast",
    )
    rc = query_cmd.run(ns)
    assert rc == 0
    blob = _query_blob(capsys)
    assert blob["pipeline_used"] == "fast"
    assert blob["expansion_size"] == 0
    assert blob["results"]


def test_auto_identifier_query_uses_fast_lane_without_loading_dense_embedder(
    indexed,
    capsys,
    monkeypatch,
):
    def fail_make_embedder():
        raise AssertionError("auto identifier fast lane must not load dense embedder")

    monkeypatch.setattr(query_cmd.embedder, "make_embedder", fail_make_embedder)

    ns = argparse.Namespace(
        repo=indexed,
        question="authenticate_user",
        top_k=5,
        lane="auto",
    )
    rc = query_cmd.run(ns)
    assert rc == 0
    blob = _query_blob(capsys)
    assert blob["pipeline_used"] == "fast"
    assert blob["expansion_size"] == 0
    assert blob["results"]


def test_full_lane_uses_graph_expansion(indexed, capsys):
    ns = argparse.Namespace(
        repo=indexed,
        question="how does login authenticate users",
        top_k=5,
        lane="full",
    )
    rc = query_cmd.run(ns)
    assert rc == 0
    blob = _query_blob(capsys)
    assert blob["pipeline_used"] == "full"
    assert blob["expansion_size"] > 0
    assert blob["results"]
    assert any(
        "ppr" in r["why_this_was_returned"]
        for r in blob["results"]
    )


def test_full_lane_ppr_uses_seed_plus_expansion_as_bounded_candidates(
    indexed,
    capsys,
    monkeypatch,
):
    captured = {}

    def fake_personalized_pagerank(
        conn,
        seed_chunk_ids,
        *,
        expansion_chunk_ids=None,
        candidate_chunk_ids=None,
        iterations=10,
    ):
        captured["seed"] = list(seed_chunk_ids)
        captured["expansion"] = list(expansion_chunk_ids or [])
        captured["candidates"] = list(candidate_chunk_ids or [])
        return {chunk_id: 1.0 for chunk_id in captured["candidates"]}

    monkeypatch.setattr(
        query_cmd.graph,
        "personalized_pagerank",
        fake_personalized_pagerank,
    )

    ns = argparse.Namespace(
        repo=indexed,
        question="how does login authenticate users",
        top_k=5,
        lane="full",
    )
    rc = query_cmd.run(ns)
    assert rc == 0
    blob = _query_blob(capsys)
    assert blob["expansion_size"] > 0
    assert captured["seed"]
    assert captured["expansion"]
    assert set(captured["candidates"]) == set(captured["seed"]) | set(captured["expansion"])


def test_full_lane_keeps_a_source_chunk_above_a_swarm_of_docs(tmp_path, monkeypatch):
    """A lone source chunk must survive a candidate pool flooded with docs."""
    import argparse
    import io
    import json
    import sys
    from cbv import db, embedder, quantize
    from cbv.commands import query as Q
    from cbv import paths

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    monkeypatch.setenv("CBV_STUB_RERANKER", "1")
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repo_dir = paths.repo_dir("polltest")
    repo_dir.mkdir(parents=True, exist_ok=True)
    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        db.init_schema(conn)
        emb = embedder.make_embedder()
        # The source chunk shares only a couple of query tokens, so it is
        # lexically far weaker than the docs swarm. Each docs chunk's content
        # is EXACTLY EQUAL to the query string -> identical stub embedding
        # (distance 0) and a perfect BM25 match. Pre-Task-9, the category-blind
        # top-50 BM25/dense lanes are entirely filled by docs and the source
        # chunk never enters the candidate pool.
        rows = [("src/clusters.py", "source", "codebase call entrypoint helper")]
        rows += [
            (f"docs/plan_{i}.md", "docs", "how does the codebase call things")
            for i in range(60)
        ]
        for cid, (fp, cat, content) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python" if cat == "source" else "markdown", "window",
                 None, None, 1, 1, 0, len(content), content, f"h{cid}",
                 len(content.split()), cat),
            )
            q8 = quantize.quantize_int8(emb.embed([content])[0].reshape(1, -1))[0]
            db.insert_embedding(conn, cid, q8)
        db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
        conn.commit()
    finally:
        conn.close()

    ns = argparse.Namespace(
        repo="polltest", question="how does the codebase call things",
        # top_k=100 returns the whole 61-chunk candidate pool. Task 9 is a
        # pool-composition fix, so this test verifies pool membership. The stub
        # reranker scores by naive lexical overlap and would rank the docs
        # swarm above the source chunk; a smaller top_k would truncate the
        # source away and mask whether tiering put it in the pool at all.
        lane="full", top_k=100,
    )
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = Q.run(ns)
    finally:
        sys.stdout = old
    assert rc == 0
    result = json.loads(buf.getvalue().strip().splitlines()[-1])
    files = [r["file_relative"] for r in result["results"]]
    assert "src/clusters.py" in files


def test_symbol_exact_excludes_vendor_chunks(tmp_path, monkeypatch):
    """_symbol_exact must not return chunks whose category is 'vendor'."""
    from cbv import db
    from cbv.commands import query as Q

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    conn = db.open_db(tmp_path / "index.sqlite")
    try:
        db.init_schema(conn)
        # Two chunks — one 'source', one 'vendor' — both linked to the same symbol name.
        for cid, (fp, cat) in enumerate(
            [("src/thesymbol.py", "source"), ("vendor/thesymbol.py", "vendor")], start=1
        ):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python", "function", "Thesymbol", None, 1, 10, 0, 100,
                 "def Thesymbol(): pass", f"h{cid}", 4, cat),
            )
            # Insert a node for each chunk with matching name/short_name.
            conn.execute(
                "INSERT INTO nodes (id, kind, name, short_name, file_path, "
                "start_line, end_line, chunk_id) VALUES (?,?,?,?,?,?,?,?)",
                (cid, "function", "Thesymbol", "Thesymbol", fp, 1, 10, cid),
            )
        conn.commit()

        result = Q._symbol_exact(
            conn, "explain Thesymbol", limit=50,
            categories=Q.RETRIEVABLE_CATEGORIES,
        )
        # source chunk (id=1) must be present; vendor chunk (id=2) must be absent.
        assert 1 in result, "source chunk must be returned by _symbol_exact"
        assert 2 not in result, "vendor chunk must NOT be returned by _symbol_exact"
    finally:
        conn.close()


def test_symbol_exact_without_categories_does_not_filter(tmp_path, monkeypatch):
    """_symbol_exact without `categories` (the fast-lane default) must NOT
    filter — meta/vendor chunks are returned. This locks in the fast-lane
    behavior so the full-lane scoping can't be silently re-broken."""
    from cbv import db
    from cbv.commands import query as Q

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    conn = db.open_db(tmp_path / "index.sqlite")
    try:
        db.init_schema(conn)
        for cid, (fp, cat) in enumerate(
            [("src/thesymbol.py", "source"), ("vendor/thesymbol.py", "vendor")], start=1
        ):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python", "function", "Thesymbol", None, 1, 10, 0, 100,
                 "def Thesymbol(): pass", f"h{cid}", 4, cat),
            )
            conn.execute(
                "INSERT INTO nodes (id, kind, name, short_name, file_path, "
                "start_line, end_line, chunk_id) VALUES (?,?,?,?,?,?,?,?)",
                (cid, "function", "Thesymbol", "Thesymbol", fp, 1, 10, cid),
            )
        conn.commit()

        result = Q._symbol_exact(conn, "explain Thesymbol", limit=50)
        # No category filter -> both source and vendor chunks are returned.
        assert 1 in result, "source chunk must be returned"
        assert 2 in result, "vendor chunk must be returned when no category filter is set"
    finally:
        conn.close()


def test_graph_expand_excludes_meta_chunks(tmp_path, monkeypatch):
    """_graph_expand must not return neighbor chunks whose category is 'meta'."""
    from cbv import db
    from cbv.commands import query as Q

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    conn = db.open_db(tmp_path / "index.sqlite")
    try:
        db.init_schema(conn)
        # Three chunks: seed (source), meta neighbor, source neighbor.
        chunk_data = [
            (1, "src/seed.py", "source"),
            (2, ".claude/meta_thing.md", "meta"),
            (3, "src/neighbor.py", "source"),
        ]
        for cid, fp, cat in chunk_data:
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python", "function", f"sym{cid}", None, 1, 10, 0, 100,
                 f"def sym{cid}(): pass", f"h{cid}", 4, cat),
            )
            conn.execute(
                "INSERT INTO nodes (id, kind, name, short_name, file_path, "
                "start_line, end_line, chunk_id) VALUES (?,?,?,?,?,?,?,?)",
                (cid, "function", f"sym{cid}", f"sym{cid}", fp, 1, 10, cid),
            )
        # Edge from seed (node id=1) to meta neighbor (node id=2)
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?,?,?,?)",
            (1, 2, "calls", 1.0),
        )
        # Edge from seed (node id=1) to source neighbor (node id=3)
        conn.execute(
            "INSERT INTO edges (src, dst, kind, weight) VALUES (?,?,?,?)",
            (1, 3, "calls", 1.0),
        )
        conn.commit()

        result = Q._graph_expand(conn, [1])
        # source neighbor (chunk id=3) must be present; meta neighbor (chunk id=2) must not.
        assert 3 in result, "source neighbor chunk must be returned by _graph_expand"
        assert 2 not in result, "meta neighbor chunk must NOT be returned by _graph_expand"
    finally:
        conn.close()


def test_bm25_and_dense_accept_a_category_filter(tmp_path, monkeypatch):
    import numpy as np
    from cbv import db, embedder, quantize
    from cbv.commands import query as Q

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    conn = db.open_db(tmp_path / "index.sqlite")
    try:
        db.init_schema(conn)
        # one 'source' chunk and one 'docs' chunk, both containing "alpha"
        for cid, (fp, cat) in enumerate(
            [("a.py", "source"), ("b.md", "docs")], start=1
        ):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python", "window", None, None, 1, 1, 0, 5,
                 "alpha", f"h{cid}", 1, cat),
            )
            emb = embedder.make_embedder()
            q8 = quantize.quantize_int8(emb.embed(["alpha"])[0].reshape(1, -1))[0]
            db.insert_embedding(conn, cid, q8)
        conn.commit()

        bm25_all = Q._bm25(conn, "alpha", limit=50)
        bm25_src = Q._bm25(conn, "alpha", limit=50, categories={"source"})
        assert set(bm25_all) == {1, 2}
        assert set(bm25_src) == {1}

        emb = embedder.make_embedder()
        q8 = quantize.quantize_int8(emb.embed(["alpha"])[0].reshape(1, -1))[0]
        dense_src = Q._dense(conn, q8, limit=50, categories={"source"})
        assert set(dense_src) == {1}
    finally:
        conn.close()
