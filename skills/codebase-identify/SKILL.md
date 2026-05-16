---
name: codebase-identify
description: >
  Locate a specific, known symbol in an already-indexed codebase — where a
  function, class, method, or constant is defined and which file contains it.
  Use this whenever the user wants to find a named thing: "where is X defined",
  "find the X function", "which file has X", "where's X in <repo>", or pastes an
  identifier and asks where it lives. This is the fast location lookup. If the
  user instead wants to understand how code works or how things relate, use the
  codebase-ask skill.
metadata:
  version: "1.0.1"
---

# Codebase Identify

Answer "where is X" questions about an indexed repository by returning exact
file and line ranges — fast, with no semantic model loaded.

## Scope check — do this first

This skill returns **locations** — it answers "where is X" by pointing at exact
file and line ranges. It does not explain behavior or trace relationships.

Before running, check the user's question:

- If it asks how or why something works, what calls what, what conditions cause
  something, or anything that needs reading and explaining code, tell the user:
  *"This needs relationship and behavior knowledge, not just a location — using
  codebase-ask instead."* Then invoke the `codebase-ask` skill and stop.
- Otherwise, proceed with the steps below.

## Why this skill exists

The user already knows the name of the thing — they just need to be taken to
it. Running the full semantic pipeline for that is wasted work: it loads an
embedding model and does graph expansion to answer a question that a keyword and
symbol-name match settles in about 100 ms. This skill is the cheap, direct path.

## Step 1 — Identify the repo

The user names a repo (e.g. "in `archon`, where is..."). If it is unclear which
indexed repo they mean, list what is indexed:

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" list
```
```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" list
```

If nothing is indexed, the repo must be built first with the `codebase-vectorize`
skill — say so and stop.

## Step 2 — Run the fast-lane lookup

Pass the symbol the user is looking for. Force the fast lane so it stays cheap:

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" query "<repo>" "<symbol>" --lane fast
```
```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" query "<repo>" "<symbol>" --lane fast
```

The fast lane fuses three keyword signals — exact symbol-name match, identifier
trigrams (which survive camelCase and snake_case), and BM25 — into one ranked
list. It is deterministic: the same symbol always returns the same ranking.

## Step 3 — Report the location

The command prints JSON on its last line:

```json
{
  "repo": "...", "pipeline_used": "fast",
  "results": [
    {"rank": 1, "file_absolute": "...", "file_relative": "pkg/auth.py",
     "start_line": 8, "end_line": 14, "kind": "function", "name": "authenticate_user",
     "score": 0.93, "preview": "..."}
  ]
}
```

Tell the user the file and line range of the best match (and the next one or two
if they are close and plausibly what was meant). If they want to see the code,
open the file at that range with `Read(file, offset=start_line, limit=...)` —
do not scan the rest of the repo.

If `results` is empty, the symbol is not indexed under that name. Suggest the
user check the spelling, or rephrase as a concept question for `codebase-ask`.
