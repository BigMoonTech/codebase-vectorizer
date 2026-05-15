# codebase-vectorizer v1.0 Handoff

## Current State

- Branch: `dev`
- Current HEAD: `6993329 Add Slice 2 implementation plan: tree-sitter + cAST chunking`
- `main` is preserved and should stay preserved.
- Slice 1 is implemented, merged into `dev`, and pushed.
- Slice 2 has a written implementation plan but has not been implemented yet.

## What Was Done

Slice 1 delivered the first working v1.0 vertical:

- Replaced the old v0.3.0 scripts with a new `scripts/cbv/` package.
- Added full v1.0 SQLite schema creation: all 10 tables exist; Slice 1 populates `chunks`, `chunks_fts`, `vec_chunks`, and `meta`.
- Added source population, file walking, line-aware text-window chunking, INT8 quantization, Jina/stub embedder factory, and CLI commands.
- Added query pipeline: BM25 + dense KNN + Reciprocal Rank Fusion.
- Updated `vectorize-repo` and `codebase-query` skill docs to v1.0 JSON shapes.
- Added fixture and integration coverage for end-to-end vectorize -> query behavior.
- Final verified test result before merge: `89 passed, 1 skipped`.

Important implementation detail:

- sqlite-vec `INT8[...]` insertion/query must use `vec_int8(?)` with JSON strings. Do not use raw bytes; sqlite-vec 0.1.x treats raw bytes as float32.

## Next Step

Implement Slice 2 from:

- `docs/plans/2026-05-14-codebase-vectorizer-v1.0-slice-2-tree-sitter-cast.md`

Recommended workflow:

1. Cut `slice-2-tree-sitter-cast` from current `dev`.
2. Execute the Slice 2 plan task by task.
3. Keep `Chunk` dataclass shape stable so `vectorize.py` and `query.py` continue working.
4. Run the full test suite after Slice 2.
5. Merge back to `dev` with `--no-ff`, then push.

Slice 2 goal:

- Replace line-window chunking with tree-sitter + cAST chunking for Tier-A languages.
- Keep text-window fallback for unknown or unparseable files.

## Rest Of Project

Planned slices after Slice 2:

1. Identifier trigrams + fast-lane query.
2. Symbol graph nodes/edges.
3. Query router and lane selection.
4. Cross-encoder reranking.
5. Personalized PageRank graph expansion.
6. Concept clusters via UMAP/HDBSCAN + labels.
7. Intra-procedural CFG.
8. Intra-procedural DFG.
9. Embedding cache + Merkle incremental indexing.
10. `codebase-relate` skill.
11. ARCHITECTURE.md generation pass.
12. Benchmarking and confidence/refined-query outputs.

Known followups are acceptable to defer unless they block a later slice:

- `_rrf` source-ordering refactor.
- Embedder memoization.
- `walker.py` directory-level `.git/` pruning.
- Streaming embeddings/inserts in `vectorize.py` for large repos.
- Minor test gaps from Slice 1 reviews.

Project rule from user:

- Do not polish endlessly before the product exists.
- Do not build around failures or leave sloppy programming.
- Fix known issues when they block progress or correctness; otherwise track them and keep moving through vertical slices.
