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

        top_k = getattr(ns, "top_k", 10)
        counts = {
            "chunks": _count(conn, "chunks"),
            "nodes": _count(conn, "nodes"),
            "edges": _count(conn, "edges"),
            "clusters": _count(conn, "clusters"),
        }
        top_nodes = [
            {"name": name, "kind": kind, "pagerank": round(float(pagerank or 0.0), 6)}
            for name, kind, pagerank in conn.execute(
                "SELECT name, kind, pagerank FROM nodes "
                "WHERE kind != 'block' "
                "ORDER BY pagerank DESC, name ASC LIMIT ?",
                (top_k,),
            )
        ]
        clusters = [
            {"label": label, "summary": summary, "size": int(size)}
            for label, summary, size in conn.execute(
                "SELECT label, summary, size FROM clusters "
                "ORDER BY label ASC, id ASC"
            )
        ]
        print(
            json.dumps(
                {
                    "repo": ns.repo,
                    "counts": counts,
                    "top_nodes": top_nodes,
                    "clusters": clusters,
                }
            ),
            flush=True,
        )
        return 0
    finally:
        conn.close()


def _count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
