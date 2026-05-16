---
name: codebase-architecture
description: >
  Generate the LLM-written orientation artifacts for an already-indexed
  codebase — real concept-cluster labels and a prose ARCHITECTURE.md map — to
  replace the deterministic placeholders that codebase-vectorize writes. Use this
  when the user asks to "write the architecture doc for <repo>", "generate
  ARCHITECTURE.md", "label the concept clusters", "give me an orientation map
  of <repo>", or wants a readable high-level summary of an indexed codebase.
  This is the only skill that uses an LLM, and it is optional — codebase-vectorize,
  codebase-ask, and codebase-identify all work fully without it.
metadata:
  version: "1.0.1"
---

# Codebase Architecture

Write the human-readable orientation artifacts for an indexed repository: a
short label and summary for each concept cluster, and an `ARCHITECTURE.md`
orientation map.

## Why this is its own skill

Indexing (`codebase-vectorize`) is pure computation — chunking, embeddings, the
symbol and flow graphs, clustering, PageRank — and needs no LLM. Only two
artifacts are prose: the **concept-cluster labels** and **`ARCHITECTURE.md`**.
`vectorize` writes deterministic placeholders for both (labels like
`cluster_3`, a thin metadata `ARCHITECTURE.md`) so the index is always usable.

This skill is the explicit, optional step that upgrades those placeholders to
real LLM-written prose. **You are the LLM** — there is no external service and
no configuration. You read the index's own data and write the artifacts back.

## Step 1 — Identify the repo

The user names the repo. If unclear, run `list`:

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" list
```
```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" list
```

If the repo is not indexed, it must be built first with `codebase-vectorize` —
say so and stop.

## Step 2 — Get the payload

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" llm-payload "<repo>"
```
```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" llm-payload "<repo>"
```

It prints JSON:

```json
{
  "repo": "...",
  "architecture_path": ".../ARCHITECTURE.md",
  "clusters": [{"id": 3, "samples": ["<code chunk>", "..."]}],
  "architecture": {
    "repo_name": "...", "counts": {...}, "languages": [...],
    "top_nodes": [...], "cluster_summaries": [...], "pivotal_files": [...]
  }
}
```

If `clusters` is an empty list, this repo formed no concept clusters (common for
small repos) — there is nothing to label, so do only the architecture document.

## Step 3 — Write the artifacts

**Cluster labels.** For each cluster, read its `samples` (the code chunks an
unsupervised algorithm grouped together) and decide:
- a `label` — three words, e.g. "auth & session"
- a `summary` — one sentence describing what the chunks have in common

**`ARCHITECTURE.md`.** From the `architecture` metadata, write a GitHub-flavored
markdown document, at most ~1500 words, with these sections in order: Overview,
Languages, Entry points, Module map, Key abstractions, Concept clusters, How to
query. Ground every statement in the provided data (counts, `top_nodes`,
`pivotal_files`, your cluster labels) — do not invent.

## Step 4 — Apply the artifacts

Write a result JSON file to a temporary path:

```json
{
  "clusters": [{"id": 3, "label": "auth & session", "summary": "..."}],
  "architecture_markdown": "# <repo> Architecture\n\n## Overview\n\n..."
}
```

Then apply it:

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" apply-llm-artifacts "<repo>" "<result-file>"
```
```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" apply-llm-artifacts "<repo>" "<result-file>"
```

This writes the labels into the index and `ARCHITECTURE.md` to disk, and prints
`{"clusters_updated": N, "architecture_written": true}`.

## Step 5 — Report

Tell the user the cluster labels and `ARCHITECTURE.md` are finalized, and where
`ARCHITECTURE.md` lives (the `architecture_path` from Step 2). The labels also
make `relate concept-cluster "<topic>"` searchable by topic word in
`codebase-ask`.
