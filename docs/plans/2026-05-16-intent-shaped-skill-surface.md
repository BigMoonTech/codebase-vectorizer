# Intent-Shaped Skill Surface Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan in-session. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the plugin's skill surface so it is split by *user intent* (build / locate / understand / document) instead of by retrieval mechanism, and quarantine all LLM use into one optional skill.

**Architecture:** The `cbv` Python engine and all CLI verbs (`vectorize`, `query`, `relate`, `graph`, `flow`, `stats`, `bench`, `llm-payload`, `apply-llm-artifacts`) are unchanged — they are already correct and tested. Only the skill layer (`skills/`) and the auto-LLM wiring change. The previous "Path A" (auto-wire the `claude` CLI during `vectorize`) is removed entirely; LLM-written artifacts become an explicit, optional `architecture-codebase` skill driven by the in-session agent via the existing `llm-payload` / `apply-llm-artifacts` commands.

**Tech Stack:** Claude Code skills (SKILL.md + YAML front-matter), the existing `cbv` Python package, pytest.

---

## Background — why this change

The plugin shipped three skills split by *mechanism*: `codebase-query` (semantic search) and `codebase-relate` (graph traversal). Users do not think in "is this a structural or semantic question" — they have a question. The surface must split by intent. Final intent split:

- **build** the index — `vectorize-repo`
- **locate** a known thing — `codebase-identify` (fast lane)
- **understand / relate** something — `codebase-ask` (full lane + relate/graph/flow verbs)
- **document** with LLM prose — `architecture-codebase` (optional, the only LLM skill)

LLM use is fully optional: `vectorize`, `query`, `relate`, `graph`, `flow`, `stats` need no LLM. The LLM touches only two cosmetic artifacts — concept-cluster *labels* and `ARCHITECTURE.md`. Those are produced on demand by `architecture-codebase`.

## Decisions locked

- **Keep** `vectorize-repo` as the skill name (user prefers current naming). The `codebase-*` family is slightly inconsistent with it; accepted.
- **Keep** the `CBV_*_COMMAND` hook and `LocalLLMClusterLabeler` / `LocalLLMArchitectureWriter` classes in `clusters.py` / `architecture.py`. With no auto-wiring they simply fall back to deterministic placeholders during `vectorize`, which is the desired default. They remain a dormant advanced escape hatch. The UTF-8 encoding fix on those subprocess calls stays (still correct).
- **Remove** Path A only: `scripts/cbv/llm_invoke.py` and `bootstrap.default_llm_env`.
- **Keep** `llm-payload` and `apply-llm-artifacts` CLI verbs — they are the `architecture-codebase` skill's backend.
- **Keep** the `llm_artifacts_pending` field in the `vectorize` summary — with no auto-LLM it now reliably signals "LLM artifacts are still deterministic placeholders."

---

## File Structure After This Plan

```
scripts/
├── bootstrap.py                  MODIFIED: remove default_llm_env + shutil import + its call
└── cbv/
    └── llm_invoke.py             DELETED (Path A bridge)

skills/
├── vectorize-repo/SKILL.md       MODIFIED: drop "Step 3", point to architecture-codebase
├── codebase-query/               DELETED
├── codebase-relate/              DELETED
├── codebase-identify/SKILL.md    NEW: location lookups (fast lane)
├── codebase-ask/SKILL.md         NEW: understanding + relationship questions
└── architecture-codebase/SKILL.md NEW: optional LLM artifact generation

tests/unit/
├── test_llm_invoke.py            DELETED
└── test_bootstrap_dispatch.py    MODIFIED: drop default_llm_env tests

README.md                         REWRITTEN: full plain-language guide
.claude-plugin/plugin.json        MODIFIED: version 0.3.0 -> 1.0.0
```

Unchanged and verified: `cbv/commands/llm_payload.py`, `cbv/commands/apply_llm.py`, `cbv/architecture.py`, `cbv/clusters.py`, `cbv/cli.py`, all retrieval/graph/flow code, all other tests.

---

## Chunk 1: Remove Path A (auto-LLM wiring)

### Task 1: Delete the Path-A bridge and auto-wiring

**Files:**
- Delete: `scripts/cbv/llm_invoke.py`
- Delete: `tests/unit/test_llm_invoke.py`
- Modify: `scripts/bootstrap.py` (remove `import shutil`, `default_llm_env`, and the `child_env.update(...)` call)
- Modify: `tests/unit/test_bootstrap_dispatch.py` (remove the four `default_llm_env` tests; keep the llm-verb allowlist/parse tests)

- [ ] **Step 1: Delete `scripts/cbv/llm_invoke.py` and `tests/unit/test_llm_invoke.py`.**
- [ ] **Step 2: In `bootstrap.py`** — remove `import shutil`; delete the `default_llm_env` function; restore `main()` to `child_env = {**os.environ, "PYTHONPATH": str(SCRIPT_DIR)}` with no `default_llm_env` call. Keep `llm-payload`/`apply-llm-artifacts` in `ALLOWED_SUBCOMMANDS` and `usage()`.
- [ ] **Step 3: In `test_bootstrap_dispatch.py`** — delete `test_default_llm_env_empty_without_claude`, `test_default_llm_env_wires_both_commands_when_claude_present`, `test_default_llm_env_respects_user_command_override`. Keep `test_bootstrap_allowlist_includes_llm_verbs`, `test_cli_parses_llm_payload_args`, `test_cli_parses_apply_llm_artifacts_args`.
- [ ] **Step 4: Run** `pytest tests/unit/test_bootstrap_dispatch.py -q`. Expected: PASS, no `default_llm_env` references remain.
- [ ] **Step 5: Run the full suite** `pytest -q`. Expected: all green (count drops by the deleted tests).

---

## Chunk 2: Intent-shaped skills

### Task 2: Remove the mechanism-split skills

- [ ] **Step 1: Delete** `skills/codebase-query/` and `skills/codebase-relate/`.

### Task 3: `codebase-identify` — location lookups

**Files:** Create `skills/codebase-identify/SKILL.md`.

Front-matter `name: codebase-identify`. Description must be triggering-focused and slightly pushy, covering "where is X / find X / which file defines X". Body must open with a **Scope check** section that is a structural mirror of `codebase-ask`'s (same heading, same "do this first", same "If [other type] -> announce + invoke other skill + stop. Otherwise proceed."). Body then: what it does (`cbv query <repo> "<symbol>" --lane fast`), how to run via the launcher, the result JSON shape, and how to use it.

- [ ] **Step 1: Write `skills/codebase-identify/SKILL.md`** (full content in the "Skill Content" appendix below).
- [ ] **Step 2: Verify** front-matter parses (valid YAML, `name` + `description` present).

### Task 4: `codebase-ask` — understanding & relationship questions

**Files:** Create `skills/codebase-ask/SKILL.md`.

Front-matter `name: codebase-ask`. Description triggering-focused: "how does X work / what does X do / who calls X / what conditions cause Y / what module handles Z / explain the X flow". Body opens with the **Scope check** mirror of `codebase-identify`. Body then: a verb-routing table (question shape -> `cbv` verb), how to run each, result JSON, how to answer from it.

- [ ] **Step 1: Write `skills/codebase-ask/SKILL.md`** (full content in appendix).
- [ ] **Step 2: Verify** front-matter parses.

### Task 5: `architecture-codebase` — optional LLM artifacts

**Files:** Create `skills/architecture-codebase/SKILL.md`.

Front-matter `name: architecture-codebase`. Description: generate/regenerate LLM-written cluster labels + `ARCHITECTURE.md`; note it is optional and the only LLM-using skill. Body: the workflow — `cbv llm-payload <repo>` -> agent writes labels + markdown -> `cbv apply-llm-artifacts <repo> <result.json>` — with exact payload and result JSON shapes.

- [ ] **Step 1: Write `skills/architecture-codebase/SKILL.md`** (full content in appendix).
- [ ] **Step 2: Verify** front-matter parses.

### Task 6: Trim `vectorize-repo`

**Files:** Modify `skills/vectorize-repo/SKILL.md`.

- [ ] **Step 1:** Delete the "Step 3 — Finalize LLM artifacts" section.
- [ ] **Step 2:** Replace the LLM note so it states: cluster labels and `ARCHITECTURE.md` are written as deterministic placeholders; to get real LLM-written ones, use the `architecture-codebase` skill. Keep `"llm_artifacts_pending"` in the summary example.
- [ ] **Step 3:** Grep the file for stale references to `codebase-query` and update to `codebase-identify` / `codebase-ask`.

---

## Chunk 3: Docs and release

### Task 7: Rewrite `README.md`

Full plain-language guide (no childish analogies). Required sections: what it is and who it is for; install; the four skills and the intent split; the workflow (build once, then ask/identify, optional architecture); how indexing works; how retrieval and ranking work (lanes, the fused signals, RRF, graph, rerank — deterministic routing); what you get vs what you do not; current language support; the full CLI reference; limitations.

- [ ] **Step 1: Rewrite `README.md`.**
- [ ] **Step 2: Grep** the repo for remaining `codebase-query` / `codebase-relate` skill references and fix.

### Task 8: Bump plugin version

- [ ] **Step 1:** In `.claude-plugin/plugin.json`, change `"version": "0.3.0"` to `"version": "1.0.0"`.

### Task 9: Verify and commit

- [ ] **Step 1: Run the full suite** `pytest -q`. Expected: all green.
- [ ] **Step 2: Commit** all changes with a descriptive message.

---

## Appendix: Skill Content

The exact SKILL.md bodies are authored during execution (Tasks 3-5), following these rules from the skill-creator guidance: triggering-focused descriptions, imperative instructions, explain the *why*, no heavy-handed MUSTs, and the two ask-side scope checks written as true structural mirrors. The scope-check wording is locked here:

**`codebase-identify` scope check:**
> ## Scope check — do this first
> This skill returns **locations** — it answers "where is X" by pointing at exact file and line ranges. It does not explain behavior or trace relationships.
> Before running, check the user's question:
> - If it asks how or why something works, what calls what, what conditions cause something, or anything that needs reading and explaining code, tell the user: *"This needs relationship and behavior knowledge, not just a location — using codebase-ask instead."* Then invoke the `codebase-ask` skill and stop.
> - Otherwise, proceed with the steps below.

**`codebase-ask` scope check (mirror):**
> ## Scope check — do this first
> This skill answers **understanding and relationship questions** — how code works, what calls what, what a module is responsible for. It reads code and traverses the graph to do that.
> Before running, check the user's question:
> - If it only asks for the location of a known symbol — no explanation, no relationships, just "where is it", tell the user: *"This only needs a location — using codebase-identify instead, which is faster and skips semantic retrieval."* Then invoke the `codebase-identify` skill and stop.
> - Otherwise, proceed with the steps below.
