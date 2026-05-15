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
    verb, query, target = _normalize_namespace(ns)
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


def _normalize_namespace(ns: argparse.Namespace) -> tuple[str, str, str | None]:
    verb = getattr(ns, "relate_verb", None) or getattr(ns, "verb", "")
    args = list(getattr(ns, "args", []) or [])
    query = getattr(ns, "query", None)
    if query is None:
        query = args[0] if args else ""
    target = getattr(ns, "target", None)
    if target is None and len(args) > 1:
        target = args[1]
    return str(verb), str(query or ""), target


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
        return _flow_query(
            conn,
            verb,
            query,
            target=target,
            top_k=top_k,
            hops=hops,
            warnings=warnings,
        )
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
        WITH RECURSIVE chain(id, depth, path) AS (
            SELECT dst, 1, ',' || ? || ',' || dst || ',' FROM edges WHERE src = ? AND kind = 'inherits'
            UNION ALL
            SELECT edge.dst, chain.depth + 1, chain.path || edge.dst || ','
            FROM chain
            JOIN edges edge ON edge.src = chain.id AND edge.kind = 'inherits'
            WHERE chain.depth < ? AND instr(chain.path, ',' || edge.dst || ',') = 0
        )
        SELECT n.id, n.kind, n.name, n.short_name, n.file_path, n.start_line, n.end_line, n.chunk_id, n.pagerank, chain.depth
        FROM chain JOIN nodes n ON n.id = chain.id
        ORDER BY chain.depth ASC, n.name ASC
        """,
        (node["id"], node["id"], top_k),
    ).fetchall()
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        node_id = int(row[0])
        if node_id in seen:
            continue
        seen.add(node_id)
        results.append(_node_result(row[:9], depth=row[9]))
        if len(results) >= top_k:
            break
    return results


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
        SELECT c.id, c.label, c.summary, c.size,
               ch.id, ch.file_path, ch.language, ch.kind, ch.name, ch.start_line, ch.end_line,
               cc.membership
        FROM clusters c
        JOIN chunk_clusters cc ON cc.cluster_id = c.id
        JOIN chunks ch ON ch.id = cc.chunk_id
        WHERE c.label LIKE ? OR c.summary LIKE ?
        ORDER BY cc.membership DESC, c.size DESC, c.label ASC, ch.file_path ASC, ch.start_line ASC
        LIMIT ?
        """,
        (like, like, top_k),
    ).fetchall()
    return [
        {
            "cluster_id": row[0],
            "label": row[1],
            "summary": row[2],
            "size": row[3],
            "chunk_id": row[4],
            "file_path": row[5],
            "language": row[6],
            "chunk_kind": row[7],
            "chunk_name": row[8],
            "start_line": row[9],
            "end_line": row[10],
            "membership": round(float(row[11] or 0.0), 6),
        }
        for row in rows
    ]


def _flow_query(
    conn,
    verb: str,
    query: str,
    *,
    target: str | None,
    top_k: int,
    hops: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    flow_edges = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind IN ('controls', 'dataflow', 'guards')"
    ).fetchone()[0]
    block_nodes = conn.execute("SELECT COUNT(*) FROM nodes WHERE kind = 'block'").fetchone()[0]
    if int(flow_edges) == 0 or int(block_nodes) == 0:
        warnings.append("flow not indexed")
        return []
    node = _find_symbol(conn, query, include_blocks=True)
    node_ids = _flow_node_ids(conn, node) if node is not None else []
    site = _parse_flow_site(query)
    if verb == "reaching-definitions":
        if site is not None:
            return _dataflow_slice(
                conn,
                site["variable"],
                site_line=site["line"],
                direction="backward",
                top_k=top_k,
                hops=hops,
            )
        results = _flow_edges(conn, node_ids, incoming=True, kinds=("dataflow",), top_k=top_k)
        return results or _flow_edges_matching_metadata(
            conn,
            query,
            kinds=("dataflow",),
            top_k=top_k,
        )
    if verb == "reachable-uses":
        if site is not None:
            return _dataflow_slice(
                conn,
                site["variable"],
                site_line=site["line"],
                direction="forward",
                top_k=top_k,
                hops=hops,
            )
        results = _flow_edges(conn, node_ids, incoming=False, kinds=("dataflow",), top_k=top_k)
        return results or _flow_edges_matching_metadata(
            conn,
            query,
            kinds=("dataflow",),
            top_k=top_k,
        )
    if verb == "conditions-for":
        if site is not None:
            return _conditions_for_site(
                conn,
                site["variable"],
                site_line=site["line"],
                top_k=top_k,
                hops=hops,
            )
        if node_ids:
            return _flow_edges(
                conn,
                node_ids,
                incoming=None,
                kinds=("guards", "dataflow"),
                top_k=top_k,
            )
        return _conditions_for_metadata(conn, query, top_k=top_k)
    if not node_ids:
        return []
    line_range = _parse_line_range(target)
    path_results = _flow_paths_through(
        conn,
        node,
        line_range=line_range,
        top_k=top_k,
        hops=hops,
    )
    if line_range is not None:
        return path_results
    edge_results = _flow_edges(conn, node_ids, incoming=None, kinds=FLOW_EDGE_KINDS, top_k=top_k * 4)
    return _dedupe_flow_results([*path_results, *edge_results])[: max(top_k, len(path_results))]


def _parse_flow_site(query: str) -> dict[str, int | str] | None:
    if "@" not in query:
        return None
    variable, raw_line = query.rsplit("@", 1)
    variable = variable.strip()
    raw_line = raw_line.strip()
    if not variable or not raw_line.isdigit():
        return None
    return {"variable": variable, "line": int(raw_line)}


def _parse_line_range(target: str | None) -> tuple[int, int] | None:
    if not target:
        return None
    raw = target.strip().strip("[]()")
    separator = ":" if ":" in raw else "," if "," in raw else None
    if separator is None:
        return None
    left, right = [part.strip() for part in raw.split(separator, 1)]
    if not left.isdigit() or not right.isdigit():
        return None
    start = int(left)
    end = int(right)
    return (min(start, end), max(start, end))


def _flow_paths_through(
    conn,
    node: dict[str, Any],
    *,
    line_range: tuple[int, int] | None,
    top_k: int,
    hops: int,
) -> list[dict[str, Any]]:
    node_detail = _node_detail(conn, int(node["id"]))
    function = _function_for_flow_node(conn, node_detail)
    if function is None:
        return []
    block_ids = _function_block_ids(conn, int(function["id"]))
    if not block_ids:
        return []

    start_ids = [node_detail["id"]] if node_detail["kind"] == "block" else _cfg_start_ids(conn, block_ids)
    end_ids = _cfg_end_ids(conn, block_ids)
    paths: list[list[int]] = []
    for start_id in start_ids:
        paths.extend(
            _enumerate_control_paths(
                conn,
                start_id,
                block_ids=set(block_ids),
                end_ids=set(end_ids),
                hops=hops,
                top_k=top_k,
            )
        )
        if len(paths) >= top_k:
            break

    results: list[dict[str, Any]] = []
    for path_ids in paths:
        if line_range is not None and not _path_overlaps_line_range(conn, path_ids, line_range):
            continue
        results.append(_flow_path_result(conn, path_ids, function))
        if len(results) >= top_k:
            break
    return results


def _dataflow_slice(
    conn,
    variable: str,
    *,
    site_line: int,
    direction: str,
    top_k: int,
    hops: int,
) -> list[dict[str, Any]]:
    rows = _matching_dataflow_rows(
        conn,
        variable,
        line=site_line,
        line_kind="use_line" if direction == "backward" else "definition_line",
        top_k=top_k * 4,
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        src_id = int(row[0])
        dst_id = int(row[1])
        path_ids = _control_path_between(conn, src_id, dst_id, hops=hops) or [src_id, dst_id]
        result = _flow_edge_result(
            conn,
            row,
            node_ids={dst_id} if direction == "backward" else {src_id},
            incoming=direction == "backward",
            path_ids=path_ids,
        )
        result["variables"] = _ordered_union(result["variables"], [variable])
        results.append(result)
        if len(results) >= top_k:
            break
    return results


def _conditions_for_site(
    conn,
    variable: str,
    *,
    site_line: int,
    top_k: int,
    hops: int,
) -> list[dict[str, Any]]:
    rows = _matching_dataflow_rows(
        conn,
        variable,
        line=site_line,
        line_kind="use_line",
        top_k=top_k * 4,
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        dst = _node_detail(conn, int(row[1]))
        function = _function_for_flow_node(conn, dst)
        path_ids = (
            _entry_path_to(conn, int(function["id"]), int(dst["id"]), hops=hops)
            if function is not None
            else None
        )
        if path_ids is None:
            path_ids = _control_path_between(conn, int(row[0]), int(row[1]), hops=hops) or [int(row[0]), int(row[1])]
        result = _flow_edge_result(
            conn,
            row,
            node_ids=set(),
            incoming=None,
            path_ids=path_ids,
        )
        result["guards"] = _guard_predicates_for_path(conn, path_ids)
        result["variables"] = _ordered_union(result["variables"], [variable])
        results.append(result)
        if len(results) >= top_k:
            break
    return results


def _flow_node_ids(conn, node: dict[str, Any]) -> list[int]:
    if node["kind"] == "block":
        return [node["id"]]
    rows = conn.execute(
        "SELECT id FROM nodes WHERE kind = 'block' AND parent_id = ? ORDER BY name ASC",
        (node["id"],),
    ).fetchall()
    return [int(row[0]) for row in rows]


def _flow_edges(conn, node_ids: list[int], *, incoming: bool | None, kinds: tuple[str, ...], top_k: int) -> list[dict[str, Any]]:
    if not node_ids:
        return []
    node_placeholders = ",".join("?" for _ in node_ids)
    placeholders = ",".join("?" for _ in kinds)
    if incoming is True:
        where = f"edge.dst IN ({node_placeholders}) AND edge.kind IN ({placeholders})"
        params = (*node_ids, *kinds, top_k)
    elif incoming is False:
        where = f"edge.src IN ({node_placeholders}) AND edge.kind IN ({placeholders})"
        params = (*node_ids, *kinds, top_k)
    else:
        where = f"(edge.src IN ({node_placeholders}) OR edge.dst IN ({node_placeholders})) AND edge.kind IN ({placeholders})"
        params = (*node_ids, *node_ids, *kinds, top_k)
    rows = conn.execute(
        f"SELECT edge.src, edge.dst, edge.kind, edge.weight, edge.metadata "
        f"FROM edges edge "
        f"JOIN nodes src ON src.id = edge.src "
        f"JOIN nodes dst ON dst.id = edge.dst "
        f"WHERE {where} "
        f"ORDER BY COALESCE(src.start_line, 0), COALESCE(dst.start_line, 0), edge.kind "
        f"LIMIT ?",
        params,
    ).fetchall()
    return [
        _flow_edge_result(
            conn,
            row,
            node_ids=set(node_ids),
            incoming=incoming,
        )
        for row in rows
    ]


def _flow_edges_matching_metadata(
    conn,
    query: str,
    *,
    kinds: tuple[str, ...],
    top_k: int,
) -> list[dict[str, Any]]:
    if not query:
        return []
    placeholders = ",".join("?" for _ in kinds)
    rows = conn.execute(
        f"SELECT edge.src, edge.dst, edge.kind, edge.weight, edge.metadata "
        f"FROM edges edge "
        f"JOIN nodes src ON src.id = edge.src "
        f"JOIN nodes dst ON dst.id = edge.dst "
        f"WHERE edge.kind IN ({placeholders}) AND edge.metadata LIKE ? "
        f"ORDER BY COALESCE(src.start_line, 0), COALESCE(dst.start_line, 0), edge.kind "
        f"LIMIT ?",
        (*kinds, f"%{query}%", top_k * 4),
    ).fetchall()
    results = [
        _flow_edge_result(conn, row, node_ids=set(), incoming=None)
        for row in rows
        if _metadata_matches_query(row[4], query)
    ]
    return results[:top_k]


def _conditions_for_metadata(conn, query: str, *, top_k: int) -> list[dict[str, Any]]:
    dataflow_results = _flow_edges_matching_metadata(
        conn,
        query,
        kinds=("dataflow",),
        top_k=top_k,
    )
    function_ids = {
        result["function"]["id"]
        for result in dataflow_results
        if result.get("function") is not None
    }
    guard_results = _flow_edges_for_functions(
        conn,
        function_ids,
        kinds=("guards",),
        top_k=top_k,
    )
    dataflow_limit = max(1, top_k - len(guard_results)) if dataflow_results else 0
    merged = dataflow_results[:dataflow_limit] + guard_results
    return merged[:top_k]


def _flow_edges_for_functions(
    conn,
    function_ids: set[int],
    *,
    kinds: tuple[str, ...],
    top_k: int,
) -> list[dict[str, Any]]:
    if not function_ids:
        return []
    placeholders = ",".join("?" for _ in function_ids)
    node_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM nodes WHERE kind = 'block' AND parent_id IN ({placeholders})",
            tuple(function_ids),
        ).fetchall()
    ]
    return _flow_edges(conn, node_ids, incoming=None, kinds=kinds, top_k=top_k)


def _matching_dataflow_rows(
    conn,
    variable: str,
    *,
    line: int,
    line_kind: str,
    top_k: int,
):
    rows = conn.execute(
        "SELECT edge.src, edge.dst, edge.kind, edge.weight, edge.metadata "
        "FROM edges edge "
        "JOIN nodes src ON src.id = edge.src "
        "JOIN nodes dst ON dst.id = edge.dst "
        "WHERE edge.kind = 'dataflow' AND edge.metadata LIKE ? "
        "ORDER BY COALESCE(src.start_line, 0), COALESCE(dst.start_line, 0) "
        "LIMIT ?",
        (f"%{variable}%", top_k),
    ).fetchall()
    matched = []
    for row in rows:
        metadata = _parse_metadata(row[4])
        for item in _metadata_items(metadata):
            if item.get("variable") == variable and item.get(line_kind) == line:
                matched.append(row)
                break
    return matched


def _function_for_flow_node(conn, node: dict[str, Any]) -> dict[str, Any] | None:
    if node["kind"] in {"function", "method"}:
        return node
    parent_id = node.get("parent_id")
    if parent_id is None:
        return None
    return _node_detail(conn, int(parent_id))


def _function_block_ids(conn, function_id: int) -> list[int]:
    return [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM nodes WHERE kind = 'block' AND parent_id = ? "
            "ORDER BY COALESCE(start_line, 0), id",
            (function_id,),
        ).fetchall()
    ]


def _cfg_start_ids(conn, block_ids: list[int]) -> list[int]:
    entry_ids = _block_ids_with_short_name(conn, block_ids, "entry")
    if entry_ids:
        return entry_ids
    incoming = _cfg_incoming_ids(conn, block_ids)
    return [block_id for block_id in block_ids if block_id not in incoming] or block_ids[:1]


def _cfg_end_ids(conn, block_ids: list[int]) -> list[int]:
    exit_ids = _block_ids_with_short_name(conn, block_ids, "exit")
    if exit_ids:
        return exit_ids
    adjacency = _control_adjacency(conn, set(block_ids))
    return [block_id for block_id in block_ids if not adjacency.get(block_id)] or block_ids[-1:]


def _block_ids_with_short_name(conn, block_ids: list[int], short_name: str) -> list[int]:
    if not block_ids:
        return []
    placeholders = ",".join("?" for _ in block_ids)
    return [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM nodes WHERE id IN ({placeholders}) AND short_name = ? ORDER BY id",
            (*block_ids, short_name),
        ).fetchall()
    ]


def _cfg_incoming_ids(conn, block_ids: list[int]) -> set[int]:
    if not block_ids:
        return set()
    placeholders = ",".join("?" for _ in block_ids)
    return {
        int(row[0])
        for row in conn.execute(
            f"SELECT dst FROM edges WHERE kind = 'controls' "
            f"AND src IN ({placeholders}) AND dst IN ({placeholders})",
            (*block_ids, *block_ids),
        ).fetchall()
    }


def _enumerate_control_paths(
    conn,
    start_id: int,
    *,
    block_ids: set[int],
    end_ids: set[int],
    hops: int,
    top_k: int,
) -> list[list[int]]:
    adjacency = _control_adjacency(conn, block_ids)
    paths: list[list[int]] = []

    def visit(node_id: int, path: list[int]) -> None:
        if len(paths) >= top_k:
            return
        if node_id in end_ids and len(path) > 1:
            paths.append(path)
            return
        if len(path) - 1 >= hops:
            paths.append(path)
            return
        for next_id in adjacency.get(node_id, []):
            if next_id in path:
                continue
            visit(next_id, [*path, next_id])

    visit(start_id, [start_id])
    return paths


def _control_adjacency(conn, block_ids: set[int]) -> dict[int, list[int]]:
    if not block_ids:
        return {}
    placeholders = ",".join("?" for _ in block_ids)
    rows = conn.execute(
        f"SELECT src, dst FROM edges WHERE kind = 'controls' "
        f"AND src IN ({placeholders}) AND dst IN ({placeholders}) "
        f"ORDER BY src, dst",
        (*block_ids, *block_ids),
    ).fetchall()
    adjacency: dict[int, list[int]] = {}
    for src, dst in rows:
        adjacency.setdefault(int(src), []).append(int(dst))
    return adjacency


def _control_path_between(conn, src_id: int, dst_id: int, *, hops: int) -> list[int] | None:
    if src_id == dst_id:
        return [src_id]
    src = _node_detail(conn, src_id)
    dst = _node_detail(conn, dst_id)
    function = _edge_function(conn, src, dst)
    if function is None:
        return None
    block_ids = set(_function_block_ids(conn, int(function["id"])))
    max_hops = max(hops, len(block_ids))
    adjacency = _control_adjacency(conn, block_ids)
    queue = deque([(src_id, [src_id])])
    seen = {src_id}
    while queue:
        node_id, path = queue.popleft()
        if len(path) - 1 >= max_hops:
            continue
        for next_id in adjacency.get(node_id, []):
            next_path = [*path, next_id]
            if next_id == dst_id:
                return next_path
            if next_id in seen:
                continue
            seen.add(next_id)
            queue.append((next_id, next_path))
    return None


def _entry_path_to(conn, function_id: int, dst_id: int, *, hops: int) -> list[int] | None:
    block_ids = _function_block_ids(conn, function_id)
    max_hops = max(hops, len(block_ids))
    for start_id in _cfg_start_ids(conn, block_ids):
        path = _control_path_between(conn, start_id, dst_id, hops=max_hops)
        if path is not None:
            return path
    return None


def _path_overlaps_line_range(
    conn,
    path_ids: list[int],
    line_range: tuple[int, int],
) -> bool:
    start, end = line_range
    for node_id in path_ids:
        node = _node_detail(conn, node_id)
        node_start = node.get("start_line")
        node_end = node.get("end_line") or node_start
        if node_start is None:
            continue
        if int(node_start) <= end and int(node_end) >= start:
            return True
    return False


def _flow_path_result(conn, path_ids: list[int], function: dict[str, Any]) -> dict[str, Any]:
    nodes = [_node_detail(conn, node_id) for node_id in path_ids]
    src = nodes[0]
    dst = nodes[-1]
    result = dict(dst)
    result.update(
        {
            "edge_kind": "controls",
            "weight": 1.0,
            "metadata": {"path_kind": "cfg"},
            "src": src,
            "dst": dst,
            "function": function,
            "file_relative": src.get("file_path") or dst.get("file_path"),
            "path": [node["short_name"] for node in nodes],
            "guards": _guard_predicates_for_path(conn, path_ids),
            "variables": _dataflow_variables_for_path(conn, path_ids),
            "score": 1.0,
        }
    )
    return result


def _flow_edge_result(
    conn,
    row,
    *,
    node_ids: set[int],
    incoming: bool | None,
    path_ids: list[int] | None = None,
) -> dict[str, Any]:
    src_id = int(row[0])
    dst_id = int(row[1])
    src = _node_detail(conn, src_id)
    dst = _node_detail(conn, dst_id)
    if incoming is True:
        primary = src
    elif incoming is False:
        primary = dst
    elif src_id in node_ids:
        primary = dst
    else:
        primary = src
    result = dict(primary)
    metadata = _parse_metadata(row[4])
    function = _edge_function(conn, src, dst)
    path_nodes = [_node_detail(conn, node_id) for node_id in path_ids] if path_ids else [src, dst]
    guards = _guard_predicates_for_path(conn, path_ids) if path_ids else _metadata_guards(metadata)
    variables = _ordered_union(
        _metadata_variables(metadata),
        _dataflow_variables_for_path(conn, path_ids) if path_ids else [],
    )
    result.update(
        {
            "edge_kind": row[2],
            "weight": float(row[3] or 0.0),
            "metadata": metadata,
            "src": src,
            "dst": dst,
            "function": function,
            "file_relative": src.get("file_path") or dst.get("file_path"),
            "path": [node["short_name"] for node in path_nodes],
            "guards": guards,
            "variables": variables,
            "score": 1.0,
        }
    )
    return result


def _node_detail(conn, node_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, kind, name, short_name, file_path, start_line, end_line, "
        "chunk_id, pagerank, parent_id, signature FROM nodes WHERE id = ?",
        (node_id,),
    ).fetchone()
    result = _node_result(row[:9])
    result["parent_id"] = row[9]
    result["signature"] = row[10]
    return result


def _edge_function(conn, src: dict[str, Any], dst: dict[str, Any]) -> dict[str, Any] | None:
    if src["kind"] in {"function", "method"}:
        return src
    if dst["kind"] in {"function", "method"}:
        return dst
    parent_id = src.get("parent_id") or dst.get("parent_id")
    if parent_id is None:
        return None
    return _node_detail(conn, int(parent_id))


def _parse_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _metadata_guards(metadata: dict[str, Any]) -> list[str]:
    guards: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            predicate = value.get("predicate")
            if isinstance(predicate, str) and predicate and predicate not in guards:
                guards.append(predicate)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(metadata)
    return guards


def _guard_predicates_for_path(conn, path_ids: list[int] | None) -> list[str]:
    if not path_ids:
        return []
    placeholders = ",".join("?" for _ in path_ids)
    rows = conn.execute(
        f"SELECT metadata FROM edges WHERE kind = 'guards' "
        f"AND src IN ({placeholders}) AND dst IN ({placeholders}) "
        f"ORDER BY src, dst",
        (*path_ids, *path_ids),
    ).fetchall()
    guards: list[str] = []
    for (raw_metadata,) in rows:
        guards = _ordered_union(guards, _metadata_guards(_parse_metadata(raw_metadata)))
    return guards


def _metadata_variables(metadata: dict[str, Any]) -> list[str]:
    variables: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                add(item)
            return
        if isinstance(value, str) and value not in variables:
            variables.append(value)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("variable", "var", "variables", "vars"):
                if key in value:
                    add(value[key])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(metadata)
    return variables


def _dataflow_variables_for_path(conn, path_ids: list[int] | None) -> list[str]:
    if not path_ids:
        return []
    placeholders = ",".join("?" for _ in path_ids)
    rows = conn.execute(
        f"SELECT metadata FROM edges WHERE kind = 'dataflow' "
        f"AND src IN ({placeholders}) AND dst IN ({placeholders}) "
        f"ORDER BY src, dst",
        (*path_ids, *path_ids),
    ).fetchall()
    variables: list[str] = []
    for (raw_metadata,) in rows:
        variables = _ordered_union(variables, _metadata_variables(_parse_metadata(raw_metadata)))
    return variables


def _metadata_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    items = metadata.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return [metadata]


def _ordered_union(*value_lists: list[str]) -> list[str]:
    values: list[str] = []
    for value_list in value_lists:
        for value in value_list:
            if value not in values:
                values.append(value)
    return values


def _dedupe_flow_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for result in results:
        key = (
            str(result.get("edge_kind")),
            json.dumps(result.get("path", []), sort_keys=True),
            json.dumps(result.get("metadata", {}), sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _metadata_matches_query(raw: str | None, query: str) -> bool:
    if not raw:
        return False
    metadata = _parse_metadata(raw)
    return _metadata_contains_query(
        metadata,
        query,
        keys={"variable", "var", "variables", "vars", "predicate"},
    ) or query in raw


def _metadata_contains_query(value: Any, query: str, *, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and _metadata_value_equals(item, query):
                return True
            if _metadata_contains_query(item, query, keys=keys):
                return True
        return False
    if isinstance(value, list):
        return any(_metadata_contains_query(item, query, keys=keys) for item in value)
    return False


def _metadata_value_equals(value: Any, query: str) -> bool:
    if isinstance(value, list):
        return any(_metadata_value_equals(item, query) for item in value)
    return str(value) == query


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
