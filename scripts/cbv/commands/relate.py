from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from typing import Any

from cbv import db, paths

SYMBOL_EDGE_KINDS = ("calls", "imports", "inherits", "references", "contains")
FLOW_EDGE_KINDS = ("controls", "dataflow", "guards")


def run(ns: argparse.Namespace) -> int:
    repo = ns.repo
    verb = ns.relate_verb
    query = getattr(ns, "query", "") or ""
    repo_dir = paths.find_repo(repo)
    if repo_dir is None:
        print(f"No index found for repo {repo!r}.", file=sys.stderr)
        return 2

    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        try:
            db.assert_schema_v1(conn)
        except db.LegacySchemaError as e:
            print(str(e), file=sys.stderr)
            return 2

        warnings: list[str] = []
        top_k = max(1, int(getattr(ns, "top_k", 10)))
        hops = max(1, int(getattr(ns, "hops", 2)))
        target = getattr(ns, "target", None)
        results = _run_verb(conn, verb, query, target, top_k, hops, warnings)
        print(
            json.dumps(
                {
                    "repo": repo,
                    "verb": verb,
                    "query": _query_blob(query, target),
                    "results": results,
                    "warnings": warnings,
                }
            ),
            flush=True,
        )
        return 0
    finally:
        conn.close()


def _run_verb(conn, verb: str, query: str, target: str | None, top_k: int, hops: int, warnings: list[str]) -> list[dict[str, Any]]:
    if verb == "callers":
        return _edge_lookup(conn, query, incoming=True, top_k=top_k)
    if verb == "callees":
        return _edge_lookup(conn, query, incoming=False, top_k=top_k)
    if verb == "inheritance-chain":
        return _inheritance_chain(conn, query, top_k=top_k)
    if verb == "neighbors":
        return _neighbors(conn, query, hops=hops, top_k=top_k)
    if verb == "concept-cluster":
        return _concept_cluster(conn, query, top_k=top_k, warnings=warnings)
    if verb == "pagerank-top":
        return [_node_result(row) for row in conn.execute(
            "SELECT id, kind, name, short_name, file_path, start_line, end_line, chunk_id, pagerank "
            "FROM nodes WHERE kind != 'block' ORDER BY pagerank DESC, name ASC LIMIT ?",
            (top_k,),
        )]
    if verb == "shortest-path":
        return _shortest_path(conn, query, target, hops=hops, warnings=warnings)
    if verb in FLOW_EDGE_KINDS_FOR_VERBS:
        return _flow_query(conn, verb, query, top_k=top_k, warnings=warnings)
    warnings.append(f"unsupported relate verb: {verb}")
    return []


FLOW_EDGE_KINDS_FOR_VERBS = {
    "paths-through",
    "reaching-definitions",
    "reachable-uses",
    "conditions-for",
}


def _query_blob(query: str, target: str | None) -> Any:
    if target:
        return {"source": query, "target": target}
    return query


def _edge_lookup(conn, query: str, *, incoming: bool, top_k: int) -> list[dict[str, Any]]:
    node = _find_symbol(conn, query)
    if node is None:
        return []
    if incoming:
        sql = (
            "SELECT other.id, other.kind, other.name, other.short_name, other.file_path, "
            "other.start_line, other.end_line, other.chunk_id, other.pagerank, edge.kind, edge.weight "
            "FROM edges edge JOIN nodes other ON other.id = edge.src "
            "WHERE edge.dst = ? AND edge.kind = 'calls' AND other.kind != 'block' "
            "ORDER BY other.pagerank DESC, other.name ASC LIMIT ?"
        )
    else:
        sql = (
            "SELECT other.id, other.kind, other.name, other.short_name, other.file_path, "
            "other.start_line, other.end_line, other.chunk_id, other.pagerank, edge.kind, edge.weight "
            "FROM edges edge JOIN nodes other ON other.id = edge.dst "
            "WHERE edge.src = ? AND edge.kind = 'calls' AND other.kind != 'block' "
            "ORDER BY other.pagerank DESC, other.name ASC LIMIT ?"
        )
    return [_node_result(row[:9], edge_kind=row[9], weight=row[10]) for row in conn.execute(sql, (node["id"], top_k))]


def _neighbors(conn, query: str, *, hops: int, top_k: int) -> list[dict[str, Any]]:
    start = _find_symbol(conn, query)
    if start is None:
        return []
    kind_placeholders = ",".join("?" for _ in SYMBOL_EDGE_KINDS)
    seen = {start["id"]}
    distances: dict[int, int] = {}
    queue = deque([(start["id"], 0)])
    while queue:
        node_id, depth = queue.popleft()
        if depth >= hops:
            continue
        rows = conn.execute(
            f"SELECT other.id FROM edges edge "
            f"JOIN nodes other ON other.id = CASE WHEN edge.src = ? THEN edge.dst ELSE edge.src END "
            f"WHERE (edge.src = ? OR edge.dst = ?) AND edge.kind IN ({kind_placeholders}) "
            f"AND other.kind != 'block'",
            (node_id, node_id, node_id, *SYMBOL_EDGE_KINDS),
        ).fetchall()
        for (neighbor_id,) in rows:
            neighbor_id = int(neighbor_id)
            if neighbor_id in seen:
                continue
            seen.add(neighbor_id)
            distances[neighbor_id] = depth + 1
            queue.append((neighbor_id, depth + 1))
    if not distances:
        return []
    placeholders = ",".join("?" for _ in distances)
    rows = conn.execute(
        f"SELECT id, kind, name, short_name, file_path, start_line, end_line, chunk_id, pagerank "
        f"FROM nodes WHERE id IN ({placeholders}) ORDER BY pagerank DESC, name ASC LIMIT ?",
        (*distances.keys(), top_k),
    ).fetchall()
    return [_node_result(row, hops=distances[int(row[0])]) for row in rows]


def _inheritance_chain(conn, query: str, *, top_k: int) -> list[dict[str, Any]]:
    node = _find_symbol(conn, query)
    if node is None:
        return []
    rows = conn.execute(
        """
        WITH RECURSIVE chain(id, depth) AS (
            SELECT dst, 1 FROM edges WHERE src = ? AND kind = 'inherits'
            UNION ALL
            SELECT edge.dst, chain.depth + 1
            FROM chain
            JOIN edges edge ON edge.src = chain.id AND edge.kind = 'inherits'
            WHERE chain.depth < ?
        )
        SELECT n.id, n.kind, n.name, n.short_name, n.file_path, n.start_line, n.end_line, n.chunk_id, n.pagerank, chain.depth
        FROM chain JOIN nodes n ON n.id = chain.id
        ORDER BY chain.depth ASC, n.name ASC
        LIMIT ?
        """,
        (node["id"], top_k, top_k),
    ).fetchall()
    return [_node_result(row[:9], depth=row[9]) for row in rows]


def _shortest_path(conn, source: str, target: str | None, *, hops: int, warnings: list[str]) -> list[dict[str, Any]]:
    if not target:
        warnings.append("shortest-path requires a target symbol")
        return []
    src = _find_symbol(conn, source)
    dst = _find_symbol(conn, target)
    if src is None or dst is None:
        return []
    kind_placeholders = ",".join("?" for _ in SYMBOL_EDGE_KINDS)
    queue = deque([(src["id"], [src["id"]])])
    seen = {src["id"]}
    while queue:
        node_id, path = queue.popleft()
        if len(path) - 1 >= hops:
            continue
        rows = conn.execute(
            f"SELECT edge.dst FROM edges edge JOIN nodes n ON n.id = edge.dst "
            f"WHERE edge.src = ? AND edge.kind IN ({kind_placeholders}) AND n.kind != 'block'",
            (node_id, *SYMBOL_EDGE_KINDS),
        ).fetchall()
        for (next_id,) in rows:
            next_id = int(next_id)
            next_path = [*path, next_id]
            if next_id == dst["id"]:
                return _path_nodes(conn, next_path)
            if next_id in seen:
                continue
            seen.add(next_id)
            queue.append((next_id, next_path))
    return []


def _path_nodes(conn, node_ids: list[int]) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in node_ids)
    rows = {
        int(row[0]): row
        for row in conn.execute(
            f"SELECT id, kind, name, short_name, file_path, start_line, end_line, chunk_id, pagerank "
            f"FROM nodes WHERE id IN ({placeholders})",
            tuple(node_ids),
        )
    }
    return [_node_result(rows[node_id], path_index=idx) for idx, node_id in enumerate(node_ids)]


def _concept_cluster(conn, query: str, *, top_k: int, warnings: list[str]) -> list[dict[str, Any]]:
    count = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    if int(count) == 0:
        warnings.append("clusters not indexed")
        return []
    like = f"%{query}%"
    rows = conn.execute(
        """
        SELECT c.id, c.label, c.summary, c.size, COUNT(cc.chunk_id) AS chunks
        FROM clusters c
        LEFT JOIN chunk_clusters cc ON cc.cluster_id = c.id
        WHERE c.label LIKE ? OR c.summary LIKE ?
        GROUP BY c.id
        ORDER BY c.size DESC, c.label ASC
        LIMIT ?
        """,
        (like, like, top_k),
    ).fetchall()
    return [
        {"cluster_id": row[0], "label": row[1], "summary": row[2], "size": row[3], "chunks": row[4]}
        for row in rows
    ]


def _flow_query(conn, verb: str, query: str, *, top_k: int, warnings: list[str]) -> list[dict[str, Any]]:
    flow_edges = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind IN ('controls', 'dataflow', 'guards')"
    ).fetchone()[0]
    block_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'block'").fetchone()[0]
    if int(flow_edges) == 0 or int(block_nodes) == 0:
        warnings.append("flow not indexed")
        return []
    node = _find_symbol(conn, query, include_blocks=True)
    if node is None:
        return []
    if verb == "reaching-definitions":
        return _flow_edges(conn, node["id"], incoming=True, kinds=("dataflow",), top_k=top_k)
    if verb == "reachable-uses":
        return _flow_edges(conn, node["id"], incoming=False, kinds=("dataflow",), top_k=top_k)
    if verb == "conditions-for":
        return _flow_edges(conn, node["id"], incoming=True, kinds=("guards", "controls"), top_k=top_k)
    return _flow_edges(conn, node["id"], incoming=None, kinds=FLOW_EDGE_KINDS, top_k=top_k)


def _flow_edges(conn, node_id: int, *, incoming: bool | None, kinds: tuple[str, ...], top_k: int) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in kinds)
    if incoming is True:
        where = f"edge.dst = ? AND edge.kind IN ({placeholders})"
        other_expr = "edge.src"
        params = (node_id, *kinds, top_k)
    elif incoming is False:
        where = f"edge.src = ? AND edge.kind IN ({placeholders})"
        other_expr = "edge.dst"
        params = (node_id, *kinds, top_k)
    else:
        where = f"(edge.src = ? OR edge.dst = ?) AND edge.kind IN ({placeholders})"
        other_expr = "CASE WHEN edge.src = ? THEN edge.dst ELSE edge.src END"
        params = (node_id, node_id, node_id, *kinds, top_k)
    rows = conn.execute(
        f"SELECT other.id, other.kind, other.name, other.short_name, other.file_path, "
        f"other.start_line, other.end_line, other.chunk_id, other.pagerank, edge.kind, edge.weight "
        f"FROM edges edge JOIN nodes other ON other.id = {other_expr} "
        f"WHERE {where} ORDER BY other.pagerank DESC, other.name ASC LIMIT ?",
        params,
    ).fetchall()
    return [_node_result(row[:9], edge_kind=row[9], weight=row[10]) for row in rows]


def _find_symbol(conn, query: str, *, include_blocks: bool = False) -> dict[str, Any] | None:
    if not query:
        return None
    block_filter = "" if include_blocks else "AND kind != 'block'"
    row = conn.execute(
        f"SELECT id, kind, name, short_name, file_path, start_line, end_line, chunk_id, pagerank "
        f"FROM nodes WHERE (name = ? OR short_name = ? OR name LIKE ?) {block_filter} "
        f"ORDER BY CASE WHEN name = ? THEN 0 WHEN short_name = ? THEN 1 ELSE 2 END, pagerank DESC, name ASC LIMIT 1",
        (query, query, f"%{query}", query, query),
    ).fetchone()
    if row is None:
        return None
    result = _node_result(row)
    result["id"] = int(row[0])
    return result


def _node_result(row, **extra) -> dict[str, Any]:
    result = {
        "id": int(row[0]),
        "kind": row[1],
        "name": row[2],
        "short_name": row[3],
        "file_path": row[4],
        "start_line": row[5],
        "end_line": row[6],
        "chunk_id": row[7],
        "pagerank": round(float(row[8] or 0.0), 6),
    }
    result.update(extra)
    return result
