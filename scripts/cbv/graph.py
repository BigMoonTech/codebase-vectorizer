from __future__ import annotations

from cbv.symbols import SymbolEdge, SymbolNode


PAGERANK_EDGE_KINDS = (
    "defines",
    "calls",
    "imports",
    "inherits",
    "references",
    "contains",
    "tests",
    "documents",
    "mentions",
)


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


def compute_pagerank(conn, warnings: list[str] | None = None) -> int:
    import networkx as nx

    node_ids = {
        int(node_id)
        for (node_id,) in conn.execute("SELECT id FROM nodes WHERE kind != 'block'")
    }
    if not node_ids:
        with conn:
            conn.execute("UPDATE nodes SET pagerank = 0.0")
        return 0

    g = nx.DiGraph()
    g.add_nodes_from(node_ids)
    placeholders = ",".join("?" for _ in PAGERANK_EDGE_KINDS)
    for src, dst, weight in conn.execute(
        f"SELECT src, dst, weight FROM edges WHERE kind IN ({placeholders})",
        PAGERANK_EDGE_KINDS,
    ):
        src_id = int(src)
        dst_id = int(dst)
        if src_id in node_ids and dst_id in node_ids:
            g.add_edge(src_id, dst_id, weight=float(weight))

    try:
        scores = nx.pagerank(g, weight="weight")
    except ModuleNotFoundError as exc:
        if exc.name != "scipy":
            raise
        scores = _weighted_pagerank(g)
    except nx.PowerIterationFailedConvergence:
        if warnings is not None:
            warnings.append("pagerank failed to converge; using uniform scores")
        uniform = 1.0 / len(node_ids)
        scores = {node_id: uniform for node_id in node_ids}

    with conn:
        conn.execute("UPDATE nodes SET pagerank = 0.0")
        conn.executemany(
            "UPDATE nodes SET pagerank = ? WHERE id = ?",
            [(float(score), int(node_id)) for node_id, score in scores.items()],
        )
    return len(scores)


def personalized_pagerank(
    conn,
    seed_chunk_ids: list[int],
    *,
    iterations: int = 10,
) -> dict[int, float]:
    if not seed_chunk_ids:
        return {}

    import networkx as nx

    node_to_chunk = {
        int(node_id): int(chunk_id)
        for node_id, chunk_id in conn.execute(
            "SELECT id, chunk_id FROM nodes WHERE kind != 'block' AND chunk_id IS NOT NULL"
        ).fetchall()
    }
    if not node_to_chunk:
        return {}

    seed_chunks = set(seed_chunk_ids)
    seed_nodes = {
        node_id
        for node_id, chunk_id in node_to_chunk.items()
        if chunk_id in seed_chunks
    }
    if not seed_nodes:
        return {}

    g = nx.DiGraph()
    g.add_nodes_from(node_to_chunk)
    placeholders = ",".join("?" for _ in PAGERANK_EDGE_KINDS)
    for src, dst, weight in conn.execute(
        f"SELECT src, dst, weight FROM edges WHERE kind IN ({placeholders})",
        PAGERANK_EDGE_KINDS,
    ):
        src_id = int(src)
        dst_id = int(dst)
        if src_id in node_to_chunk and dst_id in node_to_chunk:
            g.add_edge(src_id, dst_id, weight=float(weight))

    personalization = {
        node_id: 1.0 if node_id in seed_nodes else 0.1
        for node_id in g.nodes
    }
    try:
        scores = nx.pagerank(
            g,
            personalization=personalization,
            max_iter=iterations,
            weight="weight",
        )
    except ModuleNotFoundError as exc:
        if exc.name != "scipy":
            raise
        scores = _weighted_pagerank(
            g,
            max_iter=iterations,
            personalization=personalization,
        )
    except nx.PowerIterationFailedConvergence:
        return {chunk_id: 1.0 for chunk_id in seed_chunks if chunk_id in node_to_chunk.values()}

    chunk_scores: dict[int, float] = {}
    for node_id, score in scores.items():
        chunk_id = node_to_chunk[int(node_id)]
        chunk_scores[chunk_id] = max(chunk_scores.get(chunk_id, 0.0), float(score))
    return chunk_scores


def _weighted_pagerank(
    g,
    *,
    alpha: float = 0.85,
    max_iter: int = 100,
    tol: float = 1.0e-6,
    personalization: dict[int, float] | None = None,
):
    nodes = list(g.nodes)
    if not nodes:
        return {}
    n = len(nodes)
    scores = {node: 1.0 / n for node in nodes}
    if personalization is None:
        personalization_scores = {node: 1.0 / n for node in nodes}
    else:
        total = sum(float(personalization.get(node, 0.0)) for node in nodes)
        if total == 0.0:
            personalization_scores = {node: 1.0 / n for node in nodes}
        else:
            personalization_scores = {
                node: float(personalization.get(node, 0.0)) / total
                for node in nodes
            }
    dangling_share = 1.0 / n
    out_weight = {
        node: sum(float(data.get("weight", 1.0)) for _, _, data in g.out_edges(node, data=True))
        for node in nodes
    }

    for _ in range(max_iter):
        next_scores = {
            node: (1.0 - alpha) * personalization_scores[node]
            for node in nodes
        }
        dangling_total = sum(scores[node] for node in nodes if out_weight[node] == 0.0)
        for node in nodes:
            if out_weight[node] == 0.0:
                continue
            for _, dst, data in g.out_edges(node, data=True):
                weight = float(data.get("weight", 1.0))
                next_scores[dst] += alpha * scores[node] * weight / out_weight[node]
        for node in nodes:
            next_scores[node] += alpha * dangling_total * dangling_share
        delta = sum(abs(next_scores[node] - scores[node]) for node in nodes)
        scores = next_scores
        if delta < n * tol:
            return scores
    uniform = 1.0 / n
    return {node: uniform for node in nodes}


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
