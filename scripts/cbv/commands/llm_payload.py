"""`cbv llm-payload <repo>` — emit the LLM input payload for an indexed repo.

Path B of the layered LLM-wiring fix: when the `claude` CLI is unavailable,
the vectorize-repo skill calls this to get cluster code samples and repo
metadata, generates labels + architecture prose in-session, and writes them
back via `cbv apply-llm-artifacts`.
"""
from __future__ import annotations

import argparse
import json
import sys

from cbv import db, paths


def run(ns: argparse.Namespace) -> int:
    repo_dir = paths.find_repo(ns.repo)
    if repo_dir is None:
        print(f"No index found for repo {ns.repo!r}.", file=sys.stderr)
        return 2

    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        try:
            db.assert_schema_v1(conn)
        except db.LegacySchemaError as e:
            print(str(e), file=sys.stderr)
            return 2
        payload = build_payload(conn, ns.repo, repo_dir)
        print(json.dumps(payload), flush=True)
        return 0
    finally:
        conn.close()


def build_payload(conn, repo: str, repo_dir) -> dict:
    clusters = []
    for (cluster_id,) in conn.execute("SELECT id FROM clusters ORDER BY id ASC"):
        samples = [
            content
            for (content,) in conn.execute(
                "SELECT c.content FROM chunk_clusters cc "
                "JOIN chunks c ON c.id = cc.chunk_id "
                "WHERE cc.cluster_id = ? "
                "ORDER BY cc.membership DESC, c.id ASC LIMIT 5",
                (cluster_id,),
            )
        ]
        clusters.append({"id": int(cluster_id), "samples": samples})

    languages = [
        {"language": language, "chunks": int(count)}
        for language, count in conn.execute(
            "SELECT language, COUNT(*) FROM chunks "
            "GROUP BY language ORDER BY COUNT(*) DESC, language ASC"
        )
    ]
    top_nodes = [
        {
            "name": name,
            "kind": kind,
            "file_path": file_path,
            "pagerank": round(float(pagerank or 0.0), 6),
        }
        for name, kind, file_path, pagerank in conn.execute(
            "SELECT name, kind, file_path, pagerank FROM nodes "
            "WHERE kind != 'block' ORDER BY pagerank DESC, name ASC LIMIT 20"
        )
    ]
    pivotal_files = [
        {
            "file_path": file_path,
            "chunks": int(chunk_count or 0),
            "symbols": int(symbol_count or 0),
            "pagerank": round(float(pagerank or 0.0), 6),
        }
        for file_path, chunk_count, symbol_count, pagerank in conn.execute(
            "SELECT c.file_path, COUNT(DISTINCT c.id) AS chunk_count, "
            "COUNT(DISTINCT n.id) AS symbol_count, "
            "COALESCE(SUM(CASE WHEN n.kind != 'block' THEN n.pagerank ELSE 0 END), 0.0) AS pr "
            "FROM chunks c LEFT JOIN nodes n ON n.file_path = c.file_path "
            "GROUP BY c.file_path "
            "ORDER BY pr DESC, symbol_count DESC, c.file_path ASC LIMIT 10"
        )
    ]
    cluster_summaries = [
        {"label": label, "summary": summary, "size": int(size)}
        for label, summary, size in conn.execute(
            "SELECT label, summary, size FROM clusters ORDER BY label ASC, id ASC"
        )
    ]
    counts = {
        "chunks": _count(conn, "chunks"),
        "nodes_symbol": _scalar(conn, "SELECT COUNT(*) FROM nodes WHERE kind != 'block'"),
        "nodes_block": _scalar(conn, "SELECT COUNT(*) FROM nodes WHERE kind = 'block'"),
        "edges_symbol": _scalar(
            conn,
            "SELECT COUNT(*) FROM edges WHERE kind NOT IN ('controls', 'dataflow', 'guards')",
        ),
        "edges_flow": _scalar(
            conn,
            "SELECT COUNT(*) FROM edges WHERE kind IN ('controls', 'dataflow', 'guards')",
        ),
        "clusters": _count(conn, "clusters"),
    }
    return {
        "repo": repo,
        "architecture_path": str(repo_dir / "ARCHITECTURE.md"),
        "clusters": clusters,
        "architecture": {
            "repo_name": repo,
            "counts": counts,
            "languages": languages,
            "top_nodes": top_nodes,
            "cluster_summaries": cluster_summaries,
            "pivotal_files": pivotal_files,
        },
    }


def _count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _scalar(conn, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])
