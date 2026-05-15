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
    chunker,
    db,
    embedder,
    graph,
    identifiers,
    parser,
    paths,
    quantize,
    source,
    symbols,
    walker,
)

BATCH_SIZE = 32


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

    print(f"[vectorize] target: {repo_dir}", flush=True)

    # Step 1: resolve source. Slice 1 is always-fresh — rmtree any prior src/.
    # CORRECTION 2: rmtree before calling populate_from_X (T6 added FileExistsError guard).
    if src_dir.exists():
        shutil.rmtree(src_dir)
    if source.is_git_url(spec):
        commit_sha = source.populate_from_url(spec, src_dir)
    else:
        commit_sha = source.populate_from_local(Path(spec), src_dir)

    # Step 2: open db, init schema.
    db_path = repo_dir / "index.sqlite"
    if db_path.exists():
        db_path.unlink()  # fresh index every run; incremental lands in Slice 12
    conn = db.open_db(db_path)
    db.init_schema(conn)

    # Step 3+4: walk and chunk.
    chunks_buf: list[chunker.Chunk] = []
    file_count = 0
    warnings: list[str] = []
    for entry in walker.walk(src_dir, max_file_mb=ns.max_file_mb):
        file_count += 1
        try:
            file_chunks = list(chunker.chunk_file(entry.abspath))
        except Exception as e:  # broad: per-file failure must not kill the run
            warnings.append(f"chunk failed for {entry.relpath}: {e}")
            continue
        # rewrite file_path to be repo-relative for storage
        for c in file_chunks:
            chunks_buf.append(chunker.Chunk(
                file_path=entry.relpath.as_posix(),
                language=c.language, kind=c.kind, name=c.name,
                ast_path=c.ast_path, start_line=c.start_line,
                end_line=c.end_line, start_byte=c.start_byte,
                end_byte=c.end_byte, content=c.content,
                content_hash=c.content_hash, token_count=c.token_count,
            ))

    print(f"[vectorize] {file_count} files -> {len(chunks_buf)} chunks", flush=True)

    # Step 5: embed (skip the model load if there's nothing to embed).
    if not chunks_buf:
        emb = embedder.StubEmbedder()
        embeddings = emb.embed([])
    else:
        emb = embedder.make_embedder()
        print(f"[vectorize] embedder: {emb.model_id}", flush=True)
        embeddings = _embed_in_batches(emb, [c.content for c in chunks_buf], BATCH_SIZE)

    # Step 6: write chunks + embeddings.
    # CORRECTION 1: use db.insert_embedding (vec_int8 JSON path) — NOT q.tobytes().
    with conn:
        for c in chunks_buf:
            conn.execute(
                "INSERT INTO chunks (file_path, language, kind, name, ast_path, "
                "start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (c.file_path, c.language, c.kind, c.name, c.ast_path,
                 c.start_line, c.end_line, c.start_byte, c.end_byte,
                 c.content, c.content_hash, c.token_count),
            )
        chunk_ids = [row[0] for row in conn.execute("SELECT id FROM chunks ORDER BY id").fetchall()]
        assert len(chunk_ids) == len(chunks_buf)
        for chunk_id, c in zip(chunk_ids, chunks_buf):
            conn.executemany(
                "INSERT INTO symbol_trigrams (trigram, chunk_id, symbol, occurrences) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(trigram, chunk_id, symbol) DO UPDATE SET "
                "occurrences = occurrences + excluded.occurrences",
                identifiers.symbol_trigram_rows(chunk_id, c.content),
            )
        for chunk_id, emb_row in zip(chunk_ids, embeddings):
            # quantize_int8 expects shape (N, dim); pass 1-row, take [0] for 1-D array.
            q = quantize.quantize_int8(emb_row.reshape(1, -1))[0]  # 1-D int8 array
            db.insert_embedding(conn, chunk_id, q)

    nodes_symbol, edges_symbol = _write_symbol_graph(
        conn,
        src_dir,
        chunks_buf,
        chunk_ids,
        warnings,
    )

    # Step 7: meta + manifest.
    _write_meta(
        conn,
        repo_name,
        spec,
        commit_sha,
        emb,
        len(chunks_buf),
        nodes_symbol,
        edges_symbol,
    )
    manifest = _build_manifest(repo_name, spec, src_dir, repo_dir, db_path,
                                file_count, len(chunks_buf), warnings)
    (repo_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    conn.close()

    # Step 8: emit v1.0 summary JSON on stdout (last line).
    elapsed = time.time() - t_start
    summary = {
        "repo_name": repo_name,
        "source_dir": str(src_dir),
        "db_path": str(db_path),
        "manifest_path": str(repo_dir / "manifest.json"),
        "files_indexed": file_count,
        "chunks_indexed": len(chunks_buf),
        "nodes_symbol": nodes_symbol,
        "nodes_block": 0,       # Slice 9
        "edges_symbol": edges_symbol,
        "edges_flow": 0,        # Slices 9-10
        "clusters_indexed": 0,  # Slice 7
        "elapsed_seconds": round(elapsed, 2),
        "embedding_cache_hit_rate": 0.0,   # Slice 11
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


def _write_symbol_graph(
    conn,
    src_dir: Path,
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
    for rel_file_path, file_chunks in sorted(chunks_by_file.items()):
        language = file_chunks[0][3]
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
        with conn:
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
    emb,
    total_chunks,
    nodes_symbol,
    edges_symbol,
):
    db.write_meta(conn, "schema_version", "1.0")
    db.write_meta(conn, "indexed_at", str(int(time.time())))
    db.write_meta(conn, "repo_origin", repo_origin)
    db.write_meta(conn, "commit_sha", commit_sha or "")
    db.write_meta(conn, "embedder_model", emb.model_id)
    db.write_meta(conn, "embedder_dim", str(emb.dim))
    db.write_meta(conn, "embedder_quant", "int8")
    db.write_meta(conn, "reranker_model", "")
    db.write_meta(conn, "total_chunks", str(total_chunks))
    db.write_meta(conn, "total_nodes_symbol", str(nodes_symbol))
    db.write_meta(conn, "total_nodes_block", "0")
    db.write_meta(conn, "total_edges_symbol", str(edges_symbol))
    db.write_meta(conn, "total_edges_flow", "0")
    db.write_meta(conn, "total_clusters", "0")
    db.write_meta(conn, "merkle_root_sha", "")


def _build_manifest(repo_name, repo_origin, src_dir, repo_dir, db_path,
                     files_indexed, chunks_indexed, warnings):
    return {
        "repo_name": repo_name,
        "repo_origin": repo_origin,
        "source_dir": str(src_dir),
        "repo_dir": str(repo_dir),
        "db_path": str(db_path),
        "files_indexed": files_indexed,
        "chunks_indexed": chunks_indexed,
        "warnings": warnings,
        "schema_version": "1.0",
    }
