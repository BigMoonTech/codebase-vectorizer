---
name: vectorize-repo
description: >
  Clone, chunk, and vector-index a public GitHub repo (or local folder) for cheap
  future queries. Use when the user says "vectorize this repo", "index this codebase",
  "index <repo>", "build an index for <repo>", "make this repo searchable", "RAG this
  repo", or provides a GitHub URL and asks to index/learn/explore it. Also triggers
  when the user wants to set up a codebase for later querying via the codebase-query
  skill.
metadata:
  version: "1.0.0"
---

# Vectorize Repo

Index a public GitHub repo (or local folder) into a local SQLite database (FTS5 +
`sqlite-vec`) so future codebase questions cost a few hundred tokens instead of
tens of thousands.

The user provides a GitHub URL or a local path. Extract that argument from their
message and pass it to the indexer verbatim.

## What v1.0 indexing does

1. **Resolve source** — clone (URL) or copy (local) into `<repo_dir>/source/`.
2. **Walk + filter** — `.gitignore` (root), files > 1.5 MB, binaries via NUL sniff.
3. **Chunk** — tree-sitter + cAST chunks for supported languages, with
   line-aware text windows as fallback.
4. **Embed** — `jinaai/jina-code-embeddings-1.5b` (1536-dim). GPU path uses
   transformers FP16; CPU path uses llama-cpp-python GGUF INT4. Embeddings are
   INT8-quantized into `sqlite-vec`; the cross-repo embedding cache is used
   unless `--no-cache` is passed.
5. **Write index data** — chunks, FTS5 rows, vector rows, identifier trigrams,
   symbol graph, flow graph, PageRank scores, concept clusters, Merkle hashes,
   and metadata.
6. **Write artifacts** — `ARCHITECTURE.md` after indexing, and
   `bench/results.json` when `--bench` runs.

`vectorize --update` preserves a compatible existing index, reprocesses only
added/modified/deleted files using Merkle hashes, and keeps unchanged chunks and
embeddings. Use plain `vectorize` for a full rebuild.

## Where things live

All plugin data is stored under `${CLAUDE_PLUGIN_DATA}` (Claude Code sets this
env var per plugin; it persists across plugin updates):

```
${CLAUDE_PLUGIN_DATA}/
├── python-env/              the plugin's isolated Python interpreter + deps
├── embedding_cache.sqlite   cross-repo content-hash embedding cache
└── repos/
    └── <repo-name>/
        ├── source/          the cloned repo (no .git/)
        ├── index.sqlite
        ├── manifest.json
        ├── ARCHITECTURE.md
        └── bench/
            └── results.json
```

The venv is named `python-env/` — not `.venv` — so it can never be mistaken for
a project's own virtual environment. It is invoked by absolute path and **never
activated**.

`ARCHITECTURE.md` generation uses `CBV_ARCHITECTURE_COMMAND` when configured
and otherwise writes a deterministic fallback with a warning. `bench <repo>`
writes `bench/results.json`; if no benchmark query rows are found, it writes
zeroed metrics. `vectorize --bench` runs that same benchmark step after
indexing and may likewise write zeroed results when no rows are present.

## Step 1 — Run the indexer

The launcher (`run.sh` on POSIX, `run.ps1` on Windows) handles everything: finds
Python 3.10–3.13, bootstraps the venv, installs deps (`sqlite-vec`,
`transformers`, `torch`, `llama-cpp-python`, etc.), downloads the embedding
model (~750 MB GGUF, one-time, into the user's HuggingFace cache), then indexes.

**On POSIX (macOS, Linux, WSL):**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" vectorize "<github_url_or_path>"
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" vectorize "<github_url_or_path>"
```

Useful flags:

- `--update` — incrementally update an existing compatible index.
- `--no-cache` — bypass the cross-repo embedding cache.
- `--bench` — run the benchmark step after indexing.
- `--max-file-mb N` — change the default 1.5 MB per-file skip threshold.
- `--output-dir PATH` — override the repo directory location.

First invocation takes 5–15 minutes (venv + deps + model). Subsequent runs
amortize most of that — only the per-repo index work happens.

The script ends with a JSON summary on the last line of stdout:

```json
{
  "repo_name": "react",
  "source_dir": ".../repos/react/source",
  "db_path": ".../repos/react/index.sqlite",
  "manifest_path": ".../repos/react/manifest.json",
  "files_indexed": 1247,
  "chunks_indexed": 18402,
  "nodes_symbol": 0,
  "nodes_block": 0,
  "edges_symbol": 0,
  "edges_flow": 0,
  "clusters_indexed": 0,
  "elapsed_seconds": 281.4,
  "embedding_cache_hit_rate": 0.0,
  "warnings": [],
  "bench_results": {}
}
```

The zero values above are example values only. Real runs replace
`nodes_symbol`, `nodes_block`, `edges_symbol`, `edges_flow`,
`clusters_indexed`, `embedding_cache_hit_rate`, and `bench_results` with the
actual counts, cache hit rate, and benchmark summary produced by the final
implementation. A tiny or unsupported repo may legitimately report zero for
some graph or cluster fields.

If the script errors, surface the error and stop.

## Step 2 — Report to user

Tell the user in plain English:

- Repo name + counts (files, chunks, elapsed) from the JSON summary.
- Where the index lives (the `db_path` directory).
- That they can now ask codebase questions **from any working directory** and
  the `codebase-query` skill will answer using the index.

**Do not** read further into the repo after this. Future questions go through
the query skill, not by burning tokens here.

## Troubleshooting

- **"No Python 3.10–3.13 found"** — install Python 3.12.
  - Windows: `winget install Python.Python.3.12`
  - Debian/Ubuntu/WSL: `sudo apt install python3.12 python3.12-venv`
  - macOS: `brew install python@3.12`
- **Wheels fail on first install** — almost always because the user's Python is
  too new (3.14+) and `torch` or `llama-cpp-python` has no prebuilt wheel yet.
  Install Python 3.12 and re-run.
- **Model download fails** — the default GGUF repo/file may not exist for
  jina-code-embeddings-1.5b. Set `CBV_GGUF_REPO` and `CBV_GGUF_FILE` env vars
  to a known-good community quant, then re-run.
- **Reset the plugin's state** — delete `${CLAUDE_PLUGIN_DATA}/python-env/` and
  re-run; deps reinstall. Delete `${CLAUDE_PLUGIN_DATA}/repos/<name>/` to drop a
  single index. The user's v0.3.0 indexes will return a "legacy schema, please
  re-vectorize" error on query — same fix.
