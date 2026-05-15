---
name: codebase-relate
description: Use codebase-vectorizer relationship queries to inspect symbol graphs, inheritance, concept clusters, PageRank, paths, and indexed flow relationships.
---

# Codebase Relate

Use this skill when a user wants graph-level relationships from an indexed
codebase-vectorizer repo. It covers symbol graph, inheritance, concept
clusters, PageRank, shortest paths, and indexed control/dataflow relationships.

Run through the launcher so the plugin venv and data home are used:

```powershell
scripts/run.ps1 relate <repo> <verb> [query] [target] [--top-k 10] [--hops 2]
scripts/run.ps1 graph <repo> <symbol> [--hops 2]
scripts/run.ps1 flow <repo> <symbol>
```

The CLI parser accepts exactly these `relate` verbs:

- `callers <symbol>`: symbols with `calls` edges into the symbol.
- `callees <symbol>`: symbols reached by outgoing `calls` edges.
- `inheritance-chain <symbol>`: ancestor classes via `inherits` edges.
- `neighbors <symbol> --hops N`: bounded symbolic graph walk.
- `concept-cluster <query>`: matching indexed clusters by label or centroid.
- `pagerank-top`: top non-block symbols by PageRank.
- `shortest-path <source> <target> --hops N`: bounded directed symbolic path.
- `paths-through <symbol>`: indexed control/dataflow paths through a symbol or block.
- `reaching-definitions <symbol>`: incoming dataflow definitions.
- `reachable-uses <symbol>`: outgoing dataflow uses.
- `conditions-for <symbol>`: guard/control predicates that affect the symbol.

`graph <repo> <symbol>` is an alias for `relate <repo> neighbors <symbol>`.
`flow <repo> <symbol>` is an alias for `relate <repo> paths-through <symbol>`.

Every command prints JSON with:

```json
{"repo": "...", "verb": "...", "query": "...", "results": [], "warnings": []}
```
