# codebase-vectorizer

A Claude Code plugin that turns any public GitHub repo (or local folder) into a **local, queryable, token-efficient codebase index**. One expensive indexing pass up front; cheap RAG-style lookups forever after.

## What it does

- **`/vectorize-repo` skill** — clone, chunk, embed, and store a repo in a local SQLite database (FTS5 keyword index + `sqlite-vec` ANN vector index). Then triggers one LLM pass to write a top-level `ARCHITECTURE.md`.
- **`/codebase-query` skill** — auto-triggers when you ask about an indexed codebase. Runs a hybrid keyword + semantic search, returns top file:line ranges, and Claude reads only those.

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
- **Internet on first use** for ~50 MB of Python wheels (one-time, cached) and ~130 MB for the BGE-small embedding model (one-time, cached under `~/.cache/huggingface/`). Subsequent runs are fully offline.

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

## How retrieval works

1. **Chunking**: language-aware regex splits Python/JS/TS/Go/Rust/Java/etc. by function & class boundaries. Markdown by headings. Everything else by 150-line sliding windows. Each chunk knows its file path, kind (function/class/section/window), name, and exact line range.
2. **Embeddings**: every chunk is embedded with `BAAI/bge-small-en-v1.5` (384-dim) via [`fastembed`](https://github.com/qdrant/fastembed) on ONNX. Local CPU, no API keys, no Docker, no servers.
3. **Storage**: three tables in one SQLite file — `chunks` (canonical), `chunks_fts` (FTS5 BM25), `vec_chunks` (`sqlite-vec` ANN). Same `rowid` across all three.
4. **Query**: hybrid retrieval. The query is embedded, FTS5 and vector searches run in parallel, results are fused with Reciprocal Rank Fusion (RRF), top-k chunks come back with absolute paths and line ranges.
5. **Read**: Claude opens each returned file at the specified line range using `Read(file_path, offset, limit)`.

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

## Limits & known trade-offs

- **English-only embeddings**: BGE-small is trained on English. Non-English code comments still work for keyword search but may retrieve weaker semantically.
- **Regex-based chunking**: deterministic and fast, but not as semantically precise as tree-sitter. Most function/class boundaries are caught.
- **No incremental re-indexing**: each `vectorize` is a full re-clone + re-embed. Fine for repos up to ~50k chunks (5–15 min); larger monorepos will be slower.
- **Default file limit is 1.5 MB** per file. Use `--max-file-mb` to raise it.

## License

MIT. See `LICENSE`.
