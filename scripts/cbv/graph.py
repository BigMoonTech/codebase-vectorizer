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
    by_short: dict[str, list[int]] = {}
    for name, node_id in ids.items():
        by_short.setdefault(name.rsplit("::", 1)[-1], []).append(node_id)

    def resolve(name: str) -> int | None:
        exact = ids.get(name)
        if exact is not None:
            return exact
        candidates = by_short.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        return None

    written = 0
    for e in edges:
        src = resolve(e.src_name)
        dst = resolve(e.dst_name)
        if src is None or dst is None or src == dst:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO edges (src, dst, kind, weight, metadata) VALUES (?, ?, ?, ?, ?)",
            (src, dst, e.kind, e.weight, e.metadata),
        )
        written += cur.rowcount
    return written
