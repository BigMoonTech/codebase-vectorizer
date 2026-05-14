# codebase-vectorizer

A Claude Code plugin that turns any public GitHub repo (or local folder) into a **local, queryable, token-efficient codebase index**. One expensive indexing pass up front; cheap RAG-style lookups forever after.

## What it does

- **`vectorize-repo` skill** — clone, chunk, embed, and store a repo in a local
  SQLite database (FTS5 keyword index + `sqlite-vec` ANN vector index). Slice 1
  uses line-aware text-window chunking and `jinaai/jina-code-embeddings-1.5b`
  (1536-dim, INT8-quantized). Tree-sitter + cAST chunking, symbol graph, flow
  graph, concept clusters, and the `codebase-relate` skill ship in subsequent
  slices.
- **`codebase-query` skill** — auto-triggers on questions about an indexed
  codebase. Runs BM25 + dense KNN + Reciprocal Rank Fusion and returns the
  top-k file:line ranges. Cross-encoder rerank, graph expansion, fast-lane
  routing, and confidence-based query refinement land in later slices.

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
└── repos/
    └── <repo-name>/
        ├── source/          ← the cloned repo
        ├── index.sqlite     ← FTS5 + sqlite-vec index
        ├── manifest.json
        └── ARCHITECTURE.md  ← orientation map written after indexing
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

## How retrieval works (Slice 1)

1. **Chunking**: line-aware text-window splitter (1500-byte budget) preserves
   the concat == file invariant. Future slices use tree-sitter + cAST.
2. **Embeddings**: every chunk is embedded with `jinaai/jina-code-embeddings-1.5b`
   (1536-dim, INT8-quantized). GPU path uses transformers FP16; CPU path uses
   `llama-cpp-python` with GGUF INT4. Local, no API keys.
3. **Storage**: full v1.0 schema (ten tables) created at index time;
   Slice 1 populates `chunks` (canonical), `chunks_fts` (FTS5 BM25),
   `vec_chunks` (`sqlite-vec` INT8 ANN), and `meta`. Same `rowid` across
   `chunks` and the FTS view; `chunk_id` links to `vec_chunks`.
4. **Query**: the query is embedded; BM25 and dense KNN run top-50 each, then
   Reciprocal Rank Fusion picks the top-k. Output is v1.0-shape JSON with
   `pipeline_used`, `refined_queries`, and `expansion_size` keys (the latter
   two stay zero/empty until later slices).
5. **Read**: Claude opens each returned file at the specified line range using
   `Read(file_path, offset, limit)`.

## Standalone CLI (no Claude Code needed)

The scripts work without the plugin too:

```bash
# POSIX
bash scripts/run.sh vectorize https://github.com/coleam00/Archon
bash scripts/run.sh query Archon "agent orchestration" --top-k 6
bash scripts/run.sh list
bash scripts/run.sh info       # print data dir + venv paths

# Windows PowerShell
.\scripts\run.ps1 vectorize https://github.com/coleam00/Archon
.\scripts\run.ps1 query Archon "agent orchestration" --top-k 6
```

When run standalone (outside a Claude Code session), `${CLAUDE_PLUGIN_DATA}` isn't set, so data falls back to `~/.local/share/codebase-vectorizer/` on POSIX or `%LOCALAPPDATA%\codebase-vectorizer\` on Windows.

## Limits & known trade-offs (Slice 1)

- **Text-window chunking, not tree-sitter**: chunks respect line boundaries
  and the byte budget, but do not align to function/class boundaries. Slice 2
  adds tree-sitter + cAST chunking.
- **No symbol graph yet**: caller/callee questions don't get graph expansion
  until Slice 3.
- **No cross-encoder rerank**: top-k is RRF-only. Slice 5 adds
  `mxbai-rerank-large-v2`.
- **No incremental re-indexing**: each `vectorize` is a full re-clone + re-embed.
  Slice 12 adds Merkle-based incremental updates.
- **No fast-lane router**: identifier-like queries take the full pipeline.
  Slice 4 adds the router + identifier trigram index.
- **Default file limit is 1.5 MB** per file. Use `--max-file-mb` to raise it.
- **Indexes from v0.3.0 are not auto-upgraded**: queries against them return a
  clean "legacy schema" error; re-run `vectorize-repo` to upgrade.

## License

MIT. See `LICENSE`.
