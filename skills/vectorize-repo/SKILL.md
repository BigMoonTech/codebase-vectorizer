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
  version: "0.3.0"
---

# Vectorize Repo

Index a public GitHub repo (or local folder) into a local SQLite + sqlite-vec database so future codebase questions cost a few hundred tokens instead of tens of thousands.

The user provides a GitHub URL or a local path. Extract that argument from their message and pass it to the indexer verbatim.

This skill does two things in sequence:

1. **Deterministic phase** — clone, chunk, and embed the repo into a local SQLite + sqlite-vec index. No LLM tokens spent.
2. **One LLM pass** — read the manifest and a small sample of pivotal files, then write `ARCHITECTURE.md` (a high-level orientation map) into the repo's index directory.

After this skill runs, the `codebase-query` skill auto-fires on future questions about the repo and answers them from the index — **from any working directory on this host**.

## Where things live

All plugin data is stored under `${CLAUDE_PLUGIN_DATA}` (Claude Code sets this env var per plugin; it persists across plugin updates):

```
${CLAUDE_PLUGIN_DATA}/
├── python-env/          ← the plugin's isolated Python interpreter + deps
└── repos/
    └── <repo-name>/
        ├── source/      ← the cloned repo
        ├── index.sqlite ← FTS5 + sqlite-vec index
        ├── manifest.json
        └── ARCHITECTURE.md
```

The venv is named `python-env/` — not `.venv` — so it can never be mistaken for a project's own virtual environment. It is invoked by absolute path and **never activated**, so the user's shell environment, project venvs, and `PATH` are untouched.

## Step 1 — Run the indexer

The launcher (`run.sh` on POSIX, `run.ps1` on Windows) handles everything: finds a usable Python 3.10–3.13, bootstraps the venv on first use, installs deps with prebuilt wheels only, downloads the BGE-small embedding model (~130 MB, one-time, to the user's HuggingFace cache), then runs the indexer.

**On POSIX (macOS, Linux, WSL):**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" vectorize "<github_url_or_path>"
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" vectorize "<github_url_or_path>"
```

First invocation takes ~2–3 minutes (venv + deps + model). Subsequent runs are seconds + index time. The script ends with a JSON summary like:

```json
{
  "repo_name": "react",
  "source_dir": ".../repos/react/source",
  "db_path": ".../repos/react/index.sqlite",
  "manifest_path": ".../repos/react/manifest.json",
  "files_indexed": 1247,
  "chunks_indexed": 18402,
  "elapsed_seconds": 84.3
}
```

If the script errors, surface the error and stop — do not proceed to the LLM pass on a broken index.

## Step 2 — One LLM pass: write ARCHITECTURE.md

After the indexer succeeds:

1. **Read the manifest** at `manifest_path` from the JSON. It lists every indexed file with path, language, and chunk count.
2. **Identify pivotal files**: package metadata (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `README.md`, top-level `*.md`), entry points (`main.*`, `index.*`, `app.*`, `__main__.py`), and the 5–10 largest source files in the most common language.
3. **Read those files** with the Read tool — they're usually small.
4. **Write `<source_dir>/../ARCHITECTURE.md`** with these sections:
   - **Overview** (2–4 sentences: what the project does)
   - **Languages & frameworks** (a short list)
   - **Entry points** (where execution starts)
   - **Module map** (one bullet per top-level directory)
   - **Key abstractions** (3–7 most important concepts)
   - **How to query this repo** (one sentence pointing at the codebase-query skill)

Cap at ~1500 words. It's a map, not a manual.

## Step 3 — Report to user

Tell the user in plain English:

- Repo name + counts (files, chunks, elapsed) from the JSON summary
- Where the index lives (the `db_path` directory)
- That they can now ask codebase questions **from any working directory** and the `codebase-query` skill will answer using the index
- That `ARCHITECTURE.md` is the starting map

**Do not** read further into the repo after this. Future questions go through the query skill, not by burning tokens here.

## Troubleshooting

- **"No Python 3.10–3.13 found"** — install Python 3.12. Windows: `winget install Python.Python.3.12`. Debian/Ubuntu/WSL: `sudo apt install python3.12 python3.12-venv`. macOS: `brew install python@3.12`.
- **Wheels fail on first install** — almost always because the user's Python is too new (3.14+) and `py-rust-stemmers` has no prebuilt wheel yet. Install Python 3.12 and re-run; the launcher picks it up automatically.
- **Reset the plugin's state** — delete `${CLAUDE_PLUGIN_DATA}/python-env/` and re-run; deps will reinstall. Delete `${CLAUDE_PLUGIN_DATA}/repos/<name>/` to drop a single index.
