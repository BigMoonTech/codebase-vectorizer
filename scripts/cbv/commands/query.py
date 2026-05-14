"""`query` verb — BM25 + dense + RRF retrieval.

Slice 1 implements only the spec's "full lane" minus rerank/graph/clusters:
  Stage 1 (parallel seed in spec; sequential here):
    - BM25 top-50 over chunks_fts
    - dense top-50 over vec_chunks
  Stage 2:
    - Reciprocal Rank Fusion (k=60 constant per RRF paper) of the two lists
  Stage 3-6: deferred to later slices.

Slices that extend this command:
  Slice 3 — graph expansion + symbol-exact seed
  Slice 4 — fast lane + query router
  Slice 5 — cross-encoder rerank
  Slice 6 — Personalized PageRank
  Slice 15 — confidence + refined_queries hints
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

from cbv import db, embedder, paths, quantize

RRF_K = 60  # standard RRF damping constant


def run(ns: argparse.Namespace) -> int:
    repo_dir = paths.find_repo(ns.repo)
    if repo_dir is None:
        print(
            f"No index found for repo {ns.repo!r}. "
            f"Run `run.sh list` to see available indexes, or `run.sh "
            f"vectorize <url|path>` to create one.",
            file=sys.stderr,
        )
        return 2

    db_path = repo_dir / "index.sqlite"
    conn = db.open_db(db_path)
    try:
        db.assert_schema_v1(conn)
    except db.LegacySchemaError as e:
        print(str(e), file=sys.stderr)
        return 2

    # Stage 1a: BM25.
    bm25_hits = _bm25(conn, ns.question, limit=50)

    # Stage 1b: dense (uses vec_int8 SQL function per sqlite-vec 0.1.x).
    emb = embedder.make_embedder()
    qv = emb.embed([ns.question])[0]
    q_int8 = quantize.quantize_int8(qv.reshape(1, -1))[0]
    dense_hits = _dense(conn, q_int8, limit=50)

    # Stage 2: RRF fuse.
    fused = _rrf([bm25_hits, dense_hits], k=RRF_K)
    top = fused[: ns.top_k]

    # Materialize result rows.
    results = []
    for rank, (chunk_id, score, sources) in enumerate(top, start=1):
        row = conn.execute(
            "SELECT file_path, kind, name, start_line, end_line, content "
            "FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            continue
        file_rel, kind, name, sl, el, content = row
        file_abs = (repo_dir / "source" / file_rel).resolve()
        results.append({
            "rank": rank,
            "file_absolute": str(file_abs),
            "file_relative": file_rel,
            "start_line": sl,
            "end_line": el,
            "kind": kind,
            "name": name,
            "score": round(float(score), 4),
            "preview": (content[:200] + "…") if len(content) > 200 else content,
            "why_this_was_returned": "+".join(sorted(sources)),
        })

    blob = {
        "repo": ns.repo,
        "query": ns.question,
        "repo_dir": str(repo_dir),
        "pipeline_used": "full",
        "results": results,
        "refined_queries": [],   # Slice 15
        "expansion_size": 0,      # Slice 3
    }
    print(json.dumps(blob), flush=True)
    conn.close()
    return 0


def _bm25(conn, query: str, *, limit: int) -> Dict[int, float]:
    """Return {chunk_id: bm25 rank-score} for top BM25 hits."""
    rows = conn.execute(
        "SELECT rowid, bm25(chunks_fts) FROM chunks_fts "
        "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
        (_fts_escape(query), limit),
    ).fetchall()
    return {int(r[0]): float(r[1]) for r in rows}


def _fts_escape(query: str) -> str:
    """Wrap each whitespace-split token in double quotes so FTS5 treats them as
    literal terms (no syntax injection through user input)."""
    parts = [p for p in query.split() if p]
    if not parts:
        return '""'
    quoted = ['"' + p.replace('"', '""') + '"' for p in parts]
    return " OR ".join(quoted)


def _dense(conn, q_int8: np.ndarray, *, limit: int) -> Dict[int, float]:
    """Return {chunk_id: -distance} for top sqlite-vec KNN hits.

    Inverts distance so 'higher is better' is consistent with BM25 ordering
    (where smaller bm25 = better). The RRF fuse normalizes via rank order
    so absolute scales don't matter.

    Uses `vec_int8(?)` with a JSON string for the query vector because
    sqlite-vec 0.1.x rejects raw INT8 bytes (interpreted as float32).
    """
    qparam = db.vec_int8_param(q_int8)  # JSON string, NOT raw bytes
    rows = conn.execute(
        "SELECT chunk_id, distance FROM vec_chunks "
        "WHERE embedding MATCH vec_int8(?) AND k = ? ORDER BY distance",
        (qparam, limit),
    ).fetchall()
    return {int(r[0]): -float(r[1]) for r in rows}


def _rrf(rankings: List[Dict[int, float]], *, k: int) -> List[tuple]:
    """Reciprocal Rank Fusion. Sources is a tag list per chunk for debug."""
    SOURCE_NAMES = ["bm25", "dense"]
    aggregate: Dict[int, float] = {}
    sources: Dict[int, list] = {}
    for tag, ranking in zip(SOURCE_NAMES, rankings):
        if tag == "bm25":
            sorted_ids = [cid for cid, _ in sorted(ranking.items(), key=lambda kv: kv[1])]
        else:
            sorted_ids = [cid for cid, _ in sorted(ranking.items(), key=lambda kv: -kv[1])]
        for rank, cid in enumerate(sorted_ids, start=1):
            aggregate[cid] = aggregate.get(cid, 0.0) + 1.0 / (k + rank)
            sources.setdefault(cid, []).append(tag)
    fused = sorted(
        ((cid, score, sources[cid]) for cid, score in aggregate.items()),
        key=lambda t: -t[1],
    )
    return fused
