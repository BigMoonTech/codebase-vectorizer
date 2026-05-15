---
name: codebase-relate
description: Use codebase-vectorizer relationship queries to inspect symbol graphs, inheritance, concept clusters, PageRank, paths, and flow fallbacks.
---

# Codebase Relate

Use this skill when a user wants graph-level relationships from an indexed codebase-vectorizer repo.

Run through the launcher so the plugin venv and data home are used:

```powershell
scripts/run.ps1 relate <repo> <verb> [query] [target] [--top-k 10] [--hops 2]
scripts/run.ps1 graph <repo> <symbol> [--hops 2]
scripts/run.ps1 flow <repo> <symbol>
```

Supported `relate` verbs:

- `callers <symbol>`: symbols with `calls` edges into the symbol.
- `callees <symbol>`: symbols reached by outgoing `calls` edges.
- `inheritance-chain <symbol>`: ancestor classes via `inherits` edges.
- `neighbors <symbol> --hops N`: bounded symbolic graph walk.
- `concept-cluster <query>`: matching indexed clusters; returns a clean `clusters not indexed` warning before clusters exist.
- `pagerank-top`: top non-block symbols by PageRank.
- `shortest-path <source> <target> --hops N`: bounded directed symbolic path.
- `paths-through <symbol>`: flow path lookup; returns a clean `flow not indexed` warning before flow exists.
- `reaching-definitions <symbol>`: incoming dataflow best effort.
- `reachable-uses <symbol>`: outgoing dataflow best effort.
- `conditions-for <symbol>`: incoming guard/control best effort.

Every command prints JSON with:

```json
{"repo": "...", "verb": "...", "query": "...", "results": [], "warnings": []}
```
