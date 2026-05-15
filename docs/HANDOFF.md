# codebase-vectorizer v1.0 Handoff

## Current State

- Branch: `dev`
- Latest confirmed implementation commit: `601d6b2 slice 5 t1: rerank full chunk content`
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
- `main` is preserved and should stay preserved.
- Slice 1 is implemented, merged into `dev`, and pushed.
- Slice 2 is implemented, merged into `dev` with `--no-ff`, verified, cleaned up, and pushed.
- The active execution plan is:
  - `docs/plans/2026-05-15-codebase-vectorizer-v1.0-final-vertical-completion.md`

## Current Working State

This handoff was updated after Task 7 approval:

- Task 1 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2A is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 3 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 4 checkpoint verification passed and is marked complete in the final completion plan.
- Task 5 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 5A is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 6 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 7 is implemented, reviewed, committed, and marked complete in the final completion plan.
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
- Task 2 review fixes landed in `758be1e` and `2104d5b`:
  - Duplicate short-name edge resolution drops ambiguous edges unless full-name resolution succeeds.
  - Parser-failure/file-node behavior preserves file nodes and emits `symbol extraction failed for <file>: <error>` warnings while indexing continues.
  - Empty indexable files that produce no chunks now get `kind='file'` nodes with `chunk_id = NULL`.
- Next action is Milestone 4 Task 8: content-hash embedding cache.

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

## What Exists Today

Slice 1 delivered the first working v1.0 vertical:

- Replaced the old v0.3.0 scripts with the `scripts/cbv/` package.
- Added v1.0 SQLite schema creation for all ten tables.
- Populates `chunks`, `chunks_fts`, `vec_chunks`, and `meta`.
- Added source population, file walking, line-aware fallback chunking, INT8 quantization, embedder factory, CLI commands, and query pipeline.
- Query pipeline currently uses BM25 + dense KNN + Reciprocal Rank Fusion.
- Updated `vectorize-repo` and `codebase-query` skills to v1.0 JSON shape.

Slice 2 added AST-aware chunking:

- Added tree-sitter integration through `scripts/cbv/parser.py`.
- Added cAST chunking through `scripts/cbv/cast_chunker.py`.
- Refactored `scripts/cbv/chunker.py` into AST-first orchestration with text-window fallback.
- Preserved stable `Chunk` shape and existing vectorize/query surfaces.
- Added broad unit coverage for AST chunk kind/name/path behavior and integration coverage for JavaScript AST chunks.

Current Slice 3/Milestone 1 work adds:

- Identifier trigram indexing in `symbol_trigrams`.
- Tier-A query-backed symbol extraction for definitions, variables, imports, calls, inherits, and references.
- Symbol graph persistence in `nodes` and `edges`, including chunkless file nodes.
- Query router and `--lane auto|fast|full`.
- Fast lane using symbol exact, identifier trigrams, and BM25 without dense embedding.
- Full lane using BM25, dense, symbol exact, graph expansion, and RRF.
- Global PageRank computation over symbol nodes during vectorize.
- `stats` command with counts, cluster label details, and top PageRank nodes.
- Query-time Personalized PageRank in the full lane, seeded from the post-expansion bounded set.
- `relate` command, plus `graph` and `flow` aliases, for graph/relationship queries over indexed repos.
- `codebase-relate` skill documenting caller/callee, neighborhood, path, concept, PageRank, and flow query usage.
- Cross-encoder reranker adapter with deterministic stub path.
- Full-lane reranking, query-time `reranker_model`, and low-confidence `refined_queries` hints.

Important implementation detail:

- sqlite-vec `INT8[...]` insertion/query must use `vec_int8(?)` with JSON strings. Do not use raw bytes; sqlite-vec 0.1.x treats raw bytes as float32.

## Spec Authority

The master document is:

- `specs/2026-05-14-codebase-vectorizer-v1.0-design.md`

The spec is authoritative over all plans. The final completion plan has been revised so reduced local MVP behavior is allowed only as an intermediate bootstrap step or as an explicit spec-defined fallback. It is not the final definition of done.

Spec-required surfaces still to implement:

1. Content-hash embedding cache.
2. Merkle incremental indexing.
3. Intra-procedural CFG/DFG flow edges and useful flow relate results beyond fallback.
4. UMAP + HDBSCAN concept clusters with LLM labels and spec-defined fallback.
5. One-pass LLM `ARCHITECTURE.md` with spec-defined fallback.
6. CoIR/RepoEval-style benchmark metrics and `bench/results.json`.
7. README and skill docs aligned to final behavior.

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

1. Begin Milestone 4 Task 8 for the content-hash embedding cache.
2. After Task 8 implementation, verification, and review pass, mark Task 8 complete in `docs/plans/2026-05-15-codebase-vectorizer-v1.0-final-vertical-completion.md`.
3. Continue with Merkle incremental indexing work.
4. After each task is safely done, edit the plan to mark completed checklist items.
5. Run each task's verification command before committing.
6. Run the final full verification gate before calling v1.0 code-complete.

## Do Not Drift

- Do not replace spec-required behavior with deterministic test-only shortcuts.
- Do not call Python-only flow, heuristic symbols, global PageRank alone, deterministic cluster labels, or deterministic architecture summaries "v1.0 done".
- Do not leave plan checklist state stale after completing tasks.
- Do not polish endlessly before the product exists.
- Do not build around failures or leave sloppy programming.
