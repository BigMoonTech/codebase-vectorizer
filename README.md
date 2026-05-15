# codebase-vectorizer

A Claude Code plugin that turns any public GitHub repo (or local folder) into a **local, queryable, token-efficient codebase index**. One expensive indexing pass up front; cheap RAG-style lookups forever after.

## What it does

- **`vectorize-repo` skill** — clone or copy a repo, chunk it with tree-sitter
  + cAST where supported and text windows as fallback, embed it, and store a
  local SQLite database (FTS5 keyword index + `sqlite-vec` ANN vector index).
  v1.0 also builds the symbol graph, flow graph, PageRank scores, concept
  clusters, `ARCHITECTURE.md`, optional benchmark results, and a reusable
  cross-repo embedding cache.
- **`codebase-query` skill** — auto-triggers on questions about an indexed
  codebase. Runs the `query` command with `--lane auto|fast|full`: the fast
  lane uses symbol exact, identifier trigrams, and BM25; the full lane adds
  dense KNN, graph expansion, Personalized PageRank, cross-encoder reranking,
  and confidence-based query refinements.
- **`codebase-relate` skill** — runs `relate`, `graph`, and `flow` for graph,
  inheritance, PageRank, concept-cluster, path, and dataflow/control-flow
  questions over an indexed repo.

Reading a codebase from scratch every time you ask Claude a question burns tens of thousands of tokens. After indexing, the same question costs a few hundred: the query tool returns the exact file ranges to read, and Claude opens just those.

## Install

This plugin is distributed as a git repo. Install it on each machine where you use Claude Code (Windows Desktop, WSL CLI, remote VPS, etc.). The same git URL works everywhere.

```
/plugin marketplace add <git-url-of-this-repo>
/plugin install codebase-vectorizer@codebase-vectorizer-marketplace --scope user
```

Replace `<git-url-of-this-repo>` with whatever you push this repo to (e.g. `https://github.com/<you>/codebase-vectorizer.git` or `github:<you>/codebase-vectorizer`).

## Requirements

- **Python 3.10–3.13** on PATH (3.12 recommended). Used only to bootstrap a dedicated venv — the plugin **never** touches your system Python or any project venv.
  - Windows: `winget install Python.Python.3.12`
  - Debian/Ubuntu/WSL: `sudo apt install python3.12 python3.12-venv`
  - macOS: `brew install python@3.12`
- **`git` on PATH** for cloning GitHub URLs.
- **Internet on first use** for ~250 MB of Python wheels (one-time, cached) and
  ~750 MB for the embedding model (`jinaai/jina-code-embeddings-1.5b` GGUF
  INT4, one-time, cached under `~/.cache/huggingface/`). Subsequent runs are
  fully offline.

## Where data lives

All plugin state goes under `${CLAUDE_PLUGIN_DATA}` (Claude Code sets this per plugin; it survives plugin updates):

```
${CLAUDE_PLUGIN_DATA}/
├── python-env/              ← the plugin's isolated Python interpreter + deps
├── embedding_cache.sqlite   ← cross-repo content-hash embedding cache
└── repos/
    └── <repo-name>/
        ├── source/          ← the cloned repo
        ├── index.sqlite     ← FTS5 + sqlite-vec index
        ├── manifest.json
        ├── ARCHITECTURE.md  ← orientation map written after indexing
        └── bench/
            └── results.json ← benchmark output after bench runs
```

A few design choices worth knowing:

- **The venv is named `python-env/`, not `.venv`.** Different parent directory, different name — there is no way to confuse it with any project's own venv.
- **The venv is never activated.** Its Python is invoked by absolute path. Your shell `$PATH`, `$VIRTUAL_ENV`, project venvs, and cwd are untouched. Nothing to "exit" because we never "entered" anything.
- **Indexes live in one canonical location**, not in your project's working directory. Vectorize a repo once on this host; query it from any cwd. No `.gitignore` games, nothing accidentally committed.

Override the data root with the `CODEBASE_VECTORIZER_HOME` env var if you need to.

## Usage

After install, just ask Claude:

```
Index https://github.com/coleam00/Archon
```

Then later, from any project anywhere on this machine:

```
In Archon, how does the orchestrator handle workflow dispatch?
```

The `codebase-query` skill fires, hits the local index, and Claude reads only the file ranges that matched.

## How retrieval works in v1.0

1. **Chunking**: tree-sitter + cAST chunks align to supported functions,
   methods, classes, imports, and blocks. Unsupported files fall back to the
   line-aware text-window splitter.
2. **Embeddings + cache**: every chunk is embedded with
   `jinaai/jina-code-embeddings-1.5b` (1536-dim, INT8-quantized). GPU path uses
   transformers FP16; CPU path uses `llama-cpp-python` with GGUF INT4. The
   cross-repo `embedding_cache.sqlite` stores embeddings by content hash and
   model metadata; pass `vectorize --no-cache` to bypass it.
3. **Storage**: the v1.0 schema stores chunks, FTS5 BM25 rows, sqlite-vec ANN
   rows, identifier trigrams, symbol nodes/edges, flow nodes/edges, Merkle file
   hashes, PageRank scores, concept clusters, and metadata.
4. **Incremental updates**: `vectorize --update <url|path>` preserves a
   compatible existing index, reprocesses added/modified/deleted files from
   Merkle hashes, and keeps unchanged chunks and embeddings.
5. **Query**: `query <repo> <question> --lane auto|fast|full` routes
   identifier-like lookups to the fast lane by default and natural-language
   questions to the full lane. Full-lane results fuse BM25, dense retrieval,
   symbol exact matches, graph expansion, Personalized PageRank, and reranker
   scores.
6. **Read**: Claude opens each returned file at the specified line range using
   `Read(file_path, offset, limit)`.

## Standalone CLI (no Claude Code needed)

The scripts work without the plugin too:

```bash
# POSIX
bash scripts/run.sh vectorize https://github.com/coleam00/Archon
bash scripts/run.sh vectorize /path/to/local/repo --update
bash scripts/run.sh vectorize https://github.com/coleam00/Archon --bench
bash scripts/run.sh query Archon "agent orchestration" --top-k 6 --lane auto
bash scripts/run.sh query Archon "Router::dispatch" --lane fast
bash scripts/run.sh query Archon "how workflow dispatch works" --lane full
bash scripts/run.sh stats Archon --top-k 10
bash scripts/run.sh relate Archon callers "dispatch"
bash scripts/run.sh relate Archon shortest-path "SourceSymbol" "TargetSymbol" --hops 4
bash scripts/run.sh graph Archon "dispatch" --hops 2
bash scripts/run.sh flow Archon "dispatch"
bash scripts/run.sh bench Archon
bash scripts/run.sh list
bash scripts/run.sh info       # print data dir + venv paths

# Windows PowerShell
.\scripts\run.ps1 vectorize https://github.com/coleam00/Archon
.\scripts\run.ps1 vectorize C:\src\my-repo --update
.\scripts\run.ps1 query Archon "agent orchestration" --top-k 6 --lane auto
.\scripts\run.ps1 relate Archon concept-cluster "authentication"
.\scripts\run.ps1 stats Archon
.\scripts\run.ps1 graph Archon "dispatch"
.\scripts\run.ps1 flow Archon "dispatch"
.\scripts\run.ps1 bench Archon
```

When run standalone (outside a Claude Code session), `${CLAUDE_PLUGIN_DATA}` isn't set, so data falls back to `~/.local/share/codebase-vectorizer/` on POSIX or `%LOCALAPPDATA%\codebase-vectorizer\` on Windows.

## Relationship, stats, and benchmark commands

- `stats <repo> [--top-k N]` prints index counts, cluster labels, and top
  PageRank nodes.
- `relate <repo> callers|callees|inheritance-chain|neighbors|concept-cluster|pagerank-top|shortest-path|paths-through|reaching-definitions|reachable-uses|conditions-for ...`
  returns JSON for symbol, cluster, path, and flow relationships.
- `graph <repo> <symbol> [--hops N]` is a convenience alias for
  `relate <repo> neighbors <symbol>`.
- `flow <repo> <symbol>` is a convenience alias for
  `relate <repo> paths-through <symbol>`.
- `bench <repo>` reads CoIR/RepoEval-style JSONL rows from `bench/` locations,
  runs full-lane queries when rows exist, writes `<repo_dir>/bench/results.json`,
  and reports MRR@10, NDCG@10, Recall@5, and Recall@10. If no rows are found,
  it still writes `bench/results.json` with zeroed metrics. `vectorize --bench`
  runs the same benchmark step after indexing and may likewise write zeroed
  results when no rows are present.

## Limits & known trade-offs

- **Default file limit is 1.5 MB** per file. Use `--max-file-mb` to raise it.
- **Indexes from v0.3.0 are not auto-upgraded**: queries against them return a
  clean "legacy schema" error; re-run `vectorize-repo` to upgrade.
- **Architecture summaries need local configuration for LLM prose**:
  `ARCHITECTURE.md` generation uses `CBV_ARCHITECTURE_COMMAND` when configured
  and otherwise writes a deterministic fallback with a warning.
- **Cluster labels and architecture prose are local-only integrations**:
  deterministic fallbacks keep indexing usable when local LLM commands are not
  configured.

## License

MIT. See `LICENSE`.
