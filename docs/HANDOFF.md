# codebase-vectorizer — Handoff

_Last updated: 2026-05-16, after the first live install surfaced and fixed four
Windows blockers (§3c). This replaces the earlier task-by-task Codex build log;
that history lives in git._

---

## 1. Where things stand

- **Branch:** `dev`. One commit ahead of `origin/dev` (push when ready):
  - `a070866` — fix four Windows install/index blockers; make GPU the default
- Earlier on `dev`, already pushed: `2f911b4` (HANDOFF rewrite), `62c04b0`
  (skill rename), `c2e591c` (intent-shaped skill surface).
- `main` is preserved.
- **Version:** v1.0.1 — `.claude-plugin/plugin.json` is `1.0.1`.
- **Tests:** full suite `481 passed, 1 skipped` (run with the throwaway
  `.testvenv/` described in §6).
- **Status:** the plugin installs and the engine works — it was installed from
  the marketplace and indexed a real repo (Archon: 853 files, ~11.4k chunks,
  symbol + flow graphs, 360 clusters). But that first run only succeeded after
  an agent hand-patched four Windows blockers mid-run. `a070866` fixes all four
  at the source. A **clean** install + index run, with no manual patching, has
  not yet been done — that is the next step (§4).

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

### 3c. The Windows install-robustness fix

Commit `a070866`; diagnosed by in-session systematic debugging of the first
live install (a mid-size repo, Archon, on Windows with an NVIDIA GPU). That run
surfaced four distinct blockers, each now fixed at the root:

- **`llama-cpp-python` had no Windows wheel** → bootstrap fell back to a source
  build and died with no C/C++ compiler. It is only the *CPU-fallback* embedder
  backend, yet was a hard `requirements.txt` entry that took the whole install
  down.
- **The default GGUF filename did not exist** (`...1.5b.Q4_K_M.gguf` — wrong
  quant tag, dot instead of dash) → the CPU embedder 404'd on model download.
- **Bare `torch` from PyPI is CPU-only on Windows** → `torch.cuda.is_available()`
  was always False even on an NVIDIA GPU, so the fast GPU path was never taken.
- **`shutil.rmtree` cannot delete git's read-only pack files on Windows** →
  `source/` cleanup crashed with `PermissionError` on re-index.

Fixes: a new `cbv.fsutil.force_rmtree` (clears the read-only bit and retries;
used at both cleanup sites); the GGUF default corrected to
`jina-code-embeddings-1.5b-IQ4_XS.gguf` (a real 4-bit quant); and a **GPU-aware
bootstrap** — `detect_gpu()` probes `nvidia-smi`, then `torch` is installed from
the CUDA wheel index when a GPU is present (CPU index otherwise) and
`llama-cpp-python` is installed only on the CPU stack from a prebuilt-wheel
index. No source build is ever attempted; GPU is the default path and CPU is a
genuine fallback. `torch` and `llama-cpp-python` were removed from
`requirements.txt` (bootstrap owns them). Overrides: `CBV_FORCE_CPU`,
`CBV_TORCH_INDEX_URL`, `CBV_LLAMA_INDEX_URL`.

---

## 4. Next step (priority): the clean live install test

The plugin has been installed and run once — but only with an agent hand-fixing
the four blockers in §3c mid-run. `a070866` fixes them at the source, so the job
now is a **clean** run from a fresh environment with no manual patching. This is
the gate between "passes its tests" and "actually works." Run the stages in
order; each has an explicit success signal. Stop and record the symptom if a
stage fails — a later stage cannot vindicate an earlier failure.

**Start clean.** The existing venv at `<data_home>/python-env/` was hand-patched
during the first run, so `deps_installed()` would short-circuit the new
GPU-aware bootstrap and never exercise the fix. **Delete `python-env/` before
re-testing** so the bootstrap rebuilds from scratch.

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
builds the venv at `${CLAUDE_PLUGIN_DATA}/python-env/`, then installs deps from
prebuilt wheels in steps: `torch` from a CUDA or CPU wheel index depending on
whether `nvidia-smi` is found, the core requirements, and — CPU stack only —
`llama-cpp-python` from a prebuilt-wheel index. No source build is attempted.
This is ~4 GB and several minutes.
**Success:** the venv builds and all deps install with no wheel failures;
`run.ps1 info` / `run.sh info` reports `python_env_ready: True` and a
`gpu_detected:` line matching the machine (True on an NVIDIA box).
**Watch for:** the Python-version trap — the bootstrap needs a 3.10–3.13
interpreter on PATH, not 3.14. If GPU detection is wrong, override with
`CBV_FORCE_CPU=1`, or point `CBV_TORCH_INDEX_URL` at the right CUDA series.

### Stage 2 — Model download
The first embedding step downloads the model into the HuggingFace cache; which
artifact depends on the path taken. The **GPU path** pulls the full
`jina-code-embeddings-1.5b` model (~3 GB) and runs it in FP16. The **CPU path**
pulls a quantized GGUF — the default is now `jina-code-embeddings-1.5b-IQ4_XS`
(~896 MB), a 4-bit quant that exists in the repo (the old `Q4_K_M` default
404'd; fixed in `a070866`).
**Success:** the download completes and the model loads on the expected device.
**Watch for:** on a non-NVIDIA machine, confirm it cleanly took the CPU/GGUF
path. `CBV_GGUF_FILE` overrides the quant (e.g. `-Q8_0` for best quality).

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
- **GPU vs CPU:** the bootstrap auto-detects an NVIDIA GPU via `nvidia-smi` and
  installs the CUDA `torch` build; otherwise it installs CPU `torch` plus the
  `llama-cpp-python` GGUF backend. Force CPU with `CBV_FORCE_CPU=1`; override
  the wheel indexes with `CBV_TORCH_INDEX_URL` / `CBV_LLAMA_INDEX_URL`.
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
