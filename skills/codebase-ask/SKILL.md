---
name: codebase-ask
description: >
  Answer any understanding or relationship question about an already-indexed
  codebase — how something works, what a function does, who calls what, what
  conditions trigger a behavior, which module is responsible for something, or
  how a flow runs. Use this whenever the user asks about an indexed repo with
  "how does X work", "what does X do", "who calls X", "what conditions cause Y",
  "what handles Z", "explain the X flow", or any question that needs reading or
  relating code. This is the main way to question an indexed codebase. If the
  user only wants the location of a known symbol, use the codebase-identify
  skill instead.
metadata:
  version: "1.1.0"
---

# Codebase Ask

Answer real questions about an indexed repository by querying the index — the
semantic search, the symbol graph, and the flow graph that `codebase-vectorize`
already built — instead of re-reading the whole codebase.

## Scope check — do this first

This skill answers **understanding and relationship questions** — how code
works, what calls what, what a module is responsible for. It reads code and
traverses the graph to do that.

Before running, check the user's question:

- If it only asks for the location of a known symbol — no explanation, no
  relationships, just "where is it", tell the user: *"This only needs a
  location — using codebase-identify instead, which is faster and skips semantic
  retrieval."* Then invoke the `codebase-identify` skill and stop.
- Otherwise, proceed with the steps below.

## How this skill works

The index is already built. It holds the embeddings, the symbol graph (who
defines/calls/imports/inherits what), and the intra-procedural flow graph
(control and data flow inside functions). Your job is to pick the `cbv` verb
that fits the question, run it, and answer from the file ranges it returns.

The verbs are deterministic — routing by query string is rule-based, and the
graph verbs are plain database lookups. The one judgment call is yours: choosing
the verb. Use this table.

## Step 1 — Identify the repo

The user names the repo. If unclear, run `list` (see `codebase-identify` for the
exact launcher line). If nothing is indexed, the repo must be built first with
`codebase-vectorize` — say so and stop.

## Step 2 — Pick the verb for the question

| What the user is asking | Verb to run |
|---|---|
| "how does X work", "what does X do", "what handles Z", any concept/behavior question | `query "<repo>" "<question>" --lane full` |
| "who calls X", "what calls X" | `relate "<repo>" callers <symbol>` |
| "what does X call" | `relate "<repo>" callees <symbol>` |
| "what does X inherit / extend / implement" | `relate "<repo>" inheritance-chain <symbol>` |
| "what is related to X", "neighbors of X" | `relate "<repo>" neighbors <symbol>` |
| "what conditions cause Y", "when does Y happen" | `relate "<repo>" conditions-for <symbol>` |
| "what paths run through function X" | `relate "<repo>" paths-through <function>` |
| "where does this value flow / what reaches X" | `relate "<repo>" reaching-definitions <symbol>` or `reachable-uses <symbol>` |
| "what is the X cluster / concept", "show the auth-related code" | `relate "<repo>" concept-cluster "<topic>"` |
| "what is the most central / important code" | `relate "<repo>" pagerank-top` |

`query` accepts free-text questions. The `relate` verbs need an **exact symbol
name**. If the user gave a fuzzy or partial name, run `query --lane full` first
to find the exact symbol, then run the `relate` verb on it.

## Step 3 — Run it

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" query "<repo>" "<question>" --lane full
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" relate "<repo>" callers "<symbol>"
```
```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" query "<repo>" "<question>" --lane full
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" relate "<repo>" callers "<symbol>"
```

The full lane fuses keyword (BM25), semantic (dense vector), and exact-symbol
hits, expands along the symbol graph, ranks with Personalized PageRank, and
reranks the finalists — all into one ranked list. `relate` walks the graph
directly. Both print JSON on the last line: a `results` array of
`{file_relative, start_line, end_line, kind, name, score, ...}` entries, and the
full lane also returns `refined_queries` hints when its confidence is low.

## Step 4 — Answer from the results

The index did the **finding**; you do the **understanding**. Read the returned
file ranges with `Read(file, offset=start_line, limit=...)` — only those — and
answer the user grounded in what you read.

Be aware of the boundary: the index locates and maps code (including
inheritance and call edges, which is how it surfaces polymorphic
implementations), but it does not resolve runtime dispatch. For a question like
"how does `processPayment` handle credit cards vs e-checks", expect the index to
hand you the base class, the concrete subclasses, and the call sites cheaply —
then you trace the actual dispatch yourself across that narrowed set.

If the full lane returned `refined_queries`, its confidence was low; consider
re-running with one of those phrasings before answering, or tell the user the
result is uncertain.
