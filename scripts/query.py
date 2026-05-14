#!/usr/bin/env python3
"""Query an indexed codebase. Hybrid FTS5 + vector retrieval with RRF fusion.

Usage:
    python query.py <repo_name> "<query>" [--top-k 6]
    python query.py --list

Indexes are looked up in <data_home>/repos/<name>/ — a single canonical location
so queries work from any working directory.

Output is JSON to stdout:

    {
      "repo": "react",
      "query": "...",
      "repo_dir": "/abs/path/to/repos/react",
      "results": [
        {
          "rank": 1,
          "file_absolute": "/abs/path/.../foo.py",
          "file_relative": "foo.py",
          "start_line": 12, "end_line": 80,
          "kind": "function", "name": "useState",
          "score": 0.91,
          "preview": "first ~200 chars..."
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db import EMBEDDING_DIM, fts_search, get_chunk, get_meta, open_db, vec_search  # noqa: E402
from embedder import Embedder  # noqa: E402
from paths import find_repo, list_indexed_repos, repos_dir  # noqa: E402


RRF_K = 60  # Reciprocal Rank Fusion constant


def rrf_fuse(rankings: List[List[int]]) -> Dict[int, float]:
    scores: Dict[int, float] = {}
    for ranked in rankings:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def preview(text: str, n: int = 240) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rstrip() + "..."


def run_query(repo_name: str, query: str, top_k: int) -> dict:
    repo_dir = find_repo(repo_name)
    if repo_dir is None:
        available = [r.name for r in list_indexed_repos()]
        raise FileNotFoundError(
            f"No index found for repo {repo_name!r} at {repos_dir() / repo_name}. "
            f"Available repos: {available or '[]'}. Run vectorize-repo first."
        )

    db_path = repo_dir / "index.sqlite"
    source_dir = repo_dir / "source"

    conn = open_db(str(db_path))
    indexed_model = get_meta(conn, "embedding_model") or "BAAI/bge-small-en-v1.5"

    embedder = Embedder(indexed_model)
    if embedder.dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding dim mismatch: model returned {embedder.dim}, schema expects {EMBEDDING_DIM}."
        )
    query_vec = embedder.embed_one(query)

    pool = max(top_k * 4, 24)
    fts_results = fts_search(conn, query, pool)
    vec_results = vec_search(conn, query_vec, pool)

    fts_order = [cid for cid, _ in fts_results]
    vec_order = [cid for cid, _ in vec_results]
    fused = rrf_fuse([fts_order, vec_order])

    if not fused:
        return {"repo": repo_name, "query": query, "repo_dir": str(repo_dir), "results": []}

    ranked_ids = sorted(fused.keys(), key=lambda cid: -fused[cid])[:top_k]

    out_results = []
    for rank, cid in enumerate(ranked_ids, start=1):
        chunk = get_chunk(conn, cid)
        if chunk is None:
            continue
        rel = chunk["file_path"]
        abs_path = str((source_dir / rel).resolve())
        out_results.append({
            "rank": rank,
            "file_absolute": abs_path,
            "file_relative": rel,
            "start_line": chunk["start_line"],
            "end_line": chunk["end_line"],
            "kind": chunk["kind"],
            "name": chunk["name"],
            "language": chunk["language"],
            "score": round(fused[cid], 4),
            "preview": preview(chunk["content"]),
        })

    conn.close()
    return {
        "repo": repo_name,
        "query": query,
        "repo_dir": str(repo_dir),
        "results": out_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Query an indexed codebase.")
    parser.add_argument("repo", nargs="?", help="Name of the indexed repo")
    parser.add_argument("query", nargs="?", help="Natural-language query")
    parser.add_argument("--top-k", type=int, default=6,
                        help="How many results to return (default: 6)")
    parser.add_argument("--list", action="store_true",
                        help="List every indexed repo, then exit.")
    args = parser.parse_args()

    if args.list:
        repos = list_indexed_repos()
        print(json.dumps(
            {"indexed_repos": [{"name": r.name, "path": str(r)} for r in repos]},
            indent=2,
        ))
        return 0

    if not args.repo or not args.query:
        parser.error("repo and query are required (unless --list)")
        return 2

    try:
        result = run_query(args.repo, args.query, args.top_k)
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
