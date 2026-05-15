# codebase-vectorizer v1.0 Handoff

## Current State

- Branch: `dev`
- Latest confirmed implementation/doc baseline after Task 14 verification: `93ef0ba docs: align task 14 smoke expectation`
- `dev` is ahead of `origin/dev`; local commits since `origin/dev` include:
  - `b5886bd slice 3 t1: index identifier trigrams`
  - `4dd8597 slice 3 t1: address identifier review`
  - `1d6bdc4 docs: mark task 1 complete`
  - `4196e6d slice 3 t2: populate symbol graph`
  - `758be1e slice 3 t2: address symbol graph review`
  - `2104d5b slice 3 t2: preserve chunkless file nodes`
  - `281cf27 docs: mark task 2 complete`
  - `d6fdc59 docs: update handoff for task 2a`
  - `c1cd773 slice 3 t2a: complete tags-based tier-a symbol extraction`
  - `f9a3a41 slice 3 t2a: address tag query review`
  - `f42f28b docs: record task 2a review blockers`
  - `c7dfb97 slice 3 t2a: complete query edge coverage`
  - `4ae7c94 slice 3 t2a: dedupe assigned function symbols`
  - `7eff374 docs: mark task 2a complete`
  - `58dc44c docs: update handoff for task 3`
  - `f1f82cd slice 3 t3: add query lanes and graph expansion`
  - `7855d29 slice 3 t3: cover router edge cases`
  - `18b5c5a docs: record task 3 review blockers`
  - `b75c61a slice 3 t3: harden query lanes`
  - `a50b4fe slice 3 t3: stabilize graph expansion ordering`
  - `cbedecb docs: mark task 3 complete`
  - `8b6c904 docs: mark task 4 checkpoint complete`
  - `805306d slice 4 t1: compute pagerank and expose stats`
  - `341393e slice 4 t1: address pagerank stats review`
  - `5a2ec8d docs: mark task 5 complete`
  - `d5be529 slice 4 t1a: add personalized pagerank to full lane`
  - `9159a5a slice 4 t1a: align ppr with expansion set`
  - `6555c04 slice 4 t1a: bound ppr fallback candidates`
  - `5fd9796 docs: mark task 5a complete`
  - `19130f7 slice 4 t2: add codebase-relate graph queries`
  - `73f735e slice 4 t2: harden relate graph queries`
  - `f10ed3b docs: mark task 6 complete`
  - `0d37af7 slice 5 t1: rerank query candidates and emit confidence hints`
  - `b371ffb slice 5 t1: keep fast lane reranker-free`
  - `69ec615 slice 5 t1: harden reranker edge cases`
  - `601d6b2 slice 5 t1: rerank full chunk content`
  - `e17d633 docs: mark task 7 complete`
  - `3ef70a2 slice 6 t1: cache embeddings by content hash`
  - `f2805a3 slice 6 t1: key embedding cache by model`
  - `0c049a9 slice 6 t1: harden cache vectorize behavior`
  - `58018e8 slice 6 t1: migrate embedding cache schema`
  - `3ea0f07 slice 6 t2: add merkle incremental indexing`
  - `886c6cb slice 6 t2: preserve update metadata`
  - `64a7ca5 slice 6 t2: harden incremental update safety`
  - `e1f2217 slice 6 t2: protect incremental rebuilds`
  - `89b326a slice 6 t2: protect legacy merkle backfills`
  - `fe711ff slice 6 t2: make incremental updates atomic`
  - `24b2037 docs: mark task 9 complete`
  - `2adaae3 slice 7 t1: add python flow graph bootstrap`
  - `7ab6daf slice 7 t1: harden python flow bootstrap`
  - `f11e5af slice 7 t1: guard flow scope edges`
  - `fd2725d docs: mark task 10 complete`
  - `163ac9e slice 7 t1a: complete intra-procedural flow extraction`
  - `5eb4b69 slice 7 t1a: complete flow semantics`
  - `b6a8397 slice 7 t1a: cover ruby flow guards`
  - `4d81390 slice 7 t1a: bound flow path ranges`
  - `9aba417 slice 7 t1a: bind conditions to dataflow paths`
  - `cdaa847 slice 7 t1a: cover assigned and cpp flow symbols`
  - `8f5c15e slice 7 t1a: harden flow edge cases`
  - `ae20d37 slice 7 t1a: harden tree-sitter flow edges`
  - `f2b9af0 slice 7 t1a: seed c parameters in flow`
  - `7277de3 slice 7 t2: add concept clusters`
  - `6cde559 slice 7 t2: complete cluster label and relate paths`
  - `0057120 slice 7 t2: harden concept cluster indexing`
  - `e3d0a8c slice 7 t2: make cluster updates atomic`
  - `9473f30 slice 7 t2: reuse stored vectors for clusters`
  - `280d248 slice 7 t2: respect embedder metadata on cluster fast path`
  - `abc28d5 slice 7 t2: guard cluster freshness and centroid metadata`
  - `d64d7ac fix ppr convergence fallback scoring`
  - `70f9fcc slice 7 t3: write architecture summary and bench results`
  - `403f96c fix task 12 artifact warning handling`
  - `a68e057 fix task 12 benchmark and artifact edge cases`
  - `e059a76 fix task 12 integration warning expectation`
  - `08cf5cc fix task 12 incremental warning expectation`
  - `52326b1 docs: mark task 12 complete`
  - `771f59e docs: update v1.0 code-complete surfaces`
  - `f03c440 docs: fix task 13 review findings`
  - `aa0e758 docs: mark task 13 complete`
  - `93ef0ba docs: align task 14 smoke expectation`
- `main` is preserved and should stay preserved.
- Slice 1 is implemented, merged into `dev`, and pushed.
- Slice 2 is implemented, merged into `dev` with `--no-ff`, verified, cleaned up, and pushed.
- The active execution plan is:
  - `docs/plans/2026-05-15-codebase-vectorizer-v1.0-final-vertical-completion.md`

## Current Working State

This handoff was updated after Task 14 verification:

- Task 1 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2A is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 3 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 4 checkpoint verification passed and is marked complete in the final completion plan.
- Task 5 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 5A is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 6 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 7 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 8 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 9 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 10 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 10A is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 11 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 12 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2A landed across:
  - `c1cd773 slice 3 t2a: complete tags-based tier-a symbol extraction`
  - `f9a3a41 slice 3 t2a: address tag query review`
  - `c7dfb97 slice 3 t2a: complete query edge coverage`
  - `4ae7c94 slice 3 t2a: dedupe assigned function symbols`
- Task 2A review fixes include:
  - Meaningful `cbv.tag_queries` loader/package coexistence.
  - Tier-A `reference.identifier`, `reference.inherits`, and `definition.variable` coverage.
  - Rust `impl_item` handling that avoids duplicate full-name class nodes.
  - Supported Tier-A query failures propagate to vectorize warnings while preserving chunks/file nodes.
  - Cross-file graph resolution filters by compatible kind and prefers same directory/package prefix.
  - JS/TS/TSX assigned functions are not emitted twice as both function and variable.
- Task 3 landed across:
  - `f1f82cd slice 3 t3: add query lanes and graph expansion`
  - `7855d29 slice 3 t3: cover router edge cases`
  - `b75c61a slice 3 t3: harden query lanes`
  - `a50b4fe slice 3 t3: stabilize graph expansion ordering`
- Task 3 review fixes include:
  - Empty/whitespace-only queries now return a clean CLI error instead of routing into helper token extraction.
  - `regex:` and short identifier-like queries are covered by router tests.
  - Fast auto identifier queries avoid dense embedder loading.
  - Graph expansion is limited to dependency-style symbolic edges: `calls`, `imports`, `inherits`, and `references`.
  - Duplicate neighbor chunks use `MAX(edge.weight)`.
  - Tied graph-neighbor scores are ordered deterministically by `neighbor.chunk_id ASC` before `LIMIT`.
- Task 5 landed across:
  - `805306d slice 4 t1: compute pagerank and expose stats`
  - `341393e slice 4 t1: address pagerank stats review`
- Task 5 review fixes include:
  - Fresh vectorize runs compute global PageRank before manifest/summary output.
  - PageRank excludes block nodes and flow edges.
  - PageRank convergence failure falls back to uniform scores and appends a warning.
  - `stats` is wired through CLI and bootstrap, returns counts, top PageRank nodes, and cluster label details.
  - `stats` handles legacy schema errors cleanly and defaults `top_k` for direct `Namespace` callers.
- Task 5A landed across:
  - `d5be529 slice 4 t1a: add personalized pagerank to full lane`
  - `9159a5a slice 4 t1a: align ppr with expansion set`
  - `6555c04 slice 4 t1a: bound ppr fallback candidates`
- Task 5A review fixes include:
  - Full lane seeds PPR from the post-expansion bounded set.
  - PPR candidates are bounded to initial seed plus graph expansion before RRF.
  - Full-lane result tags now require and surface `ppr`.
  - The local no-SciPy weighted PageRank fallback preserves personalized dangling behavior and returns last non-uniform scores on iteration limit.
  - PPR convergence fallback respects `candidate_chunk_ids`.
- Task 6 landed across:
  - `19130f7 slice 4 t2: add codebase-relate graph queries`
  - `73f735e slice 4 t2: harden relate graph queries`
- Task 6 review fixes include:
  - `relate`, `graph`, and `flow` are wired through CLI, bootstrap dispatch, and run scripts.
  - Every spec-listed relate verb returns the common JSON shape: `repo`, `verb`, `query`, `results`, `warnings`.
  - Direct `argparse.Namespace` callers work with both plan-style `verb`/`args` and parser-style `relate_verb`/`query`/`target`.
  - Flow verbs return clean `flow not indexed` fallback JSON until Task 10 supplies real CFG/DFG edges.
  - `flow <repo> <function>` expands a function symbol to child block nodes when flow edges exist.
  - `concept-cluster` returns clean `clusters not indexed` fallback JSON until Task 11, and returns ranked member chunks when clusters exist.
  - `inheritance-chain` dedupes results and guards recursive CTE walks against cycles.
  - `skills/codebase-relate/SKILL.md` documents the relationship-query workflow for indexed repos.
- Task 7 landed across:
  - `0d37af7 slice 5 t1: rerank query candidates and emit confidence hints`
  - `b371ffb slice 5 t1: keep fast lane reranker-free`
  - `69ec615 slice 5 t1: harden reranker edge cases`
  - `601d6b2 slice 5 t1: rerank full chunk content`
- Task 7 review fixes include:
  - Fast lane remains L1-only and never instantiates the reranker; it emits `reranker_model: null`.
  - Full-lane empty candidate results skip reranker construction and return `refined_queries: [query]`.
  - Full-lane reranking rejects mismatched score counts with a clean CLI error instead of mixing score scales.
  - Stub reranker token normalization is symmetric for query and passage text.
  - Full lane passes full chunk content to the reranker adapter while JSON output still exposes only capped preview text.
  - Non-stub factory wiring is covered with a fake `sentence_transformers.CrossEncoder` module test.
  - The final spec and code-quality reviewer objections were withdrawn after checking the written plan/spec: empty `meta.reranker_model` sentinel remains index-time compliant, and the 512-character production adapter cap is spec-defined.
- Task 8 landed across:
  - `3ef70a2 slice 6 t1: cache embeddings by content hash`
  - `f2805a3 slice 6 t1: key embedding cache by model`
  - `0c049a9 slice 6 t1: harden cache vectorize behavior`
  - `58018e8 slice 6 t1: migrate embedding cache schema`
- Task 8 review fixes include:
  - Cross-repo cache lives at `paths.embedding_cache_path()` and stores INT8 embeddings keyed by `(content_hash, model_id)`.
  - `vectorize` copies cache hits through `db.insert_embedding`, embeds and quantizes misses, writes misses to both `vec_chunks` and cache, and reports `embedding_cache_hit_rate` in summary and manifest.
  - `vectorize --no-cache` is now parsed and bypasses cache open/read/write.
  - Wrong-length cached vectors are treated as misses and replaced before sqlite-vec insertion.
  - The main repo DB and cache DB connections are closed through `finally` paths.
  - Cache schema migration handles the intermediate `PRIMARY KEY(content_hash)` table and preserves valid rows while rebuilding to `(content_hash, model_id)`.
  - Duplicate chunk content is counted per chunk for hit-rate semantics while cache storage remains distinct by content hash/model.
- Task 9 landed across:
  - `3ea0f07 slice 6 t2: add merkle incremental indexing`
  - `886c6cb slice 6 t2: preserve update metadata`
  - `64a7ca5 slice 6 t2: harden incremental update safety`
  - `e1f2217 slice 6 t2: protect incremental rebuilds`
  - `89b326a slice 6 t2: protect legacy merkle backfills`
  - `fe711ff slice 6 t2: make incremental updates atomic`
- Task 9 review fixes include:
  - `vectorize --update` is parsed and preserves the existing DB when an index already exists.
  - Fresh vectorize runs populate `merkle_files` and `meta.merkle_root_sha`.
  - Update mode uses file hashes to chunk/embed only added and modified files, remove deleted files, preserve unchanged chunks, and rewrite Merkle rows/root.
  - No-op and removal-only updates preserve embedder metadata when the embedder is unchanged.
  - Compatible embedder metadata changes, including no-op updates, trigger a safe full rebuild; incompatible dimensions abort before destructive DB changes.
  - Schema-v1 indexes with missing or partial Merkle rows are backfilled without deleting the DB and without duplicating chunks.
  - Fresh chunk failures are not marked current in Merkle, so later `--update` retries them.
  - Modified-file chunk failures preserve old chunks/Merkle and avoid graph nodes from failed current source.
  - Update-mode destructive writes, chunk inserts, vector inserts, Merkle writes, graph rebuild, PageRank, and meta writes now run in one SQLite transaction.
  - `graph.compute_pagerank` participates in the caller's transaction for rollback safety.
- Task 10 landed across:
  - `2adaae3 slice 7 t1: add python flow graph bootstrap`
  - `7ab6daf slice 7 t1: harden python flow bootstrap`
  - `f11e5af slice 7 t1: guard flow scope edges`
- Task 10 review fixes include:
  - `scripts/cbv/flow.py` adds the Python bootstrap flow extractor with statement block nodes, sequential `controls`, `guards` predicate metadata, and basic `dataflow` metadata.
  - `tests/fixtures/flow-heavy/flow_app.py` exercises the initial `decide(user, amount)` flow path.
  - `vectorize` writes Python block nodes and flow edges, links block `parent_id` to function/method symbols, reports `nodes_block` and `edges_flow`, and keeps flow extraction failures non-fatal.
  - Flow writes preserve Task 9 transaction behavior.
  - Duplicate dataflow metadata for the same `(src, dst, kind)` is aggregated without a schema change so multiple variables remain queryable.
  - Python method and nested-function flow parent symbols now match symbol graph names such as `file.py::Class::method` and `file.py::outer::inner`.
  - Nested function, class, lambda, and comprehension scopes are pruned from outer-function dataflow.
  - Symbol extraction failure no longer creates orphan block nodes or flow edges.
  - `relate` flow verbs now return useful JSON over indexed flow rows while preserving the clean `flow not indexed` fallback.
- Task 10A landed across:
  - `163ac9e slice 7 t1a: complete intra-procedural flow extraction`
  - `5eb4b69 slice 7 t1a: complete flow semantics`
  - `b6a8397 slice 7 t1a: cover ruby flow guards`
  - `4d81390 slice 7 t1a: bound flow path ranges`
  - `9aba417 slice 7 t1a: bind conditions to dataflow paths`
  - `cdaa847 slice 7 t1a: cover assigned and cpp flow symbols`
  - `8f5c15e slice 7 t1a: harden flow edge cases`
  - `ae20d37 slice 7 t1a: harden tree-sitter flow edges`
  - `f2b9af0 slice 7 t1a: seed c parameters in flow`
- Task 10A review fixes include:
  - General `flow.extract_flow(language, file_path, source)` now indexes spec-aligned intra-procedural block graphs.
  - Python uses `ast` and emits entry, statement, and exit blocks, branch/loop `controls`, `guards`, and branch-sensitive `dataflow`.
  - Python flow now handles alternate branch reaching definitions, all argument forms, augmented assignment target reads, nested-scope pruning, break/continue CFG behavior, and legacy `extract_python_flow` is documented as the old bootstrap extractor.
  - Tree-sitter best-effort flow covers Tier-A forms for JavaScript, TypeScript, TSX, Go, Rust, Java, C, C++, Ruby, and C# where grammars expose supported nodes.
  - JS/TS assigned arrow/function expressions, Ruby instance/singleton methods, Ruby `if`/`while`/`break`/`next`, Rust loop/break/continue expressions, and C/C++ class/struct scoped methods are covered.
  - Tree-sitter augmented assignment target reads are detected by node type and operator across common Tier-A grammars, including C/C++ parameter seeding through nested function declarators.
  - `vectorize` warns when supported flow extraction returns no blocks or when produced flow nodes cannot be inserted because parent symbols are missing; symbol/file rows are preserved and orphan blocks are avoided.
  - `relate` flow verbs now return semantic CFG/DFG JSON for `paths-through`, `reaching-definitions`, `reachable-uses`, and `conditions-for`, including bounded line ranges, producing dataflow paths, guard predicates, variables, and stable result fields.
  - Flow metadata matching exact-filters parsed JSON before applying `top_k`, avoiding dropped exact matches after broad substring prefilters.
- Task 11 landed across:
  - `7277de3 slice 7 t2: add concept clusters`
  - `6cde559 slice 7 t2: complete cluster label and relate paths`
  - `0057120 slice 7 t2: harden concept cluster indexing`
  - `e3d0a8c slice 7 t2: make cluster updates atomic`
  - `9473f30 slice 7 t2: reuse stored vectors for clusters`
  - `280d248 slice 7 t2: respect embedder metadata on cluster fast path`
  - `abc28d5 slice 7 t2: guard cluster freshness and centroid metadata`
- Task 11 review fixes include:
  - `scripts/cbv/clusters.py` uses UMAP + HDBSCAN with soft memberships and raises backend failures instead of silently converting unexpected failures into all-noise.
  - `LocalLLMClusterLabeler` uses `CBV_CLUSTER_LABEL_COMMAND` and falls back to deterministic labels only through `label_cluster`, appending warnings.
  - `vectorize` writes `clusters`, `chunk_clusters`, `total_clusters`, `clusters_indexed`, and `cluster_index_version`; label subprocesses run outside the DB write transaction.
  - Changed updates build cluster inputs from stored/new INT8 vectors, avoiding a second full-corpus model pass.
  - Cluster backend failure aborts changed updates before committing new chunks/graph/Merkle/meta, preserving the previous index.
  - Current no-op cluster indexes, including zero-cluster all-noise results, skip embedder loading when configured metadata still matches; metadata changes still trigger safe rebuild.
  - `relate concept-cluster` searches label substrings first with escaped LIKE wildcards, then nearest centroids only when configured and actual embedder metadata match the index.
  - The full-suite NetworkX 3.6.1 convergence regression is fixed in `d64d7ac`: PPR convergence fallback now uses the internal weighted PageRank implementation instead of flattening to seed scores.
- Task 12 landed across:
  - `70f9fcc slice 7 t3: write architecture summary and bench results`
  - `403f96c fix task 12 artifact warning handling`
  - `a68e057 fix task 12 benchmark and artifact edge cases`
  - `e059a76 fix task 12 integration warning expectation`
  - `08cf5cc fix task 12 incremental warning expectation`
- Task 12 review fixes include:
  - `scripts/cbv/architecture.py` adds `ArchitectureWriter`, `LocalLLMArchitectureWriter`, `CBV_ARCHITECTURE_COMMAND`, `CBV_ARCHITECTURE_TIMEOUT_SECONDS`, deterministic fallback markdown, and warning-backed fallback through `render_architecture`.
  - `vectorize` writes `ARCHITECTURE.md` from index counts, cluster summaries, top PageRank nodes, and pivotal files; architecture render/write failures remain non-critical and persist warnings into manifest and summary.
  - `scripts/cbv/bench.py` provides `MRR@10`, `NDCG@10`, `Recall@5`, and `Recall@10` helpers; `bench <repo>` reads CoIR/RepoEval-style JSONL inputs, runs full-lane queries, writes `bench/results.json`, and prints aggregate summary JSON.
  - Benchmark scoring collapses chunk-level query rows to first-seen unique file rankings before computing file-level metrics.
  - `vectorize --bench` runs the benchmark path, includes `bench_results` in the final summary, and converts benchmark failures into manifest/summary warnings.
  - Shared benchmark query discovery now checks both caller cwd and the project-root `bench/` directory, plus repo-local query files.
- Task 2 review fixes landed in `758be1e` and `2104d5b`:
  - Duplicate short-name edge resolution drops ambiguous edges unless full-name resolution succeeds.
  - Parser-failure/file-node behavior preserves file nodes and emits `symbol extraction failed for <file>: <error>` warnings while indexing continues.
  - Empty indexable files that produce no chunks now get `kind='file'` nodes with `chunk_id = NULL`.
- Task 13 documentation is complete:
  - `771f59e docs: update v1.0 code-complete surfaces`
  - `f03c440 docs: fix task 13 review findings`
  - README and skill docs now describe final v1.0 behavior, `query --lane auto|fast|full`, `relate`, `stats`, `graph`, `flow`, `bench`, cache behavior, and `vectorize --update`.
  - `skills/vectorize-repo/SKILL.md` documents the final summary fields including `nodes_symbol`, `nodes_block`, `edges_symbol`, `edges_flow`, `clusters_indexed`, `embedding_cache_hit_rate`, and `bench_results`.
  - `skills/codebase-query/SKILL.md` documents `pipeline_used`, `refined_queries`, `expansion_size`, and `reranker_model`.
  - `skills/codebase-relate/SKILL.md` lists the exact parser verbs and aliases.
  - `docs/HANDOFF.md` was corrected so the current-state sections no longer describe old Slice 1 behavior or label final v1.0 features as interim Slice 3/Milestone 1 work.
- Task 14 final verification gate passed:
  - Full suite: `453 passed, 1 skipped`.
  - Final CLI smoke passed with stub embedder/reranker and isolated `$env:TEMP\cbv-v1-final-smoke`.
  - Smoke evidence included: first vectorize `20` chunks, `31` symbol nodes, `34` symbol edges, `64` block nodes, `76` flow edges; fast query `pipeline_used: fast`; full query `pipeline_used: full` with `expansion_size: 9`; relate/graph/flow returned JSON with `results`; stats returned counts; bench printed zeroed result JSON for zero query rows; no-change update completed with `embedding_cache_hit_rate: 0.0`.
  - Independent review confirmed the original nonzero no-change update cache-hit expectation was stale; spec and Task 8 formula require `0.0` when `chunks_buf` is empty and no cache lookups occur.
  - Git-state check at `93ef0ba` was clean on `dev`, ahead of `origin/dev`.

## Verified Baseline

Latest verified code baseline after merging Slice 2:

- Full test suite on merged `dev`: `224 passed, 1 skipped`
- CLI smoke:
  - indexed fixture: `11 files -> 20 chunks`
  - query path returned AST function chunks
  - DB metadata checks confirmed expected `auth.py` and `util.js` function chunks

Latest verification in the current session:

- Baseline before final plan execution: `224 passed, 1 skipped`.
- Task 1 focused verification: `12 passed`.
- Task 2 focused verification including vectorize regression coverage after fixes: `24 passed`.
- Task 2A focused verification: `46 passed`.
- Task 3 focused verification after final ordering fix: `19 passed`.
- Task 3 targeted code-quality re-review approved with no findings.
- Task 4 full suite: `286 passed, 1 skipped`.
- Task 4 smoke passed:
  - vectorize summary had `nodes_symbol: 31` and `edges_symbol: 34`;
  - fast query reported `pipeline_used: fast`;
  - full query reported `pipeline_used: full` and `expansion_size: 9`.
- Task 5 focused verification: `32 passed`.
- Task 5 full-suite regression: `297 passed, 1 skipped`.
- Task 5 prepared-venv smoke passed:
  - vectorized `tests/fixtures/simple-python`;
  - `cbv stats simple-python --top-k 3` returned nonzero PageRank top nodes, highest `pkg/db.py::open_conn` at `0.104394`.
- Task 5 targeted re-review approved with no findings.
- Task 5A focused verification: `20 passed`.
- Task 5A full-suite regression: `304 passed, 1 skipped`.
- Task 5A prepared-venv smoke passed:
  - vectorized `tests/fixtures/simple-python`;
  - full-lane query returned `pipeline_used: full`, `expansion_size: 9`, and `ppr` in result source tags.
- Task 5A targeted spec re-review approved with no findings; code-quality re-review had one minor fallback-candidate issue fixed in `6555c04`.
- Task 6 focused verification: `36 passed`.
- Task 6 full-suite regression: `331 passed, 1 skipped`.
- Task 6 prepared-venv smoke passed:
  - vectorized `tests/fixtures/simple-python`;
  - `relate callers`, `graph` alias, and `flow` alias all executed;
  - `flow` returned clean `flow not indexed` fallback JSON before real CFG/DFG extraction exists.
- Task 6 targeted spec re-review and code-quality re-review approved with no findings.
- Task 7 focused verification: `22 passed`.
- Task 7 full-suite regression: `343 passed, 1 skipped`.
- Task 7 whitespace check: `git diff --check f10ed3b..HEAD` reported no issues.
- Task 7 targeted spec re-review approved with no findings after withdrawing the empty-sentinel metadata objection.
- Task 7 targeted code-quality re-review approved after withdrawing the spec-defined 512-character reranker cap objection.
- Task 8 focused verification: `34 passed`.
- Task 8 full-suite regression: `354 passed, 1 skipped`.
- Task 8 whitespace check: `git diff --check e17d633..HEAD` reported no issues.
- Task 8 targeted spec re-review approved with no findings.
- Task 8 targeted code-quality re-review approved with no findings.
- Task 9 focused verification after final atomicity fix: `42 passed`.
- Task 9 full-suite regression after final atomicity fix: `373 passed, 1 skipped`.
- Task 9 whitespace check: `git diff --check f0e034a..HEAD` reported no issues.
- Task 9 targeted spec re-review approved with no findings.
- Task 9 targeted code-quality re-review approved with no findings after probing rollback during PageRank, rollback after meta writes, and update-mode `--no-cache`.
- Task 10 focused verification after final scope fix: `74 passed`.
- Task 10 full-suite regression after final scope fix: `386 passed, 1 skipped`.
- Task 10 whitespace check: `git diff --check 24b2037..HEAD` reported no issues.
- Task 10 targeted spec re-review approved with no findings.
- Task 10 targeted code-quality re-review approved with no findings.
- Task 10A focused verification after final C/C++ parameter fix: `68 passed`.
- Task 10A adjacent vectorize/full-index/incremental regression after final fix: `37 passed`.
- Task 10A full-suite regression after final fix: `417 passed, 1 skipped`.
- Task 10A whitespace check: `git diff --check fd2725d..HEAD` reported no issues.
- Task 10A targeted spec re-review approved with no findings.
- Task 10A targeted code-quality re-review approved with no findings.
- Task 11 focused verification after final cluster freshness/centroid guard fix: `61 passed`.
- Task 11 adjacent cluster/embedder/vectorize/full-index verification after final fix: `39 passed`.
- Task 11 bootstrap dispatch verification after final fix: `13 passed`.
- Task 11 full-suite regression after PPR fallback fix: `436 passed, 1 skipped`.
- Task 11 whitespace check: `git diff --check 8ee711c..HEAD` reported no issues.
- Task 11 final spec re-review approved with no findings.
- Task 11 final code-quality re-review approved with no blocking findings.
- Task 12 required/focused verification after benchmark/artifact fixes: `45 passed`.
- Task 12 integration regression for full index/query/relate paths: `56 passed`.
- Task 12 full-suite regression after warning-expectation updates: `453 passed, 1 skipped`.
- Task 12 whitespace check: `git diff --check e31db83..HEAD` reported no issues.
- Task 12 final spec review approved with no findings.
- Task 12 final code-quality re-review approved with no blocking findings.
- Task 13 required docs coverage grep passed:
  `rg "vectorize|query|relate|stats|graph|flow|bench|--lane|--update|codebase-relate" README.md skills docs\HANDOFF.md`
- Task 13 whitespace check: `git diff --check 52326b1..HEAD` reported no issues.
- Task 13 final spec review approved: `SPEC APPROVED: compliant`.
- Task 13 final code-quality review approved: `APPROVED: no blocking code-quality issues`.
- Task 14 full suite: `453 passed, 1 skipped`.
- Task 14 final CLI smoke passed:
  - first vectorize summary had nonzero chunks, symbol nodes, and symbol edges;
  - fast query reported `pipeline_used: fast`;
  - full query reported `pipeline_used: full` and `expansion_size: 9`;
  - `relate`, `graph`, and `flow` returned JSON with `results`;
  - `stats` returned counts;
  - `bench` printed result JSON;
  - no-change `vectorize --update` completed and correctly reported `embedding_cache_hit_rate: 0.0`.
- Task 14 stale-expectation review result: `PLAN_EXPECTATION_STALE`.
- Task 14 git-state check at `93ef0ba`: clean working tree on `dev`, ahead of `origin/dev`.

## What Exists Today

v1.0 initial version is code-complete through Task 14 final verification. The
current implementation includes:

- `scripts/cbv/` package replacing the old v0.3.0 scripts.
- v1.0 SQLite schema and populated chunks, FTS5 rows, sqlite-vec rows, metadata,
  identifier trigrams, symbol graph, flow graph, Merkle rows, concept clusters,
  and artifact metadata.
- Source population, file walking, tree-sitter + cAST chunking with line-aware
  fallback, INT8 quantization, embedder factory, and CLI commands.
- Query router and `query --lane auto|fast|full`.
- Fast lane using symbol exact, identifier trigrams, and BM25 without dense
  embedding.
- Full lane using BM25, dense, symbol exact, graph expansion, Personalized
  PageRank, Reciprocal Rank Fusion, cross-encoder reranking, and low-confidence
  `refined_queries` hints.
- Global PageRank computation over symbol nodes during vectorize.
- `stats` command with counts, cluster label details, and top PageRank nodes.
- `relate` command, plus `graph` and `flow` aliases, for graph/relationship queries over indexed repos.
- `codebase-relate` skill documenting caller/callee, neighborhood, path, concept, PageRank, and flow query usage.
- Cross-repo content-hash embedding cache with `--no-cache`, hit-rate reporting, wrong-length fallback, and stale-schema migration.
- Merkle incremental indexing with `vectorize --update`, safe Merkle backfill, retryable chunk failures, and transactional update writes.
- Spec-complete Task 10A intra-procedural flow indexing with block nodes, `controls`/`guards`/`dataflow` edges, vectorize flow counts, Tier-A best-effort tree-sitter coverage, and semantic flow relate JSON.
- Spec-aligned concept clusters using UMAP + HDBSCAN, stored centroids, soft chunk memberships, configurable LLM labels with warning-backed deterministic fallback, safe incremental cluster refresh, and `relate concept-cluster`.
- `ARCHITECTURE.md` generation after vectorize with configurable local LLM command, deterministic warning-backed fallback, and non-critical artifact failure handling.
- `bench <repo>` and optional `vectorize --bench`, with CoIR/RepoEval-style JSONL inputs, file-level MRR@10/NDCG@10/Recall@5/Recall@10 scoring, `bench/results.json`, zeroed results when no rows exist, and summary `bench_results`.

Important implementation detail:

- sqlite-vec `INT8[...]` insertion/query must use `vec_int8(?)` with JSON strings. Do not use raw bytes; sqlite-vec 0.1.x treats raw bytes as float32.

## Spec Authority

The master document is:

- `specs/2026-05-14-codebase-vectorizer-v1.0-design.md`

The spec is authoritative over all plans. The final completion plan has been revised so reduced local MVP behavior is allowed only as an intermediate bootstrap step or as an explicit spec-defined fallback. It is not the final definition of done.

Spec-required surfaces through Task 14:

1. README and skill docs are aligned to final behavior by the documentation pass.
2. Task 13 spec and quality reviews passed, and the plan checklist is marked complete.
3. Task 14 full suite, CLI smoke, git-state check, and plan checklist are complete.

## Completion Tracking Rule

The active completion plan now repeats this directive across the plan:

> When a task can be safely designated as done, mark the task as complete by editing the completion plan.

Operational meaning:

- After a task's implementation, verification command, and commit step succeed, edit `docs/plans/2026-05-15-codebase-vectorizer-v1.0-final-vertical-completion.md`.
- Change the relevant checklist items from `- [ ]` to `- [x]`.
- Do not rely on terminal output, chat history, or commit messages as the only completion record.
- If a task is superseded, document that explicitly in the plan and only mark it complete if the replacement is spec-aligned.
- Any unchecked task at the final verification gate is a blocker unless explicitly superseded in the plan.

## Recommended Next Workflow

User requested:

- Write and execute on `dev`.
- No worktrees for this final plan unless explicitly redirected later.
- The spec is the master doc.

Recommended next action:

1. Commit the final Task 14 plan/handoff state.
2. Run one final `git status --short --branch` check after that commit.
3. Do not merge or open a PR unless the user explicitly requests it.

## Do Not Drift

- Do not replace spec-required behavior with deterministic test-only shortcuts.
- Do not call heuristic symbols, global PageRank alone, deterministic cluster labels, or deterministic architecture summaries "v1.0 done".
- Do not leave plan checklist state stale after completing tasks.
- Do not polish endlessly before the product exists.
- Do not build around failures or leave sloppy programming.
