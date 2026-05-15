from __future__ import annotations

from cbv.symbols import SymbolEdge, SymbolNode


def insert_nodes(conn, nodes: list[SymbolNode]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for n in nodes:
        parent_id = ids.get(n.parent_name or "")
        cur = conn.execute(
            "INSERT INTO nodes (kind, name, short_name, file_path, start_line, end_line, signature, parent_id, chunk_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                n.kind,
                n.name,
                n.short_name,
                n.file_path,
                n.start_line,
                n.end_line,
                n.signature,
                parent_id,
                n.chunk_id,
            ),
        )
        ids[n.name] = int(cur.lastrowid)
    return ids


def insert_edges(conn, edges: list[SymbolEdge], ids: dict[str, int]) -> int:
    node_kinds = {
        int(row[0]): row[1]
        for row in conn.execute("SELECT id, kind FROM nodes").fetchall()
    }
    node_file_paths = {
        int(row[0]): row[1]
        for row in conn.execute("SELECT id, file_path FROM nodes").fetchall()
    }
    by_short: dict[str, list[int]] = {}
    for name, node_id in ids.items():
        by_short.setdefault(name.rsplit("::", 1)[-1], []).append(node_id)

    def resolve_src(name: str) -> int | None:
        exact = ids.get(name)
        if exact is not None:
            return exact
        candidates = by_short.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        return None

    def resolve_dst(name: str, edge_kind: str, src_id: int) -> int | None:
        exact = ids.get(name)
        if exact is not None:
            return exact if _is_compatible_dst_kind(edge_kind, node_kinds[exact]) else None
        candidates = [
            candidate
            for candidate in by_short.get(name, [])
            if _is_compatible_dst_kind(edge_kind, node_kinds[candidate])
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return None
        candidates = _prefer_source_path(candidates, src_id, node_file_paths)
        if len(candidates) == 1:
            return candidates[0]
        return None

    written = 0
    for e in edges:
        src = resolve_src(e.src_name)
        if src is None:
            continue
        dst = resolve_dst(e.dst_name, e.kind, src)
        if dst is None or src == dst:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO edges (src, dst, kind, weight, metadata) VALUES (?, ?, ?, ?, ?)",
            (src, dst, e.kind, e.weight, e.metadata),
        )
        written += cur.rowcount
    return written


def _is_compatible_dst_kind(edge_kind: str, node_kind: str) -> bool:
    if edge_kind == "calls":
        return node_kind in {"function", "method"}
    if edge_kind == "inherits":
        return node_kind == "class"
    if edge_kind in {"imports", "references"}:
        return node_kind != "block"
    return True


def _prefer_source_path(
    candidates: list[int],
    src_id: int,
    node_file_paths: dict[int, str],
) -> list[int]:
    src_file = node_file_paths[src_id]
    src_dir = _path_dir(src_file)

    same_dir = [
        candidate
        for candidate in candidates
        if _path_dir(node_file_paths[candidate]) == src_dir
    ]
    if same_dir:
        return same_dir

    scores = [
        (_common_path_prefix_len(src_file, node_file_paths[candidate]), candidate)
        for candidate in candidates
    ]
    best_score = max(score for score, _ in scores)
    if best_score <= 0:
        return candidates
    return [candidate for score, candidate in scores if score == best_score]


def _path_dir(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _common_path_prefix_len(left: str, right: str) -> int:
    left_parts = left.split("/")[:-1]
    right_parts = right.split("/")[:-1]
    total = 0
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part != right_part:
            break
        total += 1
    return total
