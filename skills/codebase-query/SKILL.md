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
  version: "1.0.0"
---

# Codebase Query

Answer codebase questions token-efficiently by querying the local v1.0 index
(SQLite + FTS5 + `sqlite-vec` + symbol/flow graph metadata), then reading only
the specific file ranges the query returns. **Never scan the indexed repo with
Glob/Grep/Read on full files unless the query tool comes back empty.** That
defeats the entire purpose of this plugin.

Indexes live in `${CLAUDE_PLUGIN_DATA}/repos/` — the same location regardless
of where the user runs `claude`. Vectorize once, query from anywhere.

## When this skill fires

For any question that's clearly about an indexed codebase. Examples:

- "In react, how does useState work?"
- "Find the rate limiter in the express repo I indexed."
- "Where is `parseConfig` defined?"
- "What does the auth middleware do?"
- "Explain the build pipeline."

If the user names a repo, use that. If they don't, list what's available
(Step 1) and ask which — unless there is exactly one indexed repo, in which
case use it.

## Workflow

### 1. List available indexed repos

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" list
```

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" list
```

Each line prints `<name>\tschema=<version>\t<path>`. If the output is empty,
suggest running the `vectorize-repo` skill. If `schema=legacy` appears for the
target repo, tell the user the index needs re-vectorizing for v1.0.

### 2. Run the query tool

Pass the user's question verbatim — do not paraphrase.

**On POSIX:**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" query <repo_name> "<exact user question>" --top-k 6 --lane auto
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" query <repo_name> "<exact user question>" --top-k 6 --lane auto
```

`--lane auto` routes identifier-style lookups to the fast lane and
natural-language questions to the full lane. Use `--lane fast` when the user is
clearly asking for an exact symbol/identifier lookup. Use `--lane full` when
they need semantic retrieval, graph expansion, Personalized PageRank, rerank,
or query refinement even for a terse query.

The script prints v1.0-shape JSON to stdout (last line):

```json
{
  "repo": "react",
  "query": "how does useState work",
  "repo_dir": "/abs/path/to/repos/react",
  "pipeline_used": "full",
  "results": [
    {
      "rank": 1,
      "file_absolute": "/abs/path/.../ReactHooks.js",
      "file_relative": "packages/react/src/ReactHooks.js",
      "start_line": 42,
      "end_line": 87,
      "kind": "window",
      "name": null,
      "score": 0.0316,
      "preview": "first ~200 chars of the chunk…",
      "why_this_was_returned": "bm25+dense"
    }
  ],
  "refined_queries": [],
  "expansion_size": 0,
  "reranker_model": "..."
}
```

The routing fields always follow this shape:

```json
{
  "pipeline_used": "fast|full",
  "refined_queries": [],
  "expansion_size": 0,
  "reranker_model": "..."
}
```

`pipeline_used` reports the actual lane after `auto` routing, so it is either
`"fast"` or `"full"`. Fast-lane responses use symbol exact matches, identifier
trigrams, and BM25, with `expansion_size: 0`, no reranker model, and no refined
queries. Full-lane responses add dense retrieval, graph expansion, Personalized
PageRank, cross-encoder reranking, `reranker_model`, and low-confidence
`refined_queries` hints when applicable.

### 3. Read only the returned ranges

For each result, use the Read tool with `offset` and `limit` so you load only
those lines, not the whole file. To read lines 42–87:

```
Read(file_path="/abs/path/.../ReactHooks.js", offset=42, limit=46)
```

Read at most 3–5 chunks unless the question clearly demands more. If the
chunks reference other symbols you need to understand, run another `query`
call rather than opening more files blindly.

### 4. Answer with citations

Cite every claim with `file:line` form, e.g.
`packages/react/src/ReactHooks.js:42-87`.

## Hard rules

- **Do not** `Glob`, `Grep`, or `Read` whole files in the indexed repo as a
  first move. Query first.
- **Do not** re-index the repo for a normal question. If the user wants a fresh
  or incremental index, run `vectorize-repo` again with plain `vectorize` or
  `vectorize --update`.
- **Do not** answer from training-data memory.
- If the query script errors with "No index found", run `list` (Step 1) and
  tell the user what's available.
- If the query script errors with "older codebase-vectorizer index", tell the
  user the index is from an earlier version and needs re-vectorizing.
