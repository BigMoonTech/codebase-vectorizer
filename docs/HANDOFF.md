# codebase-vectorizer v1.0 Handoff

## Current State

- Branch: `dev`
- Current HEAD: `281cf27 docs: mark task 2 complete`
- `dev` is ahead of `origin/dev` by seven local commits:
  - `b5886bd slice 3 t1: index identifier trigrams`
  - `4dd8597 slice 3 t1: address identifier review`
  - `1d6bdc4 docs: mark task 1 complete`
  - `4196e6d slice 3 t2: populate symbol graph`
  - `758be1e slice 3 t2: address symbol graph review`
  - `2104d5b slice 3 t2: preserve chunkless file nodes`
  - `281cf27 docs: mark task 2 complete`
- `main` is preserved and should stay preserved.
- Slice 1 is implemented, merged into `dev`, and pushed.
- Slice 2 is implemented, merged into `dev` with `--no-ff`, verified, cleaned up, and pushed.
- The active execution plan is:
  - `docs/plans/2026-05-15-codebase-vectorizer-v1.0-final-vertical-completion.md`

## Current Uncommitted Work

This handoff was updated during Task 2 review. At the moment of this update:

- Task 1 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2 is implemented, reviewed, committed, and marked complete in the final completion plan.
- Task 2A is in progress with a fresh subagent.
- Task 2 review fixes landed in `758be1e` and `2104d5b`:
  - Duplicate short-name edge resolution drops ambiguous edges unless full-name resolution succeeds.
  - Parser-failure/file-node behavior preserves file nodes and emits `symbol extraction failed for <file>: <error>` warnings while indexing continues.
  - Empty indexable files that produce no chunks now get `kind='file'` nodes with `chunk_id = NULL`.
- The only expected uncommitted change is this handoff state correction itself.

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

Important implementation detail:

- sqlite-vec `INT8[...]` insertion/query must use `vec_int8(?)` with JSON strings. Do not use raw bytes; sqlite-vec 0.1.x treats raw bytes as float32.

## Spec Authority

The master document is:

- `specs/2026-05-14-codebase-vectorizer-v1.0-design.md`

The spec is authoritative over all plans. The final completion plan has been revised so reduced local MVP behavior is allowed only as an intermediate bootstrap step or as an explicit spec-defined fallback. It is not the final definition of done.

Spec-required surfaces still to implement:

1. tags.scm-backed Tier-A symbol extraction.
2. Query router with fast/full lanes.
3. Graph expansion plus query-time Personalized PageRank.
4. Cross-encoder reranking and refined-query hints.
5. `codebase-relate`, plus `graph` and `flow` CLI aliases.
6. Content-hash embedding cache.
7. Merkle incremental indexing.
8. Intra-procedural CFG/DFG flow edges and flow relate verbs.
9. UMAP + HDBSCAN concept clusters with LLM labels and spec-defined fallback.
10. One-pass LLM `ARCHITECTURE.md` with spec-defined fallback.
11. CoIR/RepoEval-style benchmark metrics and `bench/results.json`.
12. README and skill docs aligned to final behavior.

Task 2 note: symbol graph nodes/edges now exist as the planned bootstrap implementation, but do not call symbol extraction spec-complete until Task 2A lands.

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

1. Finish Task 2A implementation and review loop.
2. If Task 2A reviews pass, mark Task 2A complete in `docs/plans/2026-05-15-codebase-vectorizer-v1.0-final-vertical-completion.md` and commit the checklist update.
3. Continue with Task 3 using `superpowers:subagent-driven-development` with fresh subagents and review after each task.
4. After each task is safely done, edit the plan to mark completed checklist items.
5. Run each task's verification command before committing.
6. Run the final full verification gate before calling v1.0 code-complete.

## Do Not Drift

- Do not replace spec-required behavior with deterministic test-only shortcuts.
- Do not call Python-only flow, heuristic symbols, global PageRank alone, deterministic cluster labels, or deterministic architecture summaries "v1.0 done".
- Do not leave plan checklist state stale after completing tasks.
- Do not polish endlessly before the product exists.
- Do not build around failures or leave sloppy programming.
