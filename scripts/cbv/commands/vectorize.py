"""`vectorize` verb — index a repo into <data_home>/repos/<name>/.

Slice 1 pipeline:
  1. resolve source (URL → git clone --depth 1; local → recursive copy)
  2. open <repo_dir>/index.sqlite and init the full v1.0 schema
  3. walk source/ honoring gitignore/size/binary filters
  4. chunk each file (line-aware text windows; tree-sitter+cAST lands in Slice 2)
  5. embed every chunk via the configured embedder
  6. write chunks (FTS5 trigger syncs) + INT8 quantized embeddings (vec_chunks)
  7. write meta keys and manifest.json
  8. print v1.0 summary JSON to stdout
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import List

from cbv import (
    cache,
    chunker,
    db,
    embedder,
    flow,
    graph,
    identifiers,
    incremental,
    parser,
    paths,
    quantize,
    source,
    symbols,
    walker,
)

BATCH_SIZE = 32
FLOW_EDGE_WEIGHTS = {
    "controls": 0.5,
    "dataflow": 0.7,
    "guards": 0.3,
}


def run(ns: argparse.Namespace) -> int:
    t_start = time.time()
    spec = ns.source
    repo_name = source.derive_repo_name(spec)
    repo_dir = (
        paths.repo_dir(repo_name)
        if not ns.output_dir
        else Path(ns.output_dir).expanduser().resolve()
    )
    src_dir = repo_dir / "source"
    repo_dir.mkdir(parents=True, exist_ok=True)
    update_requested = getattr(ns, "update", False)

    print(f"[vectorize] target: {repo_dir}", flush=True)

    # Step 1: resolve source. Always refresh source/ so delta planning compares
    # the current source bytes against the prior merkle table.
    # CORRECTION 2: rmtree before calling populate_from_X (T6 added FileExistsError guard).
    if src_dir.exists():
        shutil.rmtree(src_dir)
    if source.is_git_url(spec):
        commit_sha = source.populate_from_url(spec, src_dir)
    else:
        commit_sha = source.populate_from_local(Path(spec), src_dir)

    # Step 2: open db, init schema.
    db_path = repo_dir / "index.sqlite"
    incremental_mode = update_requested and db_path.exists()
    if db_path.exists() and not incremental_mode:
        db_path.unlink()
    conn = db.open_db(db_path)
    try:
        db.init_schema(conn)
        if incremental_mode:
            db.assert_schema_v1(conn)

        # Step 3: walk and plan delta.
        entries = list(walker.walk(src_dir, max_file_mb=ns.max_file_mb))
        file_count = len(entries)
        source_files: list[tuple[str, str]] = []
        merkle_files: dict[str, tuple[str, int]] = {}
        current_shas: dict[str, str] = {}
        for entry in entries:
            rel_file_path = entry.relpath.as_posix()
            sha = incremental.file_sha(entry.abspath)
            current_shas[rel_file_path] = sha
            merkle_files[rel_file_path] = (sha, entry.size_bytes)
            source_files.append((rel_file_path, chunker.detect_language(entry.abspath)))

        paths_to_chunk = set(current_shas)
        force_full_rebuild = False
        prior_merkle_files: dict[str, tuple[str, int]] = {}
        delta = None
        if incremental_mode:
            prior_merkle_files = _read_merkle_files(conn)
            force_full_rebuild = _missing_merkle_for_indexed_current_file(
                prior_merkle_files,
                _indexed_file_paths(conn),
                set(current_shas),
            )
            delta = incremental.plan_delta(conn, current_shas)
            paths_to_chunk = (
                set(current_shas)
                if force_full_rebuild
                else delta.added | delta.modified
            )

        # Step 4: chunk only files that need writes.
        warnings: list[str] = []
        chunks_buf, chunked_paths = _chunk_selected_entries(
            entries,
            paths_to_chunk,
            warnings,
        )

        # Step 5: embed cache misses (skip the model load if there's nothing to embed).
        embedding_cache_hit_rate = 0.0
        quantized_embeddings = []
        emb = None
        if incremental_mode or chunks_buf:
            emb = embedder.make_embedder()
            embedder_model = emb.model_id
            embedder_dim = str(emb.dim)
            embedder_quant = "int8"
            if incremental_mode and _embedder_metadata_mismatch(
                conn,
                embedder_model,
                embedder_dim,
                embedder_quant,
            ):
                if not _embedder_schema_compatible(embedder_dim, embedder_quant):
                    print(
                        "[vectorize] update aborted: embedder metadata changed "
                        f"to incompatible schema model={embedder_model!r} "
                        f"dim={embedder_dim!r} quant={embedder_quant!r}",
                        flush=True,
                    )
                    return 2
                force_full_rebuild = True
                warnings = []
                chunks_buf, chunked_paths = _chunk_selected_entries(
                    entries,
                    set(current_shas),
                    warnings,
                )
        else:
            embedder_model, embedder_dim, embedder_quant = _metadata_for_empty_update(
                conn,
                incremental_mode,
            )

        if not chunks_buf:
            print(f"[vectorize] {file_count} files -> {len(chunks_buf)} chunks", flush=True)
        else:
            assert emb is not None
            print(f"[vectorize] {file_count} files -> {len(chunks_buf)} chunks", flush=True)
            print(f"[vectorize] embedder: {emb.model_id}", flush=True)
            cache_conn = None
            if not getattr(ns, "no_cache", False):
                cache_conn = cache.open_cache(paths.embedding_cache_path())
            try:
                hits = 0
                quantized_embeddings = [None] * len(chunks_buf)
                miss_positions: list[int] = []
                miss_texts: list[str] = []
                for i, c in enumerate(chunks_buf):
                    cached = (
                        cache.get(cache_conn, c.content_hash, emb.model_id)
                        if cache_conn is not None
                        else None
                    )
                    if cached is None or cached.shape != (emb.dim,):
                        miss_positions.append(i)
                        miss_texts.append(c.content)
                    else:
                        hits += 1
                        quantized_embeddings[i] = cached

                miss_embeddings = _embed_in_batches(emb, miss_texts, BATCH_SIZE)
                if cache_conn is None:
                    for pos, emb_row in zip(miss_positions, miss_embeddings):
                        quantized_embeddings[pos] = quantize.quantize_int8(
                            emb_row.reshape(1, -1)
                        )[0]
                else:
                    with cache_conn:
                        for pos, emb_row in zip(miss_positions, miss_embeddings):
                            q = quantize.quantize_int8(emb_row.reshape(1, -1))[0]
                            quantized_embeddings[pos] = q
                            cache.put(
                                cache_conn,
                                chunks_buf[pos].content_hash,
                                emb.model_id,
                                q,
                            )
                embedding_cache_hit_rate = hits / len(chunks_buf)
            finally:
                if cache_conn is not None:
                    cache_conn.close()

        # Step 6: write chunks + embeddings.
        # CORRECTION 1: use db.insert_embedding (vec_int8 JSON path) — NOT q.tobytes().
        if incremental_mode:
            if force_full_rebuild:
                if chunked_paths != set(current_shas):
                    print(
                        "[vectorize] update aborted: full rebuild could not "
                        "chunk every current file",
                        flush=True,
                    )
                    return 2
                delete_paths = _indexed_file_paths(conn)
                merkle_to_write = {
                    rel: merkle_files[rel]
                    for rel in chunked_paths
                }
            else:
                assert delta is not None
                delete_paths = delta.removed | (delta.modified & chunked_paths)
                merkle_to_write = dict(prior_merkle_files)
                for rel in delta.removed:
                    merkle_to_write.pop(rel, None)
                for rel in chunked_paths:
                    merkle_to_write[rel] = merkle_files[rel]
        else:
            delete_paths = set()
            merkle_to_write = {
                rel: merkle_files[rel]
                for rel in chunked_paths
            }

        expected_chunk_paths = (
            set(current_shas)
            if incremental_mode and force_full_rebuild
            else paths_to_chunk
        )
        graph_source_files = _graph_source_files(
            source_files,
            set(merkle_to_write),
            expected_chunk_paths - chunked_paths,
        )

        with conn:
            _clear_symbol_graph(conn)
            _delete_file_chunks(conn, delete_paths)

            inserted_chunk_ids: list[int] = []
            for c in chunks_buf:
                cur = conn.execute(
                    "INSERT INTO chunks (file_path, language, kind, name, ast_path, "
                    "start_line, end_line, start_byte, end_byte, content, "
                    "content_hash, token_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c.file_path, c.language, c.kind, c.name, c.ast_path,
                     c.start_line, c.end_line, c.start_byte, c.end_byte,
                     c.content, c.content_hash, c.token_count),
                )
                inserted_chunk_ids.append(int(cur.lastrowid))
            assert len(inserted_chunk_ids) == len(chunks_buf)
            for chunk_id, c in zip(inserted_chunk_ids, chunks_buf):
                conn.executemany(
                    "INSERT INTO symbol_trigrams (trigram, chunk_id, symbol, occurrences) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(trigram, chunk_id, symbol) DO UPDATE SET "
                    "occurrences = occurrences + excluded.occurrences",
                    identifiers.symbol_trigram_rows(chunk_id, c.content),
            )
            for chunk_id, q in zip(inserted_chunk_ids, quantized_embeddings):
                db.insert_embedding(conn, chunk_id, q)
            incremental.write_merkle(conn, merkle_to_write)

            all_chunk_ids, all_chunks = _load_chunks(conn)

            nodes_symbol, edges_symbol = _write_symbol_graph(
                conn,
                src_dir,
                graph_source_files,
                all_chunks,
                all_chunk_ids,
                warnings,
            )
            nodes_block, edges_flow = _write_flow_graph(
                conn,
                src_dir,
                graph_source_files,
                all_chunks,
                all_chunk_ids,
                warnings,
            )
            graph.compute_pagerank(conn, warnings=warnings)

            # Step 7: meta + manifest.
            _write_meta(
                conn,
                repo_name,
                spec,
                commit_sha,
                embedder_model,
                embedder_dim,
                embedder_quant,
                len(all_chunks),
                nodes_symbol,
                nodes_block,
                edges_symbol,
                edges_flow,
                incremental.merkle_root(
                    {rel: sha for rel, (sha, _size) in merkle_to_write.items()}
                ),
            )
        manifest = _build_manifest(repo_name, spec, src_dir, repo_dir, db_path,
                                    file_count, len(all_chunks), warnings,
                                    embedding_cache_hit_rate)
        (repo_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    finally:
        conn.close()

    # Step 8: emit v1.0 summary JSON on stdout (last line).
    elapsed = time.time() - t_start
    summary = {
        "repo_name": repo_name,
        "source_dir": str(src_dir),
        "db_path": str(db_path),
        "manifest_path": str(repo_dir / "manifest.json"),
        "files_indexed": file_count,
        "chunks_indexed": len(all_chunks),
        "nodes_symbol": nodes_symbol,
        "nodes_block": nodes_block,
        "edges_symbol": edges_symbol,
        "edges_flow": edges_flow,
        "clusters_indexed": 0,  # Slice 7
        "elapsed_seconds": round(elapsed, 2),
        "embedding_cache_hit_rate": embedding_cache_hit_rate,
        "warnings": warnings,
        "bench_results": {},               # Slice 14
    }
    print(json.dumps(summary), flush=True)
    return 0


def _embed_in_batches(emb: embedder.Embedder, texts: List[str], batch: int):
    import numpy as np
    if not texts:
        return np.zeros((0, emb.dim), dtype="float32")
    rows = []
    for i in range(0, len(texts), batch):
        rows.append(emb.embed(texts[i:i + batch]))
    return np.concatenate(rows, axis=0)


def _chunk_selected_entries(
    entries: list[walker.WalkEntry],
    paths_to_chunk: set[str],
    warnings: list[str],
) -> tuple[list[chunker.Chunk], set[str]]:
    chunks_buf: list[chunker.Chunk] = []
    chunked_paths: set[str] = set()
    for entry in entries:
        rel_file_path = entry.relpath.as_posix()
        if rel_file_path not in paths_to_chunk:
            continue
        try:
            file_chunks = list(chunker.chunk_file(entry.abspath))
        except Exception as e:  # broad: per-file failure must not kill the run
            warnings.append(f"chunk failed for {entry.relpath}: {e}")
            continue
        chunked_paths.add(rel_file_path)
        for c in file_chunks:
            chunks_buf.append(
                chunker.Chunk(
                    file_path=rel_file_path,
                    language=c.language,
                    kind=c.kind,
                    name=c.name,
                    ast_path=c.ast_path,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    start_byte=c.start_byte,
                    end_byte=c.end_byte,
                    content=c.content,
                    content_hash=c.content_hash,
                    token_count=c.token_count,
                )
            )
    return chunks_buf, chunked_paths


def _missing_merkle_for_indexed_current_file(
    prior_merkle_files: dict[str, tuple[str, int]],
    indexed_file_paths: set[str],
    current_file_paths: set[str],
) -> bool:
    return bool((indexed_file_paths & current_file_paths) - set(prior_merkle_files))


def _read_merkle_files(conn) -> dict[str, tuple[str, int]]:
    return {
        row[0]: (row[1], int(row[2]))
        for row in conn.execute(
            "SELECT file_path, blob_sha, size_bytes FROM merkle_files"
        )
    }


def _indexed_file_paths(conn) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT DISTINCT file_path FROM chunks")
    }


def _metadata_for_empty_update(conn, incremental_mode: bool) -> tuple[str, str, str]:
    fallback = embedder.StubEmbedder()
    if not incremental_mode:
        return fallback.model_id, str(fallback.dim), "int8"
    return (
        db.read_meta(conn, "embedder_model") or fallback.model_id,
        db.read_meta(conn, "embedder_dim") or str(fallback.dim),
        db.read_meta(conn, "embedder_quant") or "int8",
    )


def _embedder_metadata_mismatch(
    conn,
    embedder_model: str,
    embedder_dim: str,
    embedder_quant: str,
) -> bool:
    return (
        db.read_meta(conn, "embedder_model") != embedder_model
        or db.read_meta(conn, "embedder_dim") != embedder_dim
        or db.read_meta(conn, "embedder_quant") != embedder_quant
    )


def _embedder_schema_compatible(embedder_dim: str, embedder_quant: str) -> bool:
    return embedder_dim == str(embedder.DEFAULT_DIM) and embedder_quant == "int8"


def _graph_source_files(
    source_files: list[tuple[str, str]],
    merkle_paths: set[str],
    failed_paths: set[str],
) -> list[tuple[str, str]]:
    graph_paths = merkle_paths - failed_paths
    return [
        (rel_file_path, language)
        for rel_file_path, language in source_files
        if rel_file_path in graph_paths
    ]


def _clear_symbol_graph(conn) -> None:
    conn.execute("DELETE FROM edges")
    conn.execute("DELETE FROM nodes")


def _delete_file_chunks(conn, file_paths: set[str]) -> None:
    if not file_paths:
        return
    placeholders = ",".join("?" for _ in file_paths)
    ordered_paths = sorted(file_paths)
    chunk_ids = [
        int(row[0])
        for row in conn.execute(
            f"SELECT id FROM chunks WHERE file_path IN ({placeholders})",
            ordered_paths,
        ).fetchall()
    ]
    if not chunk_ids:
        return
    chunk_placeholders = ",".join("?" for _ in chunk_ids)
    conn.execute(
        f"DELETE FROM vec_chunks WHERE chunk_id IN ({chunk_placeholders})",
        chunk_ids,
    )
    conn.execute(
        f"DELETE FROM symbol_trigrams WHERE chunk_id IN ({chunk_placeholders})",
        chunk_ids,
    )
    conn.execute(
        f"DELETE FROM chunk_clusters WHERE chunk_id IN ({chunk_placeholders})",
        chunk_ids,
    )
    conn.execute(
        f"DELETE FROM chunks WHERE id IN ({chunk_placeholders})",
        chunk_ids,
    )


def _load_chunks(conn) -> tuple[list[int], list[chunker.Chunk]]:
    rows = conn.execute(
        "SELECT id, file_path, language, kind, name, ast_path, "
        "start_line, end_line, start_byte, end_byte, content, "
        "content_hash, token_count FROM chunks ORDER BY id"
    ).fetchall()
    chunk_ids = [int(row[0]) for row in rows]
    chunks = [
        chunker.Chunk(
            file_path=row[1],
            language=row[2],
            kind=row[3],
            name=row[4],
            ast_path=row[5],
            start_line=row[6],
            end_line=row[7],
            start_byte=row[8],
            end_byte=row[9],
            content=row[10],
            content_hash=row[11],
            token_count=row[12],
        )
        for row in rows
    ]
    return chunk_ids, chunks


def _write_symbol_graph(
    conn,
    src_dir: Path,
    source_files: list[tuple[str, str]],
    chunks_buf: list[chunker.Chunk],
    chunk_ids: list[int],
    warnings: list[str],
) -> tuple[int, int]:
    chunks_by_file: dict[str, list[tuple[int, int, int, str]]] = {}
    for chunk_id, c in zip(chunk_ids, chunks_buf):
        chunks_by_file.setdefault(c.file_path, []).append(
            (c.start_byte, c.end_byte, chunk_id, c.language)
        )

    all_nodes: list[symbols.SymbolNode] = []
    all_edges: list[symbols.SymbolEdge] = []
    for rel_file_path, language in sorted(source_files):
        file_chunks = chunks_by_file.get(rel_file_path, [])
        language_meta = parser.language_for_name(language)
        source_bytes = b""

        try:
            source_bytes = (src_dir / Path(rel_file_path)).read_bytes()
            tree = (
                parser.parse(source_bytes, language_meta)
                if language_meta is not None
                else None
            )
            if language_meta is not None and tree is None:
                warnings.append(
                    f"symbol extraction failed for {rel_file_path}: parser returned no tree"
                )
            extracted = symbols.extract_symbols(
                Path(rel_file_path),
                language,
                source_bytes,
                tree,
            )
        except Exception as e:
            warnings.append(f"symbol extraction failed for {rel_file_path}: {e}")
            extracted = symbols.extract_symbols(
                Path(rel_file_path),
                language,
                source_bytes,
                None,
            )

        ranges = [(start, end, chunk_id) for start, end, chunk_id, _ in file_chunks]
        for node in extracted.nodes:
            all_nodes.append(
                replace(
                    node,
                    chunk_id=_chunk_id_containing_start(node, ranges),
                )
            )
        all_edges.extend(extracted.edges)

    if all_nodes:
        node_ids = graph.insert_nodes(conn, all_nodes)
        graph.insert_edges(conn, all_edges, node_ids)

    nodes_symbol = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind != 'block'"
    ).fetchone()[0]
    edges_symbol = conn.execute(
        "SELECT COUNT(*) FROM edges "
        "WHERE kind IN ('defines','calls','imports','inherits','references',"
        "'contains','tests','documents','mentions')"
    ).fetchone()[0]
    return int(nodes_symbol), int(edges_symbol)


def _write_flow_graph(
    conn,
    src_dir: Path,
    source_files: list[tuple[str, str]],
    chunks_buf: list[chunker.Chunk],
    chunk_ids: list[int],
    warnings: list[str],
) -> tuple[int, int]:
    chunks_by_file: dict[str, list[tuple[int, int, int]]] = {}
    for chunk_id, c in zip(chunk_ids, chunks_buf):
        chunks_by_file.setdefault(c.file_path, []).append(
            (int(c.start_line), int(c.end_line), int(chunk_id))
        )

    function_ids = {
        row[1]: int(row[0])
        for row in conn.execute(
            "SELECT id, name FROM nodes WHERE kind IN ('function', 'method')"
        ).fetchall()
    }

    for rel_file_path, language in sorted(source_files):
        if language != "python":
            continue
        try:
            source_text = (src_dir / Path(rel_file_path)).read_text(encoding="utf-8")
            flow_nodes, flow_edges = flow.extract_python_flow(
                rel_file_path,
                source_text,
            )
        except Exception as e:
            warnings.append(f"flow extraction failed for {rel_file_path}: {e}")
            continue

        flow_node_ids: dict[str, int] = {}
        file_chunks = chunks_by_file.get(rel_file_path, [])
        for node in flow_nodes:
            parent_id = function_ids.get(node.parent_symbol)
            cur = conn.execute(
                "INSERT INTO nodes (kind, name, short_name, file_path, start_line, "
                "end_line, signature, parent_id, chunk_id) "
                "VALUES ('block', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node.name,
                    node.short_name,
                    node.file_path,
                    node.start_line,
                    node.end_line,
                    node.signature,
                    parent_id,
                    _chunk_id_containing_line(node.start_line, file_chunks),
                ),
            )
            flow_node_ids[node.name] = int(cur.lastrowid)

        for edge in flow_edges:
            src_id = flow_node_ids.get(edge.src_name) or function_ids.get(edge.src_name)
            dst_id = flow_node_ids.get(edge.dst_name) or function_ids.get(edge.dst_name)
            if src_id is None or dst_id is None:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO edges (src, dst, kind, weight, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    src_id,
                    dst_id,
                    edge.kind,
                    FLOW_EDGE_WEIGHTS[edge.kind],
                    edge.metadata,
                ),
            )

    nodes_block = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'block'"
    ).fetchone()[0]
    edges_flow = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind IN ('controls', 'dataflow', 'guards')"
    ).fetchone()[0]
    return int(nodes_block), int(edges_flow)


def _chunk_id_containing_line(
    start_line: int,
    ranges: list[tuple[int, int, int]],
) -> int | None:
    for range_start, range_end, chunk_id in ranges:
        if range_start <= start_line <= range_end:
            return chunk_id
    return None


def _chunk_id_containing_start(
    node: symbols.SymbolNode,
    ranges: list[tuple[int, int, int]],
) -> int | None:
    for start_byte, end_byte, chunk_id in ranges:
        if start_byte <= node.start_byte < end_byte:
            return chunk_id
    return None


def _write_meta(
    conn,
    repo_name,
    repo_origin,
    commit_sha,
    embedder_model,
    embedder_dim,
    embedder_quant,
    total_chunks,
    nodes_symbol,
    nodes_block,
    edges_symbol,
    edges_flow,
    merkle_root_sha,
):
    rows = [
        ("schema_version", "1.0"),
        ("indexed_at", str(int(time.time()))),
        ("repo_origin", repo_origin),
        ("commit_sha", commit_sha or ""),
        ("embedder_model", embedder_model),
        ("embedder_dim", embedder_dim),
        ("embedder_quant", embedder_quant),
        ("reranker_model", ""),
        ("total_chunks", str(total_chunks)),
        ("total_nodes_symbol", str(nodes_symbol)),
        ("total_nodes_block", str(nodes_block)),
        ("total_edges_symbol", str(edges_symbol)),
        ("total_edges_flow", str(edges_flow)),
        ("total_clusters", "0"),
        ("merkle_root_sha", merkle_root_sha),
    ]
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rows,
    )


def _build_manifest(repo_name, repo_origin, src_dir, repo_dir, db_path,
                     files_indexed, chunks_indexed, warnings,
                     embedding_cache_hit_rate):
    return {
        "repo_name": repo_name,
        "repo_origin": repo_origin,
        "source_dir": str(src_dir),
        "repo_dir": str(repo_dir),
        "db_path": str(db_path),
        "files_indexed": files_indexed,
        "chunks_indexed": chunks_indexed,
        "embedding_cache_hit_rate": embedding_cache_hit_rate,
        "warnings": warnings,
        "schema_version": "1.0",
    }
