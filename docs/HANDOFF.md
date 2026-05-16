# codebase-vectorizer — Handoff

_Last rewritten: 2026-05-16. This replaces the earlier task-by-task Codex build
log; that history lives in git._

---

## 1. Where things stand

- **Branch:** `dev`. Two commits ahead of `origin/dev` (push when ready):
  - `c2e591c` — reshape skill surface by intent, make LLM use optional
  - `62c04b0` — rename skills to a consistent `codebase-*` family
- `main` is preserved.
- **Version:** v1.0 — `.claude-plugin/plugin.json` is `1.0.0`.
- **Tests:** full suite `466 passed, 1 skipped` (run with the throwaway
  `.testvenv/` described in §6).
- **Status:** code-complete and test-green, **but never run as an installed
  plugin and never run with the real embedding model.** The next step is the
  live test in §4.

---

## 2. What this is

A Claude Code plugin that indexes a repo into a local `index.sqlite`, so Claude
answers questions about that codebase from precise file ranges (a few hundred
tokens) instead of re-reading files (tens of thousands). The substance is the
`cbv` Python engine (~40 modules); the four skills are a thin, intelligent
routing layer over its CLI.

The four skills, split by intent:

| Skill | Intent | CLI it drives |
|---|---|---|
| `codebase-vectorize` | build the index | `vectorize` |
| `codebase-identify` | locate a known symbol | `query --lane fast` |
| `codebase-ask` | understand / relate code | `query --lane full`, `relate`, `graph`, `flow` |
| `codebase-architecture` | optional LLM orientation doc | `llm-payload`, `apply-llm-artifacts` |

---

## 3. What was built

### 3a. The engine (prior work, by an automated agent across three plans)

A four-layer index in one SQLite file per repo:

- **Lexical** — FTS5 BM25 + a custom identifier-trigram index.
- **Dense** — `jina-code-embeddings-1.5b` vectors in `sqlite-vec`.
- **Graph** — a symbol graph (defines/calls/imports/inherits/references/
  contains) and an intra-procedural flow graph (control/data flow), plus global
  PageRank.
- **Clusters** — UMAP + HDBSCAN concept clusters.

Retrieval is one query with two deterministic lanes (fast = keyword/identifier;
full = adds dense + graph expansion + Personalized PageRank + cross-encoder
rerank), fused with Reciprocal Rank Fusion. Incremental re-indexing via a Merkle
tree. See `specs/2026-05-14-codebase-vectorizer-v1.0-design.md` for the full
design (note: that spec predates the skill rename in §3b — it still says
`codebase-query`/`codebase-relate`).

### 3b. This arc's changes (the skill refactor)

Plan: `docs/plans/2026-05-16-intent-shaped-skill-surface.md`.

- **Skill surface reshaped by intent.** Replaced the mechanism-split
  `codebase-query` / `codebase-relate` skills with the four intent-shaped skills
  in §2. The two ask-side skills carry mirrored scope checks that hand off to
  each other when a question fits the other better.
- **LLM use quarantined and made optional.** The indexer (`vectorize`) never
  invokes an LLM — it writes deterministic placeholder cluster labels and a
  placeholder `ARCHITECTURE.md`. The new `codebase-architecture` skill is the
  only LLM-using path; the in-session agent generates the real artifacts via the
  new `llm-payload` / `apply-llm-artifacts` CLI verbs. The earlier auto-wiring
  ("Path A": `llm_invoke.py`, `bootstrap.default_llm_env`) was removed.
- **UTF-8 fix.** Configured-command subprocess boundaries now force UTF-8 so
  non-ASCII output survives on Windows as well as Linux/WSL2.
- **Docs/release.** README rewritten as a full plain-language guide;
  `plugin.json` bumped to `1.0.0`.

---

## 4. Next step (priority): the live install test

Nobody has run this as an installed plugin or with the real model. This test is
the gate between "passes its tests" and "actually works." Run the stages in
order; each has an explicit success signal. Stop and record the symptom if a
stage fails — a later stage cannot vindicate an earlier failure.

**Pick a test repo deliberately.** Use a repo **you know well** (so you can
judge whether answers are correct) that is **mid-size** — roughly 100–400 source
files. Too tiny and no concept clusters form (HDBSCAN needs density); too huge
and indexing drags. A repo in a deeply-supported language (Python, JS/TS, Go,
Java, C/C++, C#, Rust, Ruby) exercises the symbol and flow graphs.

### Stage 0 — Install
`/plugin marketplace add <repo-url-or-path>` then `/plugin install
codebase-vectorizer@codebase-vectorizer-marketplace --scope user`.
**Success:** all four skills (`codebase-vectorize`, `codebase-identify`,
`codebase-ask`, `codebase-architecture`) appear in the available-skills list.

### Stage 1 — Bootstrap the environment
Trigger the first index ("index <repo>"). `bootstrap.py` finds Python 3.10–3.13,
builds the venv at `${CLAUDE_PLUGIN_DATA}/python-env/`, and pip-installs deps
(`torch`, `sqlite-vec`, `tree-sitter-language-pack`, `umap-learn`, `hdbscan`, …).
This is ~4 GB and several minutes.
**Success:** the venv builds and all deps install with no wheel failures;
`run.sh info` / `run.ps1 info` reports `python_env_ready: True`.
**Watch for:** the Python-version trap — the bootstrap must select 3.10–3.13,
not 3.14. `torch` / `llama-cpp-python` wheels must exist for the chosen Python.

### Stage 2 — Model download
The first embedding step downloads the `jina-code-embeddings-1.5b` GGUF
(~750 MB) into the HuggingFace cache.
**Success:** download completes and the model loads.
**Watch for:** the default `CBV_GGUF_REPO` / `CBV_GGUF_FILE` may not resolve to
a real artifact — this is a known risk. If the download fails, that is a finding;
the fix is to set those env vars to a known-good community quant.

### Stage 3 — Index the repo ("vectorize" — build, map, classify)
Let `codebase-vectorize` index the chosen repo. Read the JSON summary on the
last line.
**Success:**
- `files_indexed`, `chunks_indexed` — nonzero and plausible for the repo size.
- `nodes_symbol`, `edges_symbol` — nonzero → the **symbol graph** ("map") built.
- `nodes_block`, `edges_flow` — nonzero → the **flow graph** built.
- `clusters_indexed` — **nonzero** on a mid-size repo → **clustering**
  ("classify") worked. Zero is only acceptable on a small repo.
- `llm_artifacts_pending: true` — expected (LLM artifacts are placeholders).
- `warnings` — read every one. A few "unsupported file, used fallback" warnings
  are normal; symbol-extraction or flow failures on a mainstream language are
  not.

### Stage 4 — Inspect the index
Run `stats <repo>` and `list`.
**Success:** counts match the Stage 3 summary; the top-PageRank nodes are
genuinely central code (entry points, core classes) — not noise.

### Stage 5 — `codebase-identify` (location lookup)
Ask "where is `<symbol>` defined in `<repo>`" for a symbol **whose location you
already know**.
**Success:** the top result is the actual definition site, correct file and
line range. The skill should route here without you naming it.

### Stage 6 — `codebase-ask` (the real test: retrieval quality)
Ask 5–10 real questions you know the answers to — a mix of:
- behavior ("how does X work"),
- relationships ("who calls X", "what does X inherit"),
- a concept question ("what handles <concern>").
**Success — this is the bar that matters:**
- The returned file ranges actually contain the relevant code.
- Relationship answers are correct (the callers/inheritance lists are right).
- Claude can answer well from **only** the returned ranges, without grepping
  further — that is the token-savings proof. Note the rough token cost per
  question; it should be hundreds-to-low-thousands, not tens of thousands.
- The graph catches relationships keyword search would miss (e.g. polymorphic
  implementations via `inherits` edges).
**Red flags:** irrelevant files returned; empty graph results for a
deeply-supported language; Claude still has to grep the repo to answer.

### Stage 7 — `codebase-architecture` (optional LLM pass)
Run it on the indexed repo.
**Success:** cluster labels become real phrases ("auth & session"), not
`cluster_3`; `ARCHITECTURE.md` is a real prose document with all seven sections
(Overview, Languages, Entry points, Module map, Key abstractions, Concept
clusters, How to query), grounded in the actual repo.

### Stage 8 — Incremental update
Change one file, re-run `codebase-vectorize` on the same repo.
**Success:** only the changed file is reprocessed, the run is fast, and the
counts update correctly.

### Stage 9 — Cross-platform
The target platforms are Linux, WSL2, and Windows. Verify on Windows first
(current machine); repeat Stages 0–7 on WSL2 and a Linux host as follow-up.

**Overall success:** the plugin installs, builds its environment, indexes a real
repo with all four layers populated, and answers real questions **accurately
from narrow context, more cheaply than vanilla Claude would**. If retrieval
quality is poor, that is the single most important thing to learn — it is
currently unknown.

---

## 5. Next step: curate benchmark data

`bench` measures retrieval *accuracy* with file-level MRR@10, NDCG@10, Recall@5,
Recall@10. The machinery works but **ships with no data**, so it currently
returns zeros and the spec's accuracy goal is unverified.

`bench` looks for query files at (first found wins, all are read):
`./bench/coir_subset.jsonl`, `./bench/repoeval_mini.jsonl`, the project-root
`bench/` equivalents, `<repo_dir>/source/bench/queries.jsonl`, and
`<repo_dir>/bench/queries.jsonl`.

**Schema** — JSONL, one JSON object per line:

```json
{"query": "how does the router dispatch requests", "expected_files": ["pkg/router.py"]}
{"query": "where are sessions validated", "expected_files": ["pkg/auth.py", "pkg/session.py"]}
```

- `query` — a non-empty string; run through the **full lane**.
- `expected_files` — a list of **repo-relative** paths (matching the
  `file_relative` field in query output) that *should* be retrieved.

`bench` runs each query, takes the retrieved files, and scores them against
`expected_files`. It is **file-level** — it grades which files came back, not
line ranges.

**How to produce a set:** the easiest path is to hand-curate one for a repo you
know — pick the repo, write 30–50 questions a real user would ask, and for each
record the file(s) that genuinely answer it. Drop the result at
`<repo_dir>/bench/queries.jsonl` and run `bench <repo>`. Alternatively, derive
`coir_subset.jsonl` / `repoeval_mini.jsonl` from the published CoIR and RepoEval
datasets (then you index their corpora, not your own). The work is the curation,
not the format.

---

## 6. Practical notes

- **Data location:** `${CLAUDE_PLUGIN_DATA}/` (set by Claude Code), or
  `CODEBASE_VECTORIZER_HOME`, or the platform default
  (`~/.local/share/codebase-vectorizer/` POSIX, `%LOCALAPPDATA%\codebase-vectorizer\`
  Windows). The venv is `python-env/`; per-repo data is under `repos/<name>/`.
- **Reset:** delete `python-env/` to rebuild the environment; delete
  `repos/<name>/` to drop one index.
- **`.testvenv/` in the repo root** is a throwaway, git-ignored virtual
  environment used to run `pytest` without the full ~4 GB plugin bootstrap. It
  is not part of the plugin — ignore or delete it.
- Run the suite: `.testvenv/Scripts/python.exe -m pytest -q` (Windows) or the
  equivalent.

---

## 7. Known loose ends

- **Retrieval quality is unverified** — see §4, Stage 6. Highest-value unknown.
- **No benchmark data** — see §5.
- **Deep symbol/flow support is ~11 languages** (Python, JS, TS, TSX, Go, Java,
  C, C++, C#, Rust, Ruby); the spec aspired to ~40. Other languages get
  search-only coverage. Either close the gap or revise the spec's claim.
- **The spec and this doc's §3a** still reference the old `codebase-query` /
  `codebase-relate` skill names. The spec is a dated design record; it was left
  intact rather than rewritten to match later decisions.
- **`bench` auto-run** — the spec says a first-time index should auto-run
  `bench`; currently it runs only with `--bench`. Minor.
