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
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import List

import numpy as np

from cbv import (
    architecture,
    cache,
    chunker,
    clusters,
    db,
    embedder,
    flow,
    fsutil,
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
from cbv.commands import bench_cmd

BATCH_SIZE = 32
CLUSTER_INDEX_VERSION = "umap-hdbscan-v1"
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
    # force_rmtree tolerates read-only git pack files left over on Windows.
    fsutil.force_rmtree(src_dir)
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

        no_delta_update = (
            incremental_mode
            and not force_full_rebuild
            and delta is not None
            and not delta.added
            and not delta.modified
            and not delta.removed
        )
        skip_cluster_rebuild = (
            no_delta_update
            and _clusters_current(conn)
        )
        if skip_cluster_rebuild:
            intended_model, intended_dim, intended_quant = (
                embedder.configured_embedder_metadata()
            )
            if _embedder_metadata_mismatch(
                conn,
                intended_model,
                intended_dim,
                intended_quant,
            ):
                skip_cluster_rebuild = False

        # Step 5: embed cache misses (skip the model load if there's nothing to embed).
        embedding_cache_hit_rate = 0.0
        quantized_embeddings = []
        emb = None
        if skip_cluster_rebuild and not chunks_buf:
            embedder_model, embedder_dim, embedder_quant = _metadata_for_empty_update(
                conn,
                incremental_mode,
            )
        elif incremental_mode or chunks_buf:
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

        if incremental_mode:
            existing_chunk_ids, existing_chunks = _load_chunks(conn)
            planned_all_chunks = []
            preserved_chunk_ids: list[int] = []
            for chunk_id, c in zip(existing_chunk_ids, existing_chunks):
                if c.file_path in delete_paths:
                    continue
                planned_all_chunks.append(c)
                preserved_chunk_ids.append(chunk_id)
            planned_all_chunks.extend(chunks_buf)
        else:
            preserved_chunk_ids = []
            planned_all_chunks = list(chunks_buf)

        if skip_cluster_rebuild:
            cluster_plan = None
            clusters_indexed = _cluster_count(conn)
        else:
            cluster_embeddings = _cluster_embedding_matrix_for_plan(
                conn,
                preserved_chunk_ids,
                quantized_embeddings,
                warnings,
            )
            if cluster_embeddings is None:
                detail = warnings[-1] if warnings else "concept clustering failed"
                print(f"[vectorize] update aborted: {detail}", flush=True)
                return 2
            cluster_plan = _build_concept_cluster_plan(
                planned_all_chunks,
                cluster_embeddings,
                warnings,
            )
            if cluster_plan is None:
                detail = warnings[-1] if warnings else "concept clustering failed"
                print(f"[vectorize] update aborted: {detail}", flush=True)
                return 2

        with conn:
            _clear_symbol_graph(conn)
            _delete_file_chunks(conn, delete_paths)

            inserted_chunk_ids: list[int] = []
            for c in chunks_buf:
                cur = conn.execute(
                    "INSERT INTO chunks (file_path, language, kind, name, ast_path, "
                    "start_line, end_line, start_byte, end_byte, content, "
                    "content_hash, token_count, category) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c.file_path, c.language, c.kind, c.name, c.ast_path,
                     c.start_line, c.end_line, c.start_byte, c.end_byte,
                     c.content, c.content_hash, c.token_count, c.category),
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
            if len(all_chunks) != len(planned_all_chunks):
                raise RuntimeError(
                    "planned chunk positions did not match committed chunk rows"
                )

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

            if cluster_plan is not None:
                clusters_indexed = _write_concept_cluster_records(
                    conn,
                    cluster_plan,
                    all_chunk_ids,
                )
            cluster_index_version = (
                CLUSTER_INDEX_VERSION
                if cluster_plan is not None
                else db.read_meta(conn, "cluster_index_version")
            )

            # Step 7: meta.
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
                clusters_indexed,
                incremental.merkle_root(
                    {rel: sha for rel, (sha, _size) in merkle_to_write.items()}
                ),
                cluster_index_version,
            )
            architecture_payload = _build_architecture_payload(
                conn,
                repo_name,
                len(all_chunks),
                nodes_symbol,
                nodes_block,
                edges_symbol,
                edges_flow,
                clusters_indexed,
            )
        try:
            architecture_text, architecture_warning = architecture.render_architecture(
                architecture_payload,
                writer=architecture.LocalLLMArchitectureWriter(),
            )
            if architecture_warning is not None:
                warnings.append(architecture_warning)
            (repo_dir / "ARCHITECTURE.md").write_text(
                architecture_text,
                encoding="utf-8",
            )
        except Exception as e:
            warnings.append(f"ARCHITECTURE.md generation failed; non-critical artifact: {e}")

    finally:
        conn.close()

    bench_results = {}
    if getattr(ns, "bench", False):
        try:
            _bench_rc, bench_results, bench_error = bench_cmd.run_bench(repo_name, emit=False)
            if bench_error is not None:
                warnings.append(f"bench failed: {bench_error}")
        except Exception as e:
            warnings.append(f"bench failed: {e}")

    manifest = _build_manifest(repo_name, spec, src_dir, repo_dir, db_path,
                                file_count, len(all_chunks), warnings,
                                embedding_cache_hit_rate)
    (repo_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

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
        "clusters_indexed": clusters_indexed,
        "elapsed_seconds": round(elapsed, 2),
        "embedding_cache_hit_rate": embedding_cache_hit_rate,
        "warnings": warnings,
        "bench_results": bench_results,
        "llm_artifacts_pending": _llm_artifacts_pending(clusters_indexed),
    }
    print(json.dumps(summary), flush=True)
    return 0


def _llm_artifacts_pending(clusters_indexed: int) -> bool:
    """True when an LLM-backed artifact was left as a deterministic
    placeholder because no LLM command was configured. The vectorize-repo
    skill reads this flag and finalizes the artifacts in-session."""
    architecture_unset = not os.environ.get("CBV_ARCHITECTURE_COMMAND")
    cluster_label_unset = not os.environ.get("CBV_CLUSTER_LABEL_COMMAND")
    return bool(architecture_unset or (cluster_label_unset and clusters_indexed > 0))


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
                    category=entry.category,
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


def _clear_clusters(conn) -> None:
    conn.execute("DELETE FROM chunk_clusters")
    conn.execute("DELETE FROM clusters")


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
        "content_hash, token_count, category FROM chunks ORDER BY id"
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
            category=row[13],
        )
        for row in rows
    ]
    return chunk_ids, chunks


def _cluster_embedding_matrix_for_plan(
    conn,
    preserved_chunk_ids: list[int],
    quantized_embeddings: list[np.ndarray],
    warnings: list[str],
) -> np.ndarray | None:
    try:
        embeddings = _load_embeddings_for_chunk_ids(conn, preserved_chunk_ids)
        for idx, q in enumerate(quantized_embeddings):
            if q is None:
                raise RuntimeError(f"missing new embedding at position {idx}")
            embeddings.append(np.asarray(q, dtype=np.int8))
        return _int8_embeddings_to_float32_matrix(embeddings)
    except Exception as e:
        warnings.append(f"concept clustering failed: {e}")
        return None


def _load_embeddings_for_chunk_ids(conn, chunk_ids: list[int]) -> list[np.ndarray]:
    if not chunk_ids:
        return []
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        f"SELECT chunk_id, embedding FROM vec_chunks WHERE chunk_id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    embeddings_by_id = {
        int(chunk_id): np.frombuffer(embedding, dtype=np.int8).copy()
        for chunk_id, embedding in rows
    }
    missing = [chunk_id for chunk_id in chunk_ids if chunk_id not in embeddings_by_id]
    if missing:
        raise RuntimeError(f"missing stored embedding for chunk_id {missing[0]}")
    return [embeddings_by_id[chunk_id] for chunk_id in chunk_ids]


def _int8_embeddings_to_float32_matrix(embeddings: list[np.ndarray]) -> np.ndarray:
    if not embeddings:
        return np.zeros((0, embedder.DEFAULT_DIM), dtype="float32")
    matrix = np.stack(
        [np.asarray(row, dtype=np.int8) for row in embeddings],
        axis=0,
    ).astype("float32", copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.divide(matrix, norms, out=matrix, where=norms != 0)
    return matrix


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
        try:
            source_text = (src_dir / Path(rel_file_path)).read_text(encoding="utf-8")
            flow_nodes, flow_edges = flow.extract_flow(
                language,
                rel_file_path,
                source_text,
            )
        except Exception as e:
            warnings.append(f"flow extraction failed for {rel_file_path}: {e}")
            continue
        if (
            parser.language_for_name(language) is not None
            and not flow_nodes
            and _file_has_indexed_functions(rel_file_path, function_ids)
        ):
            warnings.append(
                f"flow extraction produced no blocks for {rel_file_path}"
            )

        flow_node_ids: dict[str, int] = {}
        file_chunks = chunks_by_file.get(rel_file_path, [])
        skipped_missing_parent = 0
        for node in flow_nodes:
            parent_id = function_ids.get(node.parent_symbol)
            if parent_id is None:
                skipped_missing_parent += 1
                continue
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
        if skipped_missing_parent and _file_has_indexed_functions(
            rel_file_path,
            function_ids,
        ):
            symbol_label = "symbol" if skipped_missing_parent == 1 else "symbols"
            warnings.append(
                f"flow nodes skipped for {rel_file_path}: "
                f"{skipped_missing_parent} missing parent {symbol_label}"
            )

        edge_metadata: dict[tuple[int, int, str], list[str | None]] = {}
        for edge in flow_edges:
            src_id = flow_node_ids.get(edge.src_name) or function_ids.get(edge.src_name)
            dst_id = flow_node_ids.get(edge.dst_name) or function_ids.get(edge.dst_name)
            if src_id is None or dst_id is None:
                continue
            edge_metadata.setdefault((src_id, dst_id, edge.kind), []).append(edge.metadata)

        for (src_id, dst_id, kind), metadata_values in edge_metadata.items():
            conn.execute(
                "INSERT OR IGNORE INTO edges (src, dst, kind, weight, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    src_id,
                    dst_id,
                    kind,
                    FLOW_EDGE_WEIGHTS[kind],
                    _aggregate_flow_metadata(metadata_values),
                ),
            )

    nodes_block = conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE kind = 'block'"
    ).fetchone()[0]
    edges_flow = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind IN ('controls', 'dataflow', 'guards')"
    ).fetchone()[0]
    return int(nodes_block), int(edges_flow)


def _build_concept_cluster_plan(
    chunks_buf: list[chunker.Chunk],
    embeddings: np.ndarray,
    warnings: list[str],
) -> tuple[list[tuple[int, str, str, bytes, int]], list[tuple[int, int, float]]] | None:
    if not chunks_buf:
        return [], []

    embeddings = embeddings.astype("float32", copy=False)
    if len(embeddings) != len(chunks_buf):
        warnings.append(
            "concept clustering failed: embedding count did not match planned chunks"
        )
        return None
    try:
        result = clusters.cluster_embeddings(embeddings)
    except Exception as e:
        warnings.append(f"concept clustering failed: {e}")
        return None
    grouped: dict[int, list[int]] = {}
    for idx, label in enumerate(result.labels):
        membership = result.memberships[idx]
        if label < 0 or membership <= 0.1:
            continue
        grouped.setdefault(label, []).append(idx)

    labeler = clusters.LocalLLMClusterLabeler()
    cluster_rows: list[tuple[int, str, str, bytes, int]] = []
    member_rows: list[tuple[int, int, float]] = []
    for cluster_id, positions in sorted(grouped.items()):
        positions.sort(key=lambda idx: result.memberships[idx], reverse=True)
        samples = [chunks_buf[idx].content for idx in positions[:5]]
        label, summary, warning = clusters.label_cluster(samples, labeler)
        if warning is not None:
            warnings.append(warning)

        centroid = embeddings[positions].mean(axis=0).astype("float32")
        norm = np.linalg.norm(centroid)
        if norm:
            centroid = centroid / norm
        cluster_rows.append(
            (int(cluster_id), label, summary, centroid.astype("float32").tobytes(), len(positions))
        )
        member_rows.extend(
            (idx, int(cluster_id), float(result.memberships[idx]))
            for idx in positions
        )
    return cluster_rows, member_rows


def _write_concept_cluster_records(
    conn,
    cluster_plan: tuple[list[tuple[int, str, str, bytes, int]], list[tuple[int, int, float]]],
    chunk_ids: list[int],
) -> int:
    cluster_rows, member_position_rows = cluster_plan
    member_rows = [
        (chunk_ids[position], cluster_id, membership)
        for position, cluster_id, membership in member_position_rows
    ]
    _clear_clusters(conn)
    conn.executemany(
        "INSERT INTO clusters (id, label, summary, centroid, size) VALUES (?, ?, ?, ?, ?)",
        cluster_rows,
    )
    conn.executemany(
        "INSERT INTO chunk_clusters (chunk_id, cluster_id, membership) VALUES (?, ?, ?)",
        member_rows,
    )
    return len(cluster_rows)


def _cluster_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0])


def _clusters_current(conn) -> bool:
    if db.read_meta(conn, "cluster_index_version") != CLUSTER_INDEX_VERSION:
        return False
    total_clusters = db.read_meta(conn, "total_clusters")
    if total_clusters is None:
        return False
    try:
        return int(total_clusters) == _cluster_count(conn)
    except ValueError:
        return False


def _file_has_indexed_functions(
    rel_file_path: str,
    function_ids: dict[str, int],
) -> bool:
    prefix = f"{rel_file_path}::"
    return any(symbol.startswith(prefix) for symbol in function_ids)


def _aggregate_flow_metadata(metadata_values: list[str | None]) -> str | None:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in metadata_values:
        if value is None or value in seen:
            continue
        seen.add(value)
        unique_values.append(value)

    if not unique_values:
        return None
    if len(unique_values) == 1:
        return unique_values[0]

    items = [_parse_flow_metadata(value) for value in unique_values]
    metadata: dict[str, object] = {"items": items}
    variables = _ordered_metadata_values(items, "variable")
    if variables:
        metadata["variables"] = variables
        metadata["vars"] = variables
    return json.dumps(metadata, sort_keys=True)


def _parse_flow_metadata(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _ordered_metadata_values(items: list[dict[str, object]], key: str) -> list[str]:
    values: list[str] = []
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or value in values:
            continue
        values.append(value)
    return values


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
    total_clusters,
    merkle_root_sha,
    cluster_index_version,
):
    rows = [
        ("schema_version", db.SCHEMA_VERSION),
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
        ("total_clusters", str(total_clusters)),
        ("merkle_root_sha", merkle_root_sha),
    ]
    if cluster_index_version is not None:
        rows.append(("cluster_index_version", cluster_index_version))
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rows,
    )


def _build_architecture_payload(
    conn,
    repo_name: str,
    chunks_indexed: int,
    nodes_symbol: int,
    nodes_block: int,
    edges_symbol: int,
    edges_flow: int,
    clusters_indexed: int,
) -> dict:
    top_nodes = [
        {
            "name": name,
            "kind": kind,
            "file_path": file_path,
            "pagerank": round(float(pagerank or 0.0), 6),
        }
        for name, kind, file_path, pagerank in conn.execute(
            "SELECT name, kind, file_path, pagerank FROM nodes "
            "WHERE kind != 'block' "
            "ORDER BY pagerank DESC, name ASC LIMIT 20"
        )
    ]
    cluster_summaries = [
        {"label": label, "summary": summary, "size": int(size)}
        for label, summary, size in conn.execute(
            "SELECT label, summary, size FROM clusters ORDER BY label ASC, id ASC"
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
    return {
        "repo_name": repo_name,
        "counts": {
            "chunks": chunks_indexed,
            "nodes_symbol": nodes_symbol,
            "edges_symbol": edges_symbol,
            "nodes_block": nodes_block,
            "edges_flow": edges_flow,
            "clusters": clusters_indexed,
        },
        "top_nodes": top_nodes,
        "clusters": cluster_summaries,
        "pivotal_files": pivotal_files,
    }


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
