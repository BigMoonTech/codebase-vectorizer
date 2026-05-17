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
