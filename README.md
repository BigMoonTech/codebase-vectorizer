# codebase-vectorizer

A Claude Code plugin that turns any GitHub repo or local folder into a **local,
searchable index** of the code. You pay one slow indexing pass up front; after
that, every question Claude answers about that codebase costs a few hundred
tokens instead of tens of thousands.

---

## Why this exists

When you ask Claude a question about an unfamiliar codebase, it has to *find*
the relevant code before it can answer — and finding means reading files, often
a lot of them. On a large repo that can burn tens of thousands of tokens just to
locate the right 50 lines.

This plugin does the finding **once**. It builds an index — a single
`index.sqlite` file per repo — that already knows where everything is, how the
pieces connect, and what the code means. Afterwards, when you ask a question,
the plugin looks the answer up in that index and hands Claude the exact file and
line ranges to read. Claude opens just those, and answers.

**Who it's for:** anyone using Claude Code to work on or explore a codebase big
enough that "just read the repo" is expensive or slow — your own large project,
a dependency you need to understand, an open-source repo you're evaluating.

---

## Install

The plugin is distributed as a git repo. Install it once per machine:

```
/plugin marketplace add <git-url-of-this-repo>
/plugin install codebase-vectorizer@codebase-vectorizer-marketplace --scope user
```

You only ever type slash commands for installation. Everything after that is
plain English — the skills below trigger on their own.

**Requirements:**
- **Python 3.10–3.13** on PATH (3.12 recommended). Used only to build the
  plugin's own isolated environment — it never touches your system Python or any
  project's virtual environment.
- **`git`** on PATH (to clone GitHub URLs).
- **Internet on first use** — about 250 MB of Python packages and a ~750 MB
  embedding model, downloaded once and cached. Every run after that is offline.

---

## The four skills — split by what you're trying to do

The plugin is organized around **intent**. You don't pick a "search mode"; you
just say what you want, and the matching skill triggers. There are four.

| Skill | You want to… | Example phrasing |
|---|---|---|
| **`codebase-vectorize`** | Build the index for a repo | "index https://github.com/x/y", "vectorize this repo" |
| **`codebase-identify`** | Find *where* a known thing is | "where is `processPayment` defined in `x`" |
| **`codebase-ask`** | *Understand* something or see how things relate | "how does auth work in `x`", "who calls `save`" |
| **`codebase-architecture`** | Get an LLM-written orientation doc (optional) | "write the architecture doc for `x`" |

**`codebase-identify` vs `codebase-ask`** is the only split that needs
explaining. `identify` answers "where is it" — it returns file and line numbers,
fast, nothing more. `ask` answers everything else — how, why, what-calls-what,
what-conditions-cause — by actually reading code and walking the relationship
graph. If you invoke the wrong one, the skill notices and hands off, telling you
it's doing so ("This only needs a location — using `codebase-identify`
instead…"). You can also always invoke a skill explicitly.

`codebase-architecture` is **optional and the only skill that uses an LLM**. The
index itself is built with zero LLM involvement; `codebase-architecture` just
writes the human-readable cluster labels and `ARCHITECTURE.md` summary on
demand.

---

## The workflow

```
1. codebase-vectorize          ← build the index. ONCE per repo. (Slow: minutes.)
        │
        ├─ 2a. codebase-ask        ← ask anything, any time, any order.
        ├─ 2b. codebase-identify   ← fast "where is X" lookups.
        │
        └─ 3. codebase-architecture  ← OPTIONAL. Pretty labels + ARCHITECTURE.md.
```

`codebase-vectorize` is the only build step. It produces the **complete** index —
chunks, search indexes, the symbol graph, the flow graph, clusters, importance
scores — all of it, in one pass. `codebase-ask` and `codebase-identify` only
*read* that finished index; they never build anything, and neither has to run
before the other. It is build-once, read-many.

Re-running `codebase-vectorize` on a repo that's already indexed does an
**incremental update** — it re-processes only the files that changed.

---

## How indexing works

When `codebase-vectorize` runs, the pipeline does this:

1. **Resolve** — clone the URL (or copy the local folder) into the plugin's data
   directory.
2. **Walk & filter** — honor `.gitignore`, skip binaries and files over 1.5 MB.
3. **Chunk** — split each file into meaningful pieces using `tree-sitter` (a
   real code parser) with the cAST algorithm, so chunks align to functions,
   classes, and methods rather than arbitrary line cuts. Files in languages the
   parser doesn't support fall back to line-window chunks.
4. **Embed** — turn each chunk into an *embedding*: a 1536-number vector that
   captures its meaning, so code that does the same thing lands near code that
   means the same thing even if it's worded differently. (Model:
   `jina-code-embeddings-1.5b`.)
5. **Build the keyword index** — an FTS5 full-text index plus a custom
   identifier-trigram index that keeps `camelCase` and `snake_case` names
   intact.
6. **Build the symbol graph** — nodes for every function/class/method, edges for
   every relationship: *defines, calls, imports, inherits, references,
   contains*. This is what lets the plugin answer "who calls X" without grep.
7. **Build the flow graph** — within each function, the control-flow and
   data-flow edges (which branch leads where, which value reaches which use).
8. **Cluster** — group related chunks into concepts (see "clustering" below).
9. **Score importance** — run PageRank over the symbol graph so the most central
   code can be ranked first.
10. **Write artifacts** — `manifest.json`, and a placeholder `ARCHITECTURE.md`
    (the `codebase-architecture` skill upgrades this later).

The result is one `index.sqlite` per repo. It is portable — copy it to another
machine and it still works.

---

## How retrieval and ranking work

This is the part worth understanding, because it's where the token savings come
from.

### One question, one call, one ranked list

You ask one question. The plugin makes **one** query call. Internally that call
consults several search signals and **fuses** them into a single ranked list of
results. Each result is a file path plus a line range. The skill reads that
list, opens those exact ranges, and answers. You never pick a "mode" — the
fusion is automatic.

The output is structured data (JSON): a `results` array of
`{file, start_line, end_line, kind, name, score, preview, why_this_was_returned}`.

### Two lanes — chosen deterministically

Every query is routed to one of two lanes by **fixed rules** (no AI, no
randomness — the same query always routes the same way):

- **Fast lane** — used when the query looks like an identifier (a single
  `snake_case`/`camelCase` token, a short no-whitespace phrase, a `regex:`
  prefix). It fuses three keyword signals and returns in ~100 ms:
  - **exact symbol match** — does the query name a defined symbol?
  - **identifier trigrams** — fuzzy identifier matching that survives case styles.
  - **BM25** — classic keyword relevance scoring.

- **Full lane** — used for natural-language questions. It does everything the
  fast lane does **plus**:
  - **dense/semantic search** — embedding similarity, to find code that *means*
    what you asked even if the words differ.
  - **graph expansion** — pull in the callers, callees, and imports of the first
    hits.
  - **Personalized PageRank** — re-rank that expanded set by how central each
    piece is.
  - **cross-encoder rerank** — a model gives the finalists a final, careful
    score.

All of those signals are merged with **Reciprocal Rank Fusion** (the math that
combines several ranked lists into one). If the full lane isn't confident, it
also returns `refined_queries` — suggested rephrasings.

You can override the lane: `--lane fast|full|auto`.

### Clustering

During indexing, the **HDBSCAN** algorithm groups chunks that are close together
in meaning-space into *concept clusters* — e.g. all the auth code in one
cluster, all the logging code in another. Two uses: the full lane pulls in
chunks from the same cluster as your hits (a recall boost for thematically
related code), and `codebase-ask` can fetch a whole cluster by topic. Small
repos legitimately produce zero clusters — there isn't enough code for distinct
dense groups to exist.

### What it does and doesn't do

The index is a **locator and a map**, not a reasoner. For a question like "how
does `processPayment` handle credit cards vs e-checks", it will cheaply hand
Claude the base class, the concrete payment subclasses (via `inherits` edges),
and the call sites — so Claude reads ~4 targeted files instead of grepping 15.
But Claude still does the actual reasoning over that narrowed set. The index
does not resolve runtime polymorphism or trace cross-function dispatch — that's
an explicit non-goal.

---

## What you get vs. what you don't

**You get:**
- One portable `index.sqlite` per repo.
- Cheap, fast question-answering — Claude reads precise ranges, not whole files.
- Three retrieval signals fused per query: keyword, semantic, and graph.
- A real symbol graph (callers/callees/inheritance) and intra-procedural flow
  graph (control/data flow), queryable directly.
- Incremental updates — re-indexing after small changes is fast.

**You don't get (be aware):**
- **Instant first run.** The first `codebase-vectorize` builds a ~4 GB environment
  and downloads a model — 5–15 minutes. Amortized after that.
- **Verified retrieval accuracy.** The engine is correctness-tested (test suite
  passes), but its *answer quality* on real repos has not yet been benchmarked.
  Treat it as promising, not proven.
- **Runtime reasoning.** It locates and maps; it doesn't resolve dynamic
  dispatch.

---

## Language support

- **Chunking + embeddings + keyword search** work for **any** language
  `tree-sitter` supports (305+ grammars); unsupported files fall back to
  line-window chunks. So *search* covers essentially everything.
- **Deep symbol graph + flow graph** are implemented for: **Python, JavaScript,
  TypeScript, TSX, Go, Java, C, C++, C#, Rust, Ruby.** Other languages get
  shallow or no graph extraction — `query` still works, but `relate`/`graph`/
  `flow` will be thin for them.

---

## CLI reference

The skills wrap a CLI. You can also run it directly — the launcher
(`scripts/run.sh` on POSIX, `scripts/run.ps1` on Windows) finds Python, builds
the environment on first run, and dispatches.

```
run.sh vectorize <url|path> [flags]   Build or update an index.
        flags: --update  --no-cache  --bench  --max-file-mb N  --output-dir PATH
run.sh query <repo> "<question>" [--lane auto|fast|full] [--top-k N]
                                      Search the index; returns ranked file ranges.
run.sh relate <repo> <verb> <args>    Graph/relationship queries (verbs below).
run.sh graph <repo> <symbol> [--hops N]   Alias for `relate neighbors`.
run.sh flow <repo> <function>         Alias for `relate paths-through`.
run.sh stats <repo> [--top-k N]       Index counts, cluster labels, top nodes.
run.sh bench <repo>                   Run retrieval benchmarks (needs eval data).
run.sh list                           List every indexed repo.
run.sh info                           Print data-dir and environment paths.
run.sh llm-payload <repo>             Emit the input for codebase-architecture.
run.sh apply-llm-artifacts <repo> <result.json>
                                      Write LLM-generated labels + ARCHITECTURE.md.
```

**`relate` verbs:** `callers`, `callees`, `inheritance-chain`, `neighbors`,
`concept-cluster`, `pagerank-top`, `shortest-path`, `paths-through`,
`reaching-definitions`, `reachable-uses`, `conditions-for`.

Examples:

```bash
bash scripts/run.sh vectorize https://github.com/coleam00/Archon
bash scripts/run.sh query Archon "how does workflow dispatch work" --lane full
bash scripts/run.sh query Archon "Router" --lane fast
bash scripts/run.sh relate Archon callers dispatch
bash scripts/run.sh relate Archon conditions-for is_admin
bash scripts/run.sh stats Archon
```

```powershell
.\scripts\run.ps1 vectorize C:\src\my-repo --update
.\scripts\run.ps1 query my-repo "where is the auth token saved" --lane full
```

`llm-payload` and `apply-llm-artifacts` are normally driven by the
`codebase-architecture` skill, not run by hand.

---

## Where data lives

All plugin state lives under `${CLAUDE_PLUGIN_DATA}` (Claude Code sets this per
plugin; it survives plugin updates):

```
${CLAUDE_PLUGIN_DATA}/
├── python-env/              the plugin's isolated Python interpreter + deps
├── embedding_cache.sqlite   cross-repo embedding cache (keyed by content hash)
└── repos/
    └── <repo-name>/
        ├── source/          the cloned/copied repo
        ├── index.sqlite     the index — all layers in one file
        ├── manifest.json
        ├── ARCHITECTURE.md  placeholder until codebase-architecture runs
        └── bench/results.json
```

Run standalone (outside Claude Code) and `${CLAUDE_PLUGIN_DATA}` isn't set, so
data falls back to `~/.local/share/codebase-vectorizer/` (POSIX) or
`%LOCALAPPDATA%\codebase-vectorizer\` (Windows). Override with the
`CODEBASE_VECTORIZER_HOME` environment variable.

---

## Limitations & honest caveats

- **First run is heavy** — ~4 GB environment, model download, several minutes.
- **Retrieval quality is unverified.** `bench` exists but ships with no eval
  data, so the headline accuracy target is currently unmeasured.
- **Deep graph support is ~11 languages** (listed above); others get search-only
  coverage.
- **Clusters need a sizeable repo** — tiny repos produce none, which is correct.
- **Indexes from v0.3.0 are not auto-upgraded** — querying one returns a clean
  "legacy schema" error; re-run `codebase-vectorize` to rebuild.
- The LLM artifacts (cluster labels, `ARCHITECTURE.md`) are deterministic
  placeholders until you run `codebase-architecture`.

---

## License

MIT. See `LICENSE`.
