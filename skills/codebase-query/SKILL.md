---
name: codebase-query
description: >
  This skill should be used when the user asks any question about a codebase that has
  been indexed by the vectorize-repo skill. Triggers on phrases like "in <repo>, how
  does...", "find <function> in <repo>", "where is X defined", "show me the auth flow",
  "explain the routing in <repo>", or any question that references an indexed repo.
  Also triggers when the conversation context shows a recent vectorize-repo run and
  the user asks a follow-up about the codebase.
metadata:
  version: "0.3.0"
---

# Codebase Query

Answer codebase questions token-efficiently by querying the pre-built SQLite + vector index, then reading only the specific file ranges the query returns. **Never scan the indexed repo with Glob/Grep/Read on full files unless the query tool comes back empty.** That defeats the entire purpose of this plugin.

Indexes live in `${CLAUDE_PLUGIN_DATA}/repos/` — the same location regardless of where the user runs `claude`. Vectorize once, query from anywhere.

## When this skill fires

For any question that's clearly about an indexed codebase. Examples:

- "In react, how does useState work?"
- "Find the rate limiter in the express repo I indexed."
- "Where is `parseConfig` defined?"
- "What does the auth middleware do?"
- "Explain the build pipeline."

If the user names a repo, use that. If they don't, list what's available (Step 1) and ask which — unless there is exactly one indexed repo, in which case use it.

## Workflow

### 1. List available indexed repos

The launcher manages the plugin's venv and discovers indexed repos under `${CLAUDE_PLUGIN_DATA}/repos/`:

**On POSIX (macOS, Linux, WSL):**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" list
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" list
```

If the output is empty, tell the user no codebases are indexed yet and suggest running the vectorize-repo skill with a GitHub URL or local path. Stop here.

### 2. Run the query tool

Pass the user's question verbatim — do not paraphrase.

**On POSIX:**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" query <repo_name> "<exact user question>" --top-k 6
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" query <repo_name> "<exact user question>" --top-k 6
```

The script prints JSON to stdout:

```json
{
  "repo": "react",
  "query": "how does useState work",
  "repo_dir": "/abs/path/to/repos/react",
  "results": [
    {
      "rank": 1,
      "file_absolute": "/abs/path/to/repos/react/source/packages/react/src/ReactHooks.js",
      "file_relative": "packages/react/src/ReactHooks.js",
      "start_line": 42,
      "end_line": 87,
      "kind": "function",
      "name": "useState",
      "score": 0.91,
      "preview": "first ~200 chars of the chunk..."
    }
  ]
}
```

### 3. Read only the returned ranges

For each result, use the Read tool with `offset` and `limit` so you load only those lines, not the whole file. To read lines 42–87:

```
Read(file_path="/abs/path/.../ReactHooks.js", offset=42, limit=46)
```

Read at most 3–5 chunks unless the question clearly demands more. If the chunks reference other symbols you need to understand, run another `query` call rather than opening more files blindly.

### 4. Orient with ARCHITECTURE.md (optional)

If the query results feel disconnected from the question — e.g. the user asked "explain the overall architecture" — read `<repo_dir>/ARCHITECTURE.md` first (the `repo_dir` comes from the query result). It's the orientation map written when the repo was indexed.

### 5. Answer with citations

Cite every claim with `file:line` form, e.g. `packages/react/src/ReactHooks.js:42-87`.

## Hard rules

- **Do not** `Glob`, `Grep`, or `Read` whole files in the indexed repo as a first move. Query first.
- **Do not** re-index the repo. If the user wants a fresh index, run vectorize-repo again.
- **Do not** answer from training-data memory. The user indexed *their* version of the code for a reason.
- If the query script errors with "No index found", run `list` (Step 1) and tell the user what's available (or that they need to vectorize first).
