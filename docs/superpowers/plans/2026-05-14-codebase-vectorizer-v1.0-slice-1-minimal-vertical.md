# codebase-vectorizer v1.0 — Slice 1: Minimal Vertical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up codebase-vectorizer v1.0 with the smallest viable end-to-end system: index a repo via text-window chunking + `jinaai/jina-code-embeddings-1.5b` into the v1.0 SQLite schema (chunks + FTS5 + sqlite-vec) and query it with BM25 + dense + Reciprocal Rank Fusion. The returned JSON matches the v1.0 spec shape (with zero-valued placeholders for stats that later slices populate).

**Architecture:** Python CLI. Launcher (`run.sh` POSIX / `run.ps1` Windows) finds Python 3.10–3.13 → invokes `bootstrap.py` → bootstrap creates the plugin venv at `<data_home>/python-env/` and dispatches `python -m cbv …` inside it. The package `scripts/cbv/` is a clean from-scratch rewrite. One `index.sqlite` per repo at `<data_home>/repos/<name>/`. The embedder picks CPU (llama-cpp-python GGUF INT4) vs GPU (transformers FP16) at runtime. The full v1.0 schema (all ten tables from the spec) is created at index time so future slices add no migrations; this slice only populates `chunks` / `chunks_fts` / `vec_chunks` / `meta`.

**Tech Stack:** Python 3.10–3.13 (plugin venv), SQLite (FTS5 + `sqlite-vec ≥ 0.1.6`), `transformers ≥ 4.42` + `torch ≥ 2.3`, `llama-cpp-python ≥ 0.2.80`, `huggingface_hub`, `numpy`, `pathspec`, `requests`, `pytest` (dev-only).

**Scope boundary (this slice covers ONLY the items below). Out of scope for Slice 1:**

- Tree-sitter + cAST chunking (Slice 2)
- Symbol-graph nodes/edges + `tags.scm` extraction + 1-hop graph expansion (Slice 3)
- Identifier trigram index + fast-lane / full-lane router (Slice 4)
- Cross-encoder rerank with `mxbai-rerank-large-v2` (Slice 5)
- Global PageRank + Personalized PageRank seeding (Slice 6)
- Concept clusters (UMAP + HDBSCAN + LLM labels) (Slice 7)
- `codebase-relate` skill and `scripts/cbv/commands/relate.py` (Slice 8)
- Intra-procedural CFG block nodes + `controls` / `guards` edges (Slice 9)
- Intra-procedural DFG `dataflow` edges + flow-relate subcommands (Slice 10)
- Cross-repo `embedding_cache.sqlite` (Slice 11)
- Merkle file table + incremental updates (Slice 12)
- `ARCHITECTURE.md` auto-generation (one LLM pass) (Slice 13)
- Benchmark harness (`bench/coir_subset.jsonl`, `repoeval_mini.jsonl`) (Slice 14)
- Confidence + `refined_queries` hints (Slice 15)

**Migration policy:** Clean rewrite. Every file currently under `scripts/` is deleted and replaced. Indexes created by v0.3.0 are NOT auto-upgraded; the query command checks `meta.schema_version` and emits the spec-mandated "legacy schema" error when it doesn't equal `"1.0"`. The legacy detector lands in this slice even though Merkle/incremental ship in Slice 12 — it is a one-row SELECT on `meta`.

**Reference:** the authoritative source is `specs/2026-05-14-codebase-vectorizer-v1.0-design.md`. Every storage decision, JSON shape, and pipeline rule below traces back to that file. When this plan and the spec disagree, the spec wins.

---

## File structure (after Slice 1)

```
scripts/
├── run.sh                        POSIX launcher (entry point)
├── run.ps1                       Windows launcher (entry point)
├── bootstrap.py                  stdlib-only: venv create + dispatch
├── requirements.txt              Slice 1 dependency pins
└── cbv/                          Python package (the v1.0 codebase)
    ├── __init__.py               empty
    ├── __main__.py               `python -m cbv` entry
    ├── paths.py                  data_home / repos_dir / venv paths
    ├── db.py                     full v1.0 DDL + open() + meta helpers
    ├── walker.py                 file walk + .gitignore + size/binary filter
    ├── source.py                 git clone or local recursive copy
    ├── chunker.py                line-aware text-window chunker
    ├── quantize.py               INT8 quantize / dequantize for vec_chunks
    ├── embedder.py               Embedder ABC + JinaCodeEmbedder + StubEmbedder
    ├── cli.py                    argparse + verb dispatch
    └── commands/
        ├── __init__.py           empty
        ├── vectorize.py          `vectorize <url|path>` orchestration
        ├── query.py              `query <repo> "<q>"` BM25 + dense + RRF
        ├── list_cmd.py           `list` indexed repos
        └── info.py               `info` paths + readiness

tests/
├── __init__.py                   empty
├── conftest.py                   shared fixtures (tmp_data_home, stub_embedder)
├── fixtures/
│   └── simple-python/            10-file Python fixture for E2E tests
│       ├── pkg/__init__.py
│       ├── pkg/auth.py
│       ├── pkg/router.py
│       ├── pkg/db.py
│       ├── pkg/utils.py
│       ├── tests/test_auth.py
│       ├── README.md
│       ├── pyproject.toml
│       ├── main.py
│       └── .gitignore
├── unit/
│   ├── __init__.py
│   ├── test_paths.py
│   ├── test_walker.py
│   ├── test_source.py
│   ├── test_chunker.py
│   ├── test_quantize.py
│   ├── test_embedder.py
│   ├── test_db.py
│   └── test_commands.py          list/info smoke tests
└── integration/
    ├── __init__.py
    └── test_full_index.py        index → query → assert against fixture

skills/
├── vectorize-repo/SKILL.md       updated to v1.0 invocation + JSON
└── codebase-query/SKILL.md       updated to v1.0 JSON shape

docs/superpowers/plans/
└── 2026-05-14-codebase-vectorizer-v1.0-slice-1-minimal-vertical.md   THIS FILE
```

**Module boundaries — single responsibility per file:**

- `paths.py`: pure path resolution, stdlib-only (shared by bootstrap and the venv-runtime code).
- `db.py`: SQL DDL strings, `open(path) -> sqlite3.Connection`, `init_schema(conn)`, `read_meta(conn, key)`, `write_meta(conn, key, value)`, `assert_schema_v1(conn)`. No business logic.
- `walker.py`: yields `(path, relpath, size)` tuples honoring gitignore / size / binary filters. Knows nothing about chunking or embedding.
- `source.py`: resolves a URL or local path into a fully-populated `<repo>/source/` directory plus a `commit_sha` (or empty string). Knows nothing about chunking or DB.
- `chunker.py`: pure function over file content → list of `Chunk` dataclasses. Knows nothing about DB or embedding.
- `quantize.py`: numpy-only INT8 helpers. Pure.
- `embedder.py`: `Embedder` ABC + concrete implementations. Selects via env var or auto-detect. Knows nothing about chunking or DB.
- `commands/vectorize.py`: orchestration — composes the above into the indexing pipeline + writes DB.
- `commands/query.py`: orchestration — embed query + BM25 + dense + RRF + format.
- `commands/list_cmd.py`, `commands/info.py`: thin verbs.

Files that change together live together. The `commands/` subpackage holds verbs (each verb is independently testable). The package root holds reusable infrastructure modules consumed by verbs.

---

## Tasks

### Task 1: Wipe v0.3.0 scripts/ and create the new directory skeleton

Bring the repo to a clean state for the rewrite. No Python code yet; just the layout.

**Files:**
- Delete: `scripts/bootstrap.py`, `scripts/chunker.py`, `scripts/db.py`, `scripts/embedder.py`, `scripts/paths.py`, `scripts/query.py`, `scripts/requirements.txt`, `scripts/run.ps1`, `scripts/run.sh`, `scripts/vectorize.py`
- Create: `scripts/cbv/__init__.py`, `scripts/cbv/commands/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Delete every v0.3.0 file under scripts/**

```bash
git rm scripts/bootstrap.py scripts/chunker.py scripts/db.py scripts/embedder.py \
       scripts/paths.py scripts/query.py scripts/requirements.txt \
       scripts/run.ps1 scripts/run.sh scripts/vectorize.py
```

- [ ] **Step 2: Create the new directory skeleton**

```bash
mkdir -p scripts/cbv/commands tests/unit tests/integration tests/fixtures
```

- [ ] **Step 3: Add empty package markers**

Create the following files with literal content `` (empty, single newline):

- `scripts/cbv/__init__.py`
- `scripts/cbv/commands/__init__.py`
- `tests/__init__.py`
- `tests/unit/__init__.py`
- `tests/integration/__init__.py`

- [ ] **Step 4: Add a placeholder conftest**

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures for codebase-vectorizer tests.

Populated incrementally across Slice 1 tasks. Slice 1 ends with at
least the tmp_data_home and stub_embedder fixtures.
"""
```

- [ ] **Step 5: Verify pytest can discover the (empty) test tree**

Run: `pytest tests/ -v --collect-only`
Expected: exit code 0, output reports "no tests collected" (or 0 tests).

If pytest is not installed, install it into the user's currently-active Python (NOT the plugin venv — the plugin venv does not exist yet). The plan assumes `pytest` is available for development; a future task adds it to a dev requirements file.

- [ ] **Step 6: Commit**

```bash
git add scripts/ tests/
git commit -m "slice 1 t1: wipe v0.3.0 scripts and create new directory skeleton"
```

---

### Task 2: scripts/cbv/paths.py — data and venv path resolution

Centralize every filesystem location the rest of the code reads. Stdlib-only so bootstrap can import it before the venv exists.

**Files:**
- Create: `scripts/cbv/paths.py`
- Create: `tests/unit/test_paths.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_paths.py`:

```python
"""Tests for cbv.paths — pure path resolution, no I/O against real
filesystem locations. We override env vars per test with monkeypatch
to avoid touching the user's actual data home.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# scripts/ on sys.path so `from cbv import paths` resolves the way
# bootstrap.py will at runtime.
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import paths  # noqa: E402


def _clear_env(monkeypatch):
    for k in ("CODEBASE_VECTORIZER_HOME", "CLAUDE_PLUGIN_DATA",
              "XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(k, raising=False)


def test_data_home_uses_codebase_vectorizer_home_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "custom"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "ignored"))
    assert paths.data_home() == (tmp_path / "custom").resolve()


def test_data_home_uses_claude_plugin_data_when_no_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin"))
    assert paths.data_home() == (tmp_path / "plugin").resolve()


def test_data_home_falls_back_to_platform_default(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
        assert paths.data_home() == tmp_path / "appdata" / "codebase-vectorizer"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert paths.data_home() == (tmp_path / "xdg").resolve() / "codebase-vectorizer"


def test_repos_dir_under_data_home(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.repos_dir() == tmp_path.resolve() / "repos"


def test_repo_dir_combines_name(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.repo_dir("myrepo") == tmp_path.resolve() / "repos" / "myrepo"


def test_find_repo_returns_none_when_missing(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.find_repo("nope") is None


def test_find_repo_returns_dir_when_index_present(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    repo = tmp_path.resolve() / "repos" / "yes"
    repo.mkdir(parents=True)
    (repo / "index.sqlite").write_bytes(b"")
    assert paths.find_repo("yes") == repo


def test_list_indexed_repos_filters_to_dirs_with_index(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    repos = tmp_path.resolve() / "repos"
    (repos / "a").mkdir(parents=True)
    (repos / "a" / "index.sqlite").write_bytes(b"")
    (repos / "b").mkdir(parents=True)  # no index.sqlite
    (repos / "stray.txt").write_text("not a dir")
    listed = paths.list_indexed_repos()
    assert [p.name for p in listed] == ["a"]


def test_python_env_executable_layout(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    exe = paths.python_env_executable()
    if os.name == "nt":
        assert exe == tmp_path.resolve() / "python-env" / "Scripts" / "python.exe"
    else:
        assert exe == tmp_path.resolve() / "python-env" / "bin" / "python"


def test_embedding_cache_path_under_data_home(monkeypatch, tmp_path):
    """Slice 11 populates this; Slice 1 just reserves the location."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.embedding_cache_path() == tmp_path.resolve() / "embedding_cache.sqlite"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_paths.py -v`
Expected: all tests FAIL with `ModuleNotFoundError: No module named 'cbv.paths'` (or `ImportError`).

- [ ] **Step 3: Implement scripts/cbv/paths.py**

Create `scripts/cbv/paths.py`:

```python
"""Path resolution for codebase-vectorizer.

All plugin state lives under a single root, in this order of preference:

  1. $CODEBASE_VECTORIZER_HOME    (user override / debugging)
  2. $CLAUDE_PLUGIN_DATA           (set by Claude Code; canonical)
  3. Platform default fallback     (running outside a Claude Code session)

Underneath that root:

  <root>/python-env/         the plugin's isolated venv (never activated)
  <root>/repos/<name>/       per-indexed-repo state
  <root>/embedding_cache.sqlite   cross-repo cache (populated in Slice 11)

Stdlib-only so bootstrap.py can import this before the venv exists.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


def data_home() -> Path:
    explicit = os.environ.get("CODEBASE_VECTORIZER_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "codebase-vectorizer"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "codebase-vectorizer"
    return Path.home() / ".local" / "share" / "codebase-vectorizer"


def python_env_dir() -> Path:
    return data_home() / "python-env"


def python_env_executable() -> Path:
    base = python_env_dir()
    if os.name == "nt":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def repos_dir() -> Path:
    return data_home() / "repos"


def repo_dir(repo_name: str) -> Path:
    return repos_dir() / repo_name


def find_repo(repo_name: str) -> Optional[Path]:
    candidate = repo_dir(repo_name)
    if (candidate / "index.sqlite").exists():
        return candidate
    return None


def list_indexed_repos() -> List[Path]:
    out: List[Path] = []
    base = repos_dir()
    if not base.exists():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if (child / "index.sqlite").exists():
            out.append(child)
    return out


def embedding_cache_path() -> Path:
    """Reserved for Slice 11. Returns the canonical location."""
    return data_home() / "embedding_cache.sqlite"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_paths.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/paths.py tests/unit/test_paths.py
git commit -m "slice 1 t2: cbv.paths — data_home / repos_dir / venv path resolution"
```

---

### Task 3: Launcher chain — bootstrap.py + run.sh + run.ps1 + requirements.txt + cli skeleton

Build the entry chain. After this task, `bash scripts/run.sh info` (POSIX) or `& scripts\run.ps1 info` (Windows) prints data paths without requiring the venv, and `bash scripts/run.sh setup` creates the venv with v1.0 dependencies.

**Files:**
- Create: `scripts/bootstrap.py`, `scripts/run.sh`, `scripts/run.ps1`, `scripts/requirements.txt`
- Create: `scripts/cbv/__main__.py`, `scripts/cbv/cli.py`
- Create: `tests/unit/test_bootstrap_dispatch.py`

- [ ] **Step 1: Write the failing test for the cli skeleton**

Create `tests/unit/test_bootstrap_dispatch.py`:

```python
"""Tests for the verb dispatcher's argument parsing only.

The actual command implementations are tested in their own modules.
This test asserts that `python -m cbv <verb> ...` parses without
error and dispatches to a function registered by the verb name.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import cli  # noqa: E402


def test_cli_known_verbs():
    """All Slice 1 verbs are registered on the parser."""
    parser = cli.build_parser()
    actions = {a.dest: a for a in parser._actions}
    sub = next(a for a in parser._actions if a.dest == "verb")
    choices = set(sub.choices.keys())
    assert {"vectorize", "query", "list", "info"} <= choices


def test_cli_dispatch_table_has_all_verbs():
    """Every parser choice has a callable in the dispatch table."""
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "verb")
    for verb in sub.choices.keys():
        assert verb in cli.DISPATCH, f"missing dispatcher for {verb!r}"
        assert callable(cli.DISPATCH[verb])


def test_cli_parses_vectorize_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["vectorize", "https://github.com/x/y"])
    assert ns.verb == "vectorize"
    assert ns.source == "https://github.com/x/y"


def test_cli_parses_query_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["query", "myrepo", "how does auth work", "--top-k", "5"])
    assert ns.verb == "query"
    assert ns.repo == "myrepo"
    assert ns.question == "how does auth work"
    assert ns.top_k == 5


def test_cli_query_top_k_default():
    parser = cli.build_parser()
    ns = parser.parse_args(["query", "r", "q"])
    assert ns.top_k == 10


def test_cli_unknown_verb_errors(capsys):
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nonsense"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_bootstrap_dispatch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cbv.cli'`.

- [ ] **Step 3: Implement scripts/cbv/cli.py**

Create `scripts/cbv/cli.py`:

```python
"""argparse-based verb dispatcher for `python -m cbv`.

Each verb lives in `cbv.commands.<verb>` and exposes a `run(ns) -> int`
function. The parser is built independently of the dispatch table so
that unit tests can verify both surface shapes without invoking commands.
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict

# Commands are imported lazily inside _dispatch() so unit tests that
# only exercise argument parsing don't pull in heavy modules
# (transformers, torch) at import time.


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cbv", description="codebase-vectorizer v1.0")
    sub = p.add_subparsers(dest="verb", required=True)

    pv = sub.add_parser("vectorize", help="Index a repo (URL or local path)")
    pv.add_argument("source", help="git URL or local path")
    pv.add_argument("--output-dir", default=None,
                    help="override repo directory location")
    pv.add_argument("--max-file-mb", type=float, default=1.5,
                    help="skip files larger than this many MB (default 1.5)")

    pq = sub.add_parser("query", help="Query an indexed repo")
    pq.add_argument("repo", help="indexed repo name")
    pq.add_argument("question", help="natural-language or identifier query")
    pq.add_argument("--top-k", type=int, default=10,
                    help="number of results to return (default 10)")

    sub.add_parser("list", help="List every indexed repo")
    sub.add_parser("info", help="Print plugin paths and readiness")

    return p


def _import_command(verb: str):
    if verb == "vectorize":
        from cbv.commands import vectorize as mod
    elif verb == "query":
        from cbv.commands import query as mod
    elif verb == "list":
        from cbv.commands import list_cmd as mod
    elif verb == "info":
        from cbv.commands import info as mod
    else:  # pragma: no cover — argparse rejects unknown verbs first
        raise SystemExit(f"unknown verb: {verb}")
    return mod


DISPATCH: Dict[str, Callable[[argparse.Namespace], int]] = {
    # Wrapped to defer the import until invocation. Each entry returns the
    # result of the command's run() function.
    "vectorize": lambda ns: _import_command("vectorize").run(ns),
    "query":     lambda ns: _import_command("query").run(ns),
    "list":      lambda ns: _import_command("list").run(ns),
    "info":      lambda ns: _import_command("info").run(ns),
}


def main(argv=None) -> int:
    ns = build_parser().parse_args(argv)
    return DISPATCH[ns.verb](ns)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 4: Implement scripts/cbv/__main__.py**

Create `scripts/cbv/__main__.py`:

```python
"""Module entry point: `python -m cbv <verb> ...`."""
from __future__ import annotations

import sys

from cbv.cli import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Stub the command modules so import succeeds**

These stubs let the parser/dispatcher tests pass without each command being implemented yet. Each later task replaces its corresponding stub.

Create `scripts/cbv/commands/vectorize.py`:

```python
"""Stub — implemented in Task 10."""
from __future__ import annotations


def run(ns) -> int:
    raise NotImplementedError("vectorize: implemented in Slice 1 Task 10")
```

Create `scripts/cbv/commands/query.py`:

```python
"""Stub — implemented in Task 11."""
from __future__ import annotations


def run(ns) -> int:
    raise NotImplementedError("query: implemented in Slice 1 Task 11")
```

Create `scripts/cbv/commands/list_cmd.py`:

```python
"""Stub — implemented in Task 12."""
from __future__ import annotations


def run(ns) -> int:
    raise NotImplementedError("list: implemented in Slice 1 Task 12")
```

Create `scripts/cbv/commands/info.py`:

```python
"""Stub — implemented in Task 12."""
from __future__ import annotations


def run(ns) -> int:
    raise NotImplementedError("info: implemented in Slice 1 Task 12")
```

- [ ] **Step 6: Run cli tests to verify they pass**

Run: `pytest tests/unit/test_bootstrap_dispatch.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Write requirements.txt**

Create `scripts/requirements.txt`:

```
# codebase-vectorizer v1.0 Slice 1 dependencies.
# Pin minor-version floors per spec; let pip resolve the latest compatible.
sqlite-vec>=0.1.6
transformers>=4.42
torch>=2.3
llama-cpp-python>=0.2.80
huggingface_hub>=0.23.0
numpy>=1.26
pathspec>=0.12
requests>=2.31.0
```

Later slices add: `tree-sitter`, `tree-sitter-language-pack` (Slice 2), `networkx` (Slice 3), `sentence-transformers` (Slice 5), `umap-learn`, `hdbscan` (Slice 7).

- [ ] **Step 8: Write bootstrap.py**

Create `scripts/bootstrap.py`:

```python
#!/usr/bin/env python3
"""Bootstrap launcher: ensure venv + deps, then dispatch to `python -m cbv`.

Invoked by run.sh (POSIX) or run.ps1 (Windows). Those shims find a
usable Python 3.10-3.13 on PATH and call this script.

This script:
  1. Verifies the running interpreter is Python 3.10-3.13.
  2. Creates the venv at <data_home>/python-env if missing.
  3. Installs deps into the venv with --only-binary=:all: where possible.
  4. Runs `python -m cbv <verb> [args...]` inside the venv by absolute
     path. The venv is never activated, so the user's shell, $PATH,
     project venvs, and cwd are untouched.

Stdlib-only — safe to run on Python 3.10-3.13 before any dep is installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cbv.paths import (  # noqa: E402
    data_home,
    list_indexed_repos,
    python_env_dir,
    python_env_executable,
    repos_dir,
)

REQS = SCRIPT_DIR / "requirements.txt"
SUPPORTED_PY = {(3, 10), (3, 11), (3, 12), (3, 13)}


def check_python_version() -> None:
    cur = sys.version_info[:2]
    if cur not in SUPPORTED_PY:
        supported = ", ".join(f"{a}.{b}" for a, b in sorted(SUPPORTED_PY))
        print(
            f"ERROR: codebase-vectorizer needs Python 3.10-3.13 "
            f"(got {cur[0]}.{cur[1]}).\n"
            f"Supported: {supported}\n"
            f"  Windows:       winget install Python.Python.3.12\n"
            f"  Debian/Ubuntu: sudo apt install python3.12 python3.12-venv\n"
            f"  macOS:         brew install python@3.12",
            file=sys.stderr,
        )
        sys.exit(2)


def ensure_venv() -> None:
    if python_env_executable().exists():
        return
    target = python_env_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"[bootstrap] creating Python env at {target}", flush=True)
    builder = venv.EnvBuilder(
        with_pip=True,
        clear=False,
        symlinks=(os.name != "nt"),
        upgrade_deps=False,
    )
    builder.create(target)


def deps_installed(py: Path) -> bool:
    """Quick smoke check: import the v1.0 minimums."""
    r = subprocess.run(
        [str(py), "-c",
         "import sqlite_vec, transformers, torch, llama_cpp, "
         "numpy, pathspec, requests, huggingface_hub"],
        capture_output=True,
    )
    return r.returncode == 0


def install_deps(py: Path) -> None:
    if not REQS.exists():
        print(f"ERROR: requirements.txt not found at {REQS}", file=sys.stderr)
        sys.exit(1)
    print(f"[bootstrap] installing deps into {python_env_dir()} "
          f"(prebuilt wheels preferred)", flush=True)
    cmd = [str(py), "-m", "pip", "install",
           "-r", str(REQS),
           "--upgrade",
           "--only-binary=:all:",
           "--disable-pip-version-check"]
    r = subprocess.run(cmd)
    if r.returncode == 0:
        return
    print("[bootstrap] binary-only install failed; retrying allowing source builds.",
          flush=True)
    cmd_src = [str(py), "-m", "pip", "install",
               "-r", str(REQS),
               "--upgrade",
               "--disable-pip-version-check"]
    r = subprocess.run(cmd_src)
    if r.returncode != 0:
        print(
            "[bootstrap] FAILED. Likely cause: your Python has no prebuilt wheel "
            "for one of the deps (often llama-cpp-python or torch). Install Python "
            "3.12 and re-run; the launcher picks it up automatically.",
            file=sys.stderr,
        )
        sys.exit(r.returncode)


def ensure_ready() -> Path:
    check_python_version()
    ensure_venv()
    py = python_env_executable()
    if not deps_installed(py):
        install_deps(py)
    return py


def cmd_info() -> int:
    """Inlined here so `info` works before the venv exists.
    Mirrors cbv.commands.info; kept in sync by Task 12's tests."""
    print(f"data_home:        {data_home()}")
    print(f"python_env:       {python_env_dir()}")
    print(f"python_env_bin:   {python_env_executable()}")
    print(f"python_env_ready: {python_env_executable().exists()}")
    print(f"repos_dir:        {repos_dir()}")
    repos = list_indexed_repos()
    print(f"indexed_repos:    {len(repos)}")
    for r in repos:
        print(f"  - {r.name}  @  {r}")
    return 0


def usage() -> int:
    print(
        "Usage: bootstrap.py {setup|vectorize|query|list|info} [args...]\n"
        "  setup                       create venv and install deps (idempotent)\n"
        "  vectorize <url|path>        index a repo\n"
        "  query <name> <question>     query an indexed repo\n"
        "  list                        list every indexed repo\n"
        "  info                        print all paths and readiness",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    if len(sys.argv) < 2:
        return usage()

    subcmd = sys.argv[1]
    rest = sys.argv[2:]

    if subcmd == "info":
        return cmd_info()

    py = ensure_ready()

    if subcmd == "setup":
        print("[bootstrap] OK", flush=True)
        return 0

    if subcmd not in {"vectorize", "query", "list"}:
        print(f"Unknown subcommand: {subcmd}\n", file=sys.stderr)
        return usage()

    r = subprocess.run([str(py), "-m", "cbv", subcmd, *rest],
                       env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)})
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: Write run.sh (POSIX launcher)**

Create `scripts/run.sh`:

```bash
#!/usr/bin/env bash
# POSIX shim: find a usable Python 3.10-3.13 and hand off to bootstrap.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ver=$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
      case "$ver" in
        3.10|3.11|3.12|3.13) echo "$candidate"; return 0 ;;
      esac
    fi
  done
  return 1
}

PY="$(find_python || true)"
if [ -z "${PY:-}" ]; then
  echo "codebase-vectorizer needs Python 3.10-3.13 on PATH." >&2
  echo "  Debian/Ubuntu/WSL: sudo apt install python3.12 python3.12-venv" >&2
  echo "  macOS:             brew install python@3.12" >&2
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/bootstrap.py" "$@"
```

After creating: `chmod +x scripts/run.sh` (the next step's commit captures the executable bit).

- [ ] **Step 10: Write run.ps1 (Windows launcher)**

Create `scripts/run.ps1`:

```powershell
# Windows shim: find a usable Python 3.10-3.13 and hand off to bootstrap.py.
# Skips the Microsoft Store stub (visible under \WindowsApps\).
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Test-PyVersion {
  param([string]$Exe, [string[]]$ExtraArgs = @())
  try {
    $allArgs = $ExtraArgs + @('-c', 'import sys;print("%d.%d"%sys.version_info[:2])')
    $out = & $Exe @allArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out.Trim()
  } catch {
    return $null
  }
}

function Find-WorkablePython {
  foreach ($v in '3.13','3.12','3.11','3.10') {
    $ver = Test-PyVersion -Exe 'py' -ExtraArgs @("-$v")
    if ($ver -in '3.10','3.11','3.12','3.13') {
      return @{ Exe = 'py'; ExtraArgs = @("-$v") }
    }
  }
  foreach ($name in 'python','python3') {
    $cmds = Get-Command $name -All -ErrorAction SilentlyContinue
    foreach ($cmd in $cmds) {
      if ($cmd.Source -like '*WindowsApps\python*') { continue }
      $ver = Test-PyVersion -Exe $cmd.Source
      if ($ver -in '3.10','3.11','3.12','3.13') {
        return @{ Exe = $cmd.Source; ExtraArgs = @() }
      }
    }
  }
  return $null
}

$pyChoice = Find-WorkablePython
if (-not $pyChoice) {
  Write-Error @"
codebase-vectorizer needs Python 3.10-3.13 on PATH.
Install Python 3.12:  winget install Python.Python.3.12
Then re-run.
"@
  exit 1
}

$exe = $pyChoice.Exe
$pre = $pyChoice.ExtraArgs
$allArgs = $pre + @((Join-Path $scriptDir 'bootstrap.py')) + $args

& $exe @allArgs
exit $LASTEXITCODE
```

- [ ] **Step 11: Manual smoke test — `info` works without venv**

Run (PowerShell): `& scripts\run.ps1 info`
Run (POSIX, if available): `bash scripts/run.sh info`

Expected output (paths vary; key lines must appear):

```
data_home:        ...
python_env:       ...
python_env_bin:   ...
python_env_ready: False
repos_dir:        ...
indexed_repos:    0
```

Exit code: 0.

- [ ] **Step 12: Manual smoke test — `setup` creates venv and installs deps**

Run (PowerShell): `& scripts\run.ps1 setup`

Expected: the launcher creates `<data_home>/python-env/`, installs the dep set, prints `[bootstrap] OK`, exits 0. First run takes 2–10 minutes depending on `torch` wheel size; the model itself is NOT downloaded yet (that happens on first `vectorize`).

Then: `& scripts\run.ps1 info`
Expected: `python_env_ready: True`.

If the install fails with a wheel error mentioning `torch` or `llama-cpp-python`, the most likely cause is a Python version mismatch (e.g., system Python is 3.14+). Install Python 3.12 and re-run; the launcher picks it up automatically.

- [ ] **Step 13: Commit**

```bash
git add scripts/bootstrap.py scripts/run.sh scripts/run.ps1 scripts/requirements.txt \
        scripts/cbv/__main__.py scripts/cbv/cli.py \
        scripts/cbv/commands/vectorize.py scripts/cbv/commands/query.py \
        scripts/cbv/commands/list_cmd.py scripts/cbv/commands/info.py \
        tests/unit/test_bootstrap_dispatch.py
git update-index --chmod=+x scripts/run.sh
git commit -m "slice 1 t3: bootstrap + run.sh/ps1 + cli skeleton with verb stubs"
```

---

### Task 4: scripts/cbv/db.py — full v1.0 schema + meta helpers + legacy detection

Create the entire v1.0 schema (all ten tables from the spec) plus helpers to open a connection with `sqlite-vec` loaded and read/write the `meta` row set. Future slices populate the unused tables; Slice 1 populates `chunks` / `chunks_fts` / `vec_chunks` / `meta`.

The schema DDL traces 1:1 to `specs/2026-05-14-codebase-vectorizer-v1.0-design.md` § "Storage schema" — keep them in sync.

**Files:**
- Create: `scripts/cbv/db.py`
- Create: `tests/unit/test_db.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_db.py`:

```python
"""Tests for cbv.db — schema creation, meta helpers, legacy detection."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

# Whether the venv exports sqlite-vec for tests. Some unit tests run outside
# the plugin venv during development; skip those that need the extension.
try:
    import sqlite_vec  # noqa: F401
    HAVE_VEC = True
except ImportError:
    HAVE_VEC = False

from cbv import db  # noqa: E402

REQUIRED_TABLES = {
    "chunks", "chunks_fts", "symbol_trigrams",
    "vec_chunks",
    "nodes", "edges",
    "clusters", "chunk_clusters",
    "merkle_files",
    "meta",
}


@pytest.fixture
def conn(tmp_path):
    p = tmp_path / "test.sqlite"
    c = db.open_db(p)
    db.init_schema(c)
    yield c
    c.close()


def test_open_db_loads_sqlite_vec():
    """open_db enables the sqlite-vec extension."""
    if not HAVE_VEC:
        pytest.skip("sqlite-vec not installed in this environment")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        path = Path(f.name)
    try:
        c = db.open_db(path)
        ver = c.execute("SELECT vec_version()").fetchone()[0]
        assert isinstance(ver, str) and len(ver) > 0
        c.close()
    finally:
        path.unlink(missing_ok=True)


def test_init_schema_creates_every_v1_table(conn):
    if not HAVE_VEC:
        pytest.skip("sqlite-vec not installed")
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type IN ('table','virtual') OR name LIKE '%_fts'"
    ).fetchall()
    names = {r[0] for r in rows}
    missing = REQUIRED_TABLES - names
    assert not missing, f"missing tables: {missing}"


def test_chunks_columns_exact(conn):
    if not HAVE_VEC:
        pytest.skip()
    rows = conn.execute("PRAGMA table_info(chunks)").fetchall()
    names = [r[1] for r in rows]
    assert names == [
        "id", "file_path", "language", "kind", "name", "ast_path",
        "start_line", "end_line", "start_byte", "end_byte",
        "content", "content_hash", "token_count",
    ]


def test_write_and_read_meta(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "schema_version", "1.0")
    db.write_meta(conn, "total_chunks", "0")
    assert db.read_meta(conn, "schema_version") == "1.0"
    assert db.read_meta(conn, "total_chunks") == "0"
    assert db.read_meta(conn, "absent") is None


def test_write_meta_overwrites(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "total_chunks", "0")
    db.write_meta(conn, "total_chunks", "42")
    assert db.read_meta(conn, "total_chunks") == "42"


def test_assert_schema_v1_accepts_matching(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "schema_version", "1.0")
    db.assert_schema_v1(conn)  # no raise


def test_assert_schema_v1_raises_on_mismatch(conn):
    if not HAVE_VEC:
        pytest.skip()
    db.write_meta(conn, "schema_version", "0.9")
    with pytest.raises(db.LegacySchemaError) as exc:
        db.assert_schema_v1(conn)
    assert "older codebase-vectorizer index" in str(exc.value)


def test_assert_schema_v1_raises_when_meta_missing(tmp_path):
    """A pre-meta-table legacy DB (v0.3.0) raises the same error."""
    if not HAVE_VEC:
        pytest.skip()
    legacy = tmp_path / "legacy.sqlite"
    raw = sqlite3.connect(legacy)
    raw.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    raw.commit()
    raw.close()
    c = db.open_db(legacy)
    with pytest.raises(db.LegacySchemaError):
        db.assert_schema_v1(c)


def test_chunks_fts_sync_triggers(conn):
    """Inserting a chunk should be findable via FTS5 immediately."""
    if not HAVE_VEC:
        pytest.skip()
    conn.execute(
        "INSERT INTO chunks (file_path, language, kind, start_line, end_line, "
        "start_byte, end_byte, content, content_hash, token_count) "
        "VALUES ('x.py','python','window',1,5,0,42,'hello unique_token_xyz',"
        "'h0','4')"
    )
    conn.commit()
    rows = conn.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'unique_token_xyz'"
    ).fetchall()
    assert len(rows) == 1


def test_vec_chunks_insert_int8(conn):
    """vec_chunks accepts INT8 1536-dim payloads as bytes."""
    if not HAVE_VEC:
        pytest.skip()
    import numpy as np
    conn.execute(
        "INSERT INTO chunks (file_path, language, kind, start_line, end_line, "
        "start_byte, end_byte, content, content_hash, token_count) "
        "VALUES ('y.py','python','window',1,2,0,1,'x','h1','1')"
    )
    chunk_id = conn.execute("SELECT id FROM chunks WHERE file_path='y.py'").fetchone()[0]
    emb = np.full(1536, 5, dtype=np.int8).tobytes()
    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
        (chunk_id, emb),
    )
    conn.commit()
    rows = conn.execute(
        "SELECT chunk_id FROM vec_chunks WHERE chunk_id = ?", (chunk_id,)
    ).fetchall()
    assert rows == [(chunk_id,)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run inside the plugin venv: `<venv_python> -m pytest tests/unit/test_db.py -v`
Expected: tests fail with `ModuleNotFoundError: No module named 'cbv.db'`.

On dev machines without the plugin venv, run with the user's Python that has `sqlite-vec` installed. Tests that require `sqlite-vec` are skipped if it is not available.

- [ ] **Step 3: Implement scripts/cbv/db.py**

Create `scripts/cbv/db.py`:

```python
"""Database access for codebase-vectorizer v1.0.

Every DDL string in SCHEMA matches the authoritative spec at
specs/2026-05-14-codebase-vectorizer-v1.0-design.md § "Storage schema".

This module:
  - opens a sqlite3 connection with the sqlite-vec extension loaded,
  - creates the full v1.0 schema (all ten tables) in one transaction,
  - exposes read/write helpers for the meta key/value store,
  - exposes assert_schema_v1() for the spec-mandated legacy detector.

Slice 1 only WRITES to chunks / chunks_fts / vec_chunks / meta. The rest
of the tables exist for later slices; they remain empty until then.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import sqlite_vec


class LegacySchemaError(RuntimeError):
    """Raised when an index's meta.schema_version is missing or not '1.0'.

    Spec § "Detected legacy index handling".
    """


SCHEMA_VERSION = "1.0"


# --- DDL ---------------------------------------------------------------------

DDL_CHUNKS = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_path TEXT NOT NULL,
    language TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT,
    ast_path TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    token_count INTEGER NOT NULL
);
"""

DDL_CHUNKS_IDX = """
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind);
"""

# FTS5 with porter stemmer + unicode61 with code-friendly separator chars.
# Tokenize option is SQL-quoted; doubled single quotes inside escape one quote.
DDL_CHUNKS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content=chunks,
    content_rowid=id,
    tokenize='porter unicode61 separators ''.,;:()[]{}<>!?'''
);
"""

# Sync triggers — standard FTS5 external-content pattern.
DDL_CHUNKS_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

DDL_SYMBOL_TRIGRAMS = """
CREATE TABLE IF NOT EXISTS symbol_trigrams (
    trigram TEXT NOT NULL,
    chunk_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (trigram, chunk_id, symbol),
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_trigrams ON symbol_trigrams(trigram);
CREATE INDEX IF NOT EXISTS idx_symbols ON symbol_trigrams(symbol);
"""

# sqlite-vec ANN index. INT8 quantized, cosine distance. Dimension 1536
# matches jina-code-embeddings-1.5b. Slice 1's only embedder; alternate
# embedders ship in later slices via separately-typed tables.
DDL_VEC_CHUNKS = """
CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding INT8[1536] distance_metric=cosine
);
"""

DDL_NODES = """
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT,
    parent_id INTEGER,
    chunk_id INTEGER,
    pagerank REAL DEFAULT 0.0,
    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_short ON nodes(short_name);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_chunk ON nodes(chunk_id);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_pr ON nodes(pagerank DESC);
"""

DDL_EDGES = """
CREATE TABLE IF NOT EXISTS edges (
    src INTEGER NOT NULL,
    dst INTEGER NOT NULL,
    kind TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    PRIMARY KEY (src, dst, kind),
    FOREIGN KEY (src) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (dst) REFERENCES nodes(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, kind);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, kind);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
"""

DDL_CLUSTERS = """
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    summary TEXT NOT NULL,
    centroid BLOB NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunk_clusters (
    chunk_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    membership REAL NOT NULL,
    PRIMARY KEY (chunk_id, cluster_id),
    FOREIGN KEY (chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
    FOREIGN KEY (cluster_id) REFERENCES clusters(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cc_cluster ON chunk_clusters(cluster_id);
"""

DDL_MERKLE = """
CREATE TABLE IF NOT EXISTS merkle_files (
    file_path TEXT PRIMARY KEY,
    blob_sha TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    last_indexed_at INTEGER NOT NULL
);
"""

DDL_META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ALL_DDL = [
    DDL_CHUNKS, DDL_CHUNKS_IDX,
    DDL_CHUNKS_FTS, DDL_CHUNKS_FTS_TRIGGERS,
    DDL_SYMBOL_TRIGRAMS,
    DDL_VEC_CHUNKS,
    DDL_NODES, DDL_EDGES,
    DDL_CLUSTERS,
    DDL_MERKLE,
    DDL_META,
]


# --- API ---------------------------------------------------------------------

def open_db(path: Path) -> sqlite3.Connection:
    """Open a sqlite3 connection with sqlite-vec loaded.

    The caller is responsible for closing the connection.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create every v1.0 table (idempotent)."""
    with conn:
        for stmt in ALL_DDL:
            conn.executescript(stmt)


def read_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def write_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def assert_schema_v1(conn: sqlite3.Connection) -> None:
    """Raise LegacySchemaError if the index isn't a v1.0 index.

    Two failure modes are treated identically:
      (a) the meta table doesn't exist (very old indexes)
      (b) meta.schema_version != "1.0"
    """
    try:
        version = read_meta(conn, "schema_version")
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            version = None
        else:
            raise
    if version != SCHEMA_VERSION:
        raise LegacySchemaError(
            f"Detected an older codebase-vectorizer index "
            f"(schema_version={version!r}, expected {SCHEMA_VERSION!r}). "
            f"The current schema requires re-indexing — different embedder "
            f"dimensions and additional tables. Run "
            f"`run.sh vectorize <repo>` (or run.ps1 on Windows) to upgrade."
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv_python> -m pytest tests/unit/test_db.py -v`
Expected: all tests pass. Tests that require `sqlite-vec` may be skipped if running outside the plugin venv; in the venv they pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/db.py tests/unit/test_db.py
git commit -m "slice 1 t4: cbv.db — v1.0 schema, meta helpers, legacy detector"
```

---

### Task 5: scripts/cbv/walker.py — file walk with gitignore + size/binary filters

Walk a source tree and yield indexable files. Respects `.gitignore` patterns via `pathspec`, skips files exceeding the configured size budget, and skips files whose first 8 KB contain a NUL byte (binary heuristic).

**Files:**
- Create: `scripts/cbv/walker.py`
- Create: `tests/unit/test_walker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_walker.py`:

```python
"""Tests for cbv.walker — file enumeration with gitignore/size/binary filters."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import walker  # noqa: E402


def _build_tree(root: Path, files: dict[str, bytes]) -> None:
    for relpath, content in files.items():
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)


def test_walker_yields_relative_paths(tmp_path):
    _build_tree(tmp_path, {
        "a.py": b"print('a')\n",
        "pkg/b.py": b"print('b')\n",
    })
    entries = sorted(e.relpath.as_posix() for e in walker.walk(tmp_path, max_file_mb=1.5))
    assert entries == ["a.py", "pkg/b.py"]


def test_walker_skips_dotgit(tmp_path):
    _build_tree(tmp_path, {
        ".git/HEAD": b"ref: refs/heads/main\n",
        ".git/objects/pack/x.pack": b"\x00" * 4,
        "src/main.py": b"x=1\n",
    })
    entries = sorted(e.relpath.as_posix() for e in walker.walk(tmp_path, max_file_mb=1.5))
    assert entries == ["src/main.py"]


def test_walker_honors_gitignore(tmp_path):
    _build_tree(tmp_path, {
        ".gitignore": b"build/\n*.log\n",
        "src/a.py": b"x=1\n",
        "build/artifact.o": b"obj",
        "info.log": b"log",
    })
    entries = sorted(e.relpath.as_posix() for e in walker.walk(tmp_path, max_file_mb=1.5))
    assert entries == [".gitignore", "src/a.py"]


def test_walker_skips_oversized(tmp_path):
    _build_tree(tmp_path, {
        "small.py": b"x=1\n",
        "big.bin": b"X" * (2 * 1024 * 1024),  # 2 MB
    })
    entries = sorted(e.relpath.as_posix() for e in walker.walk(tmp_path, max_file_mb=1.5))
    assert entries == ["small.py"]


def test_walker_skips_binary_via_nul_byte(tmp_path):
    _build_tree(tmp_path, {
        "good.py": b"hello world\n",
        "bin.dat": b"abc\x00def",
    })
    entries = sorted(e.relpath.as_posix() for e in walker.walk(tmp_path, max_file_mb=1.5))
    assert entries == ["good.py"]


def test_walker_returns_size_and_abspath(tmp_path):
    _build_tree(tmp_path, {"a.py": b"hello"})
    entry = next(walker.walk(tmp_path, max_file_mb=1.5))
    assert entry.abspath == (tmp_path / "a.py").resolve()
    assert entry.size_bytes == 5
    assert entry.relpath == Path("a.py")


def test_walker_handles_missing_gitignore(tmp_path):
    _build_tree(tmp_path, {"a.py": b"x"})
    entries = list(walker.walk(tmp_path, max_file_mb=1.5))
    assert len(entries) == 1


def test_walker_nested_gitignore_not_supported_warns(tmp_path):
    """Slice 1 only reads the root .gitignore. Nested ones are NOT honored.
    Document the limitation here so the engineer doesn't add scope creep."""
    _build_tree(tmp_path, {
        ".gitignore": b"",
        "sub/.gitignore": b"x.py\n",
        "sub/x.py": b"x=1\n",
    })
    entries = sorted(e.relpath.as_posix() for e in walker.walk(tmp_path, max_file_mb=1.5))
    # x.py IS yielded — nested .gitignore is not respected in Slice 1.
    assert "sub/x.py" in entries
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_walker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scripts/cbv/walker.py**

Create `scripts/cbv/walker.py`:

```python
"""File walker for codebase-vectorizer.

Yields one WalkEntry per indexable file. Filters:
  - .git/ trees skipped wholesale
  - root .gitignore honored via pathspec (nested .gitignore NOT honored
    in Slice 1; the spec calls out future work if needed)
  - files larger than max_file_mb skipped
  - files whose first 8 KB contain a NUL byte skipped as binary
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import pathspec

BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class WalkEntry:
    abspath: Path
    relpath: Path
    size_bytes: int


def _load_root_gitignore(root: Path) -> Optional[pathspec.PathSpec]:
    gi = root / ".gitignore"
    if not gi.is_file():
        return None
    return pathspec.PathSpec.from_lines("gitwildmatch", gi.read_text(encoding="utf-8", errors="replace").splitlines())


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    return b"\x00" in head


def walk(root: Path, max_file_mb: float = 1.5) -> Iterator[WalkEntry]:
    """Yield every indexable file under root."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    max_bytes = int(max_file_mb * 1024 * 1024)
    spec = _load_root_gitignore(root)

    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        rel_posix = rel.as_posix()
        # Always skip .git/ contents
        if rel.parts and rel.parts[0] == ".git":
            continue
        if spec is not None and spec.match_file(rel_posix):
            continue
        size = p.stat().st_size
        if size > max_bytes:
            continue
        if _looks_binary(p):
            continue
        yield WalkEntry(abspath=p, relpath=rel, size_bytes=size)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_walker.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/walker.py tests/unit/test_walker.py
git commit -m "slice 1 t5: cbv.walker — file walk with gitignore + size + binary filters"
```

---

### Task 6: scripts/cbv/source.py — git clone or local copy into source/

Given a URL or a local path, populate `<repo_dir>/source/` and return a `commit_sha` (or empty string when not available).

**Files:**
- Create: `scripts/cbv/source.py`
- Create: `tests/unit/test_source.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_source.py`:

```python
"""Tests for cbv.source — resolving a URL or local path into source/.

Git clone tests are network-bound and slow; they're gated by an env var.
Local-copy tests are pure-stdlib and always run.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import source  # noqa: E402


def test_is_git_url_recognizes_https():
    assert source.is_git_url("https://github.com/x/y.git")
    assert source.is_git_url("https://github.com/x/y")
    assert source.is_git_url("git@github.com:x/y.git")


def test_is_git_url_rejects_local_paths(tmp_path):
    assert not source.is_git_url(str(tmp_path))
    assert not source.is_git_url(".")
    assert not source.is_git_url("relative/path/here")


def test_derive_repo_name_from_url():
    assert source.derive_repo_name("https://github.com/owner/myrepo.git") == "myrepo"
    assert source.derive_repo_name("https://github.com/owner/myrepo") == "myrepo"
    assert source.derive_repo_name("git@github.com:owner/myrepo.git") == "myrepo"


def test_derive_repo_name_from_local_path(tmp_path):
    src = tmp_path / "myproject"
    src.mkdir()
    assert source.derive_repo_name(str(src)) == "myproject"


def test_copy_local_into_source(tmp_path):
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (src / "sub").mkdir()
    (src / "sub" / "b.py").write_text("y=2\n")

    dest = tmp_path / "repo" / "source"
    sha = source.populate_from_local(src, dest)

    assert (dest / "a.py").read_text() == "x=1\n"
    assert (dest / "sub" / "b.py").read_text() == "y=2\n"
    assert not (dest / ".git").exists(), ".git should be skipped on local copy"
    assert sha == "", "local copy without git metadata yields no commit_sha"


def test_copy_local_captures_commit_sha_if_git_present(tmp_path):
    # Init a real git repo with one commit
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(src), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(src), "add", "a.py"], check=True)
    subprocess.run(["git", "-C", str(src), "commit", "-qm", "init"], check=True)
    expected_sha = subprocess.check_output(
        ["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()

    dest = tmp_path / "repo" / "source"
    sha = source.populate_from_local(src, dest)
    assert sha == expected_sha
    assert not (dest / ".git").exists()


@pytest.mark.skipif(
    os.environ.get("CBV_RUN_NETWORK_TESTS") != "1",
    reason="network test; set CBV_RUN_NETWORK_TESTS=1 to enable",
)
def test_clone_url(tmp_path):
    dest = tmp_path / "repo" / "source"
    sha = source.populate_from_url(
        "https://github.com/octocat/Hello-World.git", dest
    )
    assert dest.is_dir()
    assert (dest / "README").exists()
    assert len(sha) == 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_source.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scripts/cbv/source.py**

Create `scripts/cbv/source.py`:

```python
"""Resolve a URL or a local path into a populated <repo>/source/ dir.

is_git_url    — heuristic URL classifier
derive_repo_name — last segment without .git suffix
populate_from_url   — git clone --depth 1 into dest
populate_from_local — copytree skipping .git, capture commit_sha if avail
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_URL_RE = re.compile(r"^(?:https?://|git@|ssh://|git://)")


def is_git_url(s: str) -> bool:
    return bool(_URL_RE.match(s.strip()))


def derive_repo_name(spec: str) -> str:
    """Last path segment without trailing .git."""
    s = spec.strip().rstrip("/")
    if is_git_url(s):
        if s.endswith(".git"):
            s = s[:-4]
        return s.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return Path(s).name


def populate_from_url(url: str, dest: Path) -> str:
    """git clone --depth 1 into dest, return HEAD commit_sha."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"git clone failed for {url!r}:\n{r.stderr.strip()}"
        )
    sha = subprocess.check_output(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
    ).strip()
    # Remove .git/ — we don't need history; it's just bytes from now on.
    shutil.rmtree(dest / ".git", ignore_errors=True)
    return sha


def populate_from_local(src: Path, dest: Path) -> str:
    """Recursive copy of src into dest, skipping .git/. Return commit_sha if
    src was a git repo and HEAD resolves; else empty string."""
    src = src.resolve()
    if not src.is_dir():
        raise NotADirectoryError(src)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_root: str, names: list[str]) -> list[str]:
        return [".git"] if ".git" in names else []

    shutil.copytree(src, dest, ignore=ignore, symlinks=False)

    sha = ""
    if (src / ".git").exists():
        try:
            sha = subprocess.check_output(
                ["git", "-C", str(src), "rev-parse", "HEAD"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            sha = ""
    return sha
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_source.py -v`
Expected: local-copy tests pass. The network test is skipped unless `CBV_RUN_NETWORK_TESTS=1`.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/source.py tests/unit/test_source.py
git commit -m "slice 1 t6: cbv.source — git clone and local recursive copy"
```

---

### Task 7: scripts/cbv/chunker.py — line-aware text-window chunker

Slice 1 chunker: split a file's text into non-overlapping byte windows that respect line boundaries and fit under a budget. Concatenating all chunks in order reproduces the file verbatim. Single lines that exceed the budget become their own (over-budget) chunk rather than being split mid-line. Each chunk knows its language (from the file extension), file path, byte range, and 1-indexed inclusive line range.

Slice 2 replaces this module with tree-sitter + cAST chunking; the `Chunk` shape stays the same so downstream code doesn't change.

**Files:**
- Create: `scripts/cbv/chunker.py`
- Create: `tests/unit/test_chunker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_chunker.py`:

```python
"""Tests for cbv.chunker — line-aware text-window chunking."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import chunker  # noqa: E402


def test_concat_invariant_small_file():
    content = "line1\nline2\nline3\n"
    chunks = list(chunker.chunk_text(content, language="python",
                                      file_path="x.py", budget_bytes=1500))
    assert "".join(c.content for c in chunks) == content


def test_concat_invariant_many_lines():
    content = "".join(f"line{i}\n" for i in range(200))
    chunks = list(chunker.chunk_text(content, language="python",
                                      file_path="x.py", budget_bytes=500))
    assert "".join(c.content for c in chunks) == content


def test_line_ranges_contiguous_and_one_indexed_inclusive():
    content = "a\nb\nc\nd\n"
    chunks = list(chunker.chunk_text(content, language="python",
                                      file_path="x.py", budget_bytes=4))
    # Each chunk is at most 4 bytes. "a\nb\n" = 4 bytes -> first chunk.
    assert chunks[0].start_line == 1
    last = chunks[-1].end_line
    # The content has 4 lines (a, b, c, d, plus a trailing newline counted as part of line 4)
    assert last == 4
    # contiguous coverage
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start_line == prev.end_line + 1
        assert nxt.start_byte == prev.end_byte


def test_byte_ranges_match_content():
    content = "ab\ncde\nfghij\n"
    chunks = list(chunker.chunk_text(content, language="python",
                                      file_path="x.py", budget_bytes=4))
    for c in chunks:
        assert content[c.start_byte:c.end_byte] == c.content


def test_oversized_single_line_yields_one_overbudget_chunk():
    huge = "X" * 5000 + "\n"
    chunks = list(chunker.chunk_text(huge, language="python",
                                      file_path="x.py", budget_bytes=1500))
    assert len(chunks) == 1
    assert len(chunks[0].content) == 5001


def test_content_hash_is_sha256_hex_of_content():
    content = "hello\n"
    chunks = list(chunker.chunk_text(content, language="python",
                                      file_path="x.py", budget_bytes=1500))
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert chunks[0].content_hash == expected


def test_kind_is_window_in_slice_1():
    chunks = list(chunker.chunk_text("x=1\n", language="python",
                                      file_path="x.py", budget_bytes=1500))
    assert all(c.kind == "window" for c in chunks)
    assert all(c.ast_path is None for c in chunks)
    assert all(c.name is None for c in chunks)


def test_language_detection_from_extension():
    assert chunker.detect_language(Path("foo.py")) == "python"
    assert chunker.detect_language(Path("foo.js")) == "javascript"
    assert chunker.detect_language(Path("foo.ts")) == "typescript"
    assert chunker.detect_language(Path("foo.tsx")) == "tsx"
    assert chunker.detect_language(Path("foo.go")) == "go"
    assert chunker.detect_language(Path("foo.rs")) == "rust"
    assert chunker.detect_language(Path("foo.java")) == "java"
    assert chunker.detect_language(Path("README.md")) == "markdown"
    assert chunker.detect_language(Path("Makefile")) == "makefile"
    assert chunker.detect_language(Path("script.sh")) == "bash"
    assert chunker.detect_language(Path("foo.unknown")) == "text"


def test_token_count_is_whitespace_split_estimate():
    chunks = list(chunker.chunk_text("hello world\nfoo bar baz\n",
                                      language="text",
                                      file_path="x.txt", budget_bytes=1500))
    assert chunks[0].token_count == 5


def test_empty_file_yields_no_chunks():
    chunks = list(chunker.chunk_text("", language="python",
                                      file_path="x.py", budget_bytes=1500))
    assert chunks == []


def test_chunk_file_reads_from_disk(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("a=1\nb=2\n", encoding="utf-8")
    chunks = list(chunker.chunk_file(p, budget_bytes=1500))
    assert len(chunks) == 1
    assert chunks[0].file_path == str(p)
    assert chunks[0].language == "python"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_chunker.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scripts/cbv/chunker.py**

Create `scripts/cbv/chunker.py`:

```python
"""Line-aware text-window chunker for Slice 1.

Chunks are non-overlapping; concatenating them in order reproduces the
file verbatim. A single line that exceeds the byte budget becomes its
own over-budget chunk (preserves the concat invariant).

Slice 2 swaps this for tree-sitter + cAST chunking; the Chunk dataclass
stays the same so downstream consumers don't change.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional


EXTENSION_LANGUAGE = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript", ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".rb": "ruby",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala",
    ".php": "php",
    ".lua": "lua",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss",
    ".vue": "vue",
    ".md": "markdown", ".markdown": "markdown",
    ".rst": "rst",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
}

SPECIAL_FILENAMES = {
    "Makefile": "makefile", "makefile": "makefile",
    "Dockerfile": "dockerfile",
    "BUILD": "bazel", "WORKSPACE": "bazel",
}


@dataclass(frozen=True)
class Chunk:
    file_path: str
    language: str
    kind: str
    name: Optional[str]
    ast_path: Optional[str]
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    content: str
    content_hash: str
    token_count: int


def detect_language(path: Path) -> str:
    name = path.name
    if name in SPECIAL_FILENAMES:
        return SPECIAL_FILENAMES[name]
    return EXTENSION_LANGUAGE.get(path.suffix.lower(), "text")


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _token_count(s: str) -> int:
    return len(s.split())


def chunk_text(
    content: str,
    *,
    language: str,
    file_path: str,
    budget_bytes: int = 1500,
) -> Iterator[Chunk]:
    """Yield non-overlapping line-aware chunks under budget_bytes.

    Empty content yields no chunks. A single line longer than the budget
    becomes its own over-budget chunk (preserves concat == file).
    """
    if not content:
        return
    # Use splitlines(keepends=True) so newlines stay with their lines.
    lines = content.splitlines(keepends=True)
    # Precompute byte offsets per line (UTF-8 byte counts).
    encoded = [line.encode("utf-8") for line in lines]
    line_byte_lens = [len(e) for e in encoded]
    line_start_bytes = [0]
    for n in line_byte_lens:
        line_start_bytes.append(line_start_bytes[-1] + n)

    cur_lines: list[int] = []   # line indices in current chunk
    cur_bytes = 0

    def emit() -> Chunk:
        first = cur_lines[0]
        last = cur_lines[-1]
        text = "".join(lines[first:last + 1])
        return Chunk(
            file_path=file_path,
            language=language,
            kind="window",
            name=None,
            ast_path=None,
            start_line=first + 1,
            end_line=last + 1,
            start_byte=line_start_bytes[first],
            end_byte=line_start_bytes[last + 1],
            content=text,
            content_hash=_sha256_hex(text),
            token_count=_token_count(text),
        )

    for i, n in enumerate(line_byte_lens):
        # Case 1: single line exceeds budget — emit current (if any), then
        # emit this line as its own over-budget chunk.
        if n > budget_bytes:
            if cur_lines:
                yield emit()
                cur_lines = []
                cur_bytes = 0
            cur_lines = [i]
            cur_bytes = n
            yield emit()
            cur_lines = []
            cur_bytes = 0
            continue
        # Case 2: would overflow — emit current, start new.
        if cur_bytes + n > budget_bytes and cur_lines:
            yield emit()
            cur_lines = []
            cur_bytes = 0
        cur_lines.append(i)
        cur_bytes += n

    if cur_lines:
        yield emit()


def chunk_file(path: Path, *, budget_bytes: int = 1500) -> Iterator[Chunk]:
    """Read a file and yield chunks. UTF-8 with surrogateescape fallback."""
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="surrogateescape")
    yield from chunk_text(
        content,
        language=detect_language(path),
        file_path=str(path),
        budget_bytes=budget_bytes,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_chunker.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/chunker.py tests/unit/test_chunker.py
git commit -m "slice 1 t7: cbv.chunker — line-aware text-window chunks (cAST in slice 2)"
```

---

### Task 8: scripts/cbv/quantize.py — INT8 quantize / dequantize for vec_chunks

`sqlite-vec`'s `INT8[1536]` storage holds 8-bit signed integers. Float embeddings are L2-normalized, scaled by 127, clipped to `[-128, 127]`, and cast to `int8`. Dequantization reverses by dividing by 127 (and re-normalizing if needed).

**Files:**
- Create: `scripts/cbv/quantize.py`
- Create: `tests/unit/test_quantize.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_quantize.py`:

```python
"""Tests for cbv.quantize — INT8 quant/dequant for sqlite-vec storage."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import numpy as np

from cbv import quantize  # noqa: E402


def test_quantize_returns_int8_with_same_shape():
    x = np.random.default_rng(0).standard_normal((3, 1536)).astype(np.float32)
    q = quantize.quantize_int8(x)
    assert q.dtype == np.int8
    assert q.shape == (3, 1536)


def test_quantize_bounds():
    x = np.random.default_rng(0).standard_normal((1, 1536)).astype(np.float32) * 1000
    q = quantize.quantize_int8(x)
    assert q.min() >= -128
    assert q.max() <= 127


def test_quantize_normalizes_first():
    """Two inputs that differ only in magnitude quantize identically (up to rounding)."""
    base = np.random.default_rng(1).standard_normal((1, 1536)).astype(np.float32)
    q1 = quantize.quantize_int8(base)
    q2 = quantize.quantize_int8(base * 5.0)
    # Allow small differences from rounding at the boundary, but most must agree.
    agree = (q1 == q2).sum()
    assert agree >= int(q1.size * 0.99), f"only {agree}/{q1.size} agree"


def test_quantize_to_bytes_for_sqlite_vec():
    x = np.ones((1, 1536), dtype=np.float32)
    b = quantize.quantize_int8_bytes(x)
    assert isinstance(b, bytes)
    assert len(b) == 1536


def test_dequantize_is_approximate_inverse():
    rng = np.random.default_rng(42)
    x = rng.standard_normal((2, 1536)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)  # already-normalized
    q = quantize.quantize_int8(x)
    back = quantize.dequantize_int8(q)
    # Cosine similarity between original and dequantized should be very high.
    sim = (x * back).sum(axis=1) / (
        np.linalg.norm(x, axis=1) * np.linalg.norm(back, axis=1)
    )
    assert (sim > 0.999).all(), f"min sim = {sim.min()}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_quantize.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scripts/cbv/quantize.py**

Create `scripts/cbv/quantize.py`:

```python
"""INT8 quantization for sqlite-vec INT8[1536] columns.

Quantization steps:
  1. L2-normalize each row (so all vectors live on the unit sphere).
  2. Scale by 127 and round.
  3. Clip to [-128, 127] and cast to int8.

Dequantization divides by 127 and (optionally) re-normalizes. The
roundtrip cosine similarity to the original normalized vector stays
above 0.999 for 1536-d random vectors, which is acceptable for retrieval.
"""
from __future__ import annotations

import numpy as np


def _l2_normalize(x: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(x, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1.0, norm)
    return x / norm


def quantize_int8(x: np.ndarray) -> np.ndarray:
    """Return INT8 of shape matching x; L2-normalizes before scaling."""
    if x.dtype != np.float32:
        x = x.astype(np.float32, copy=False)
    normed = _l2_normalize(x)
    scaled = np.round(normed * 127.0)
    clipped = np.clip(scaled, -128, 127)
    return clipped.astype(np.int8)


def quantize_int8_bytes(x: np.ndarray) -> bytes:
    """Quantize a single 1-D embedding (or first row of a 2-D batch) to bytes
    suitable for sqlite-vec INT8 column insertion."""
    q = quantize_int8(x.reshape(1, -1) if x.ndim == 1 else x[:1])
    return q.tobytes()


def dequantize_int8(q: np.ndarray) -> np.ndarray:
    """Approximate inverse of quantize_int8 — divides by 127, returns float32."""
    return q.astype(np.float32) / 127.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_quantize.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/quantize.py tests/unit/test_quantize.py
git commit -m "slice 1 t8: cbv.quantize — INT8 quant/dequant for sqlite-vec"
```

---

### Task 9: scripts/cbv/embedder.py — jina-code-embeddings-1.5b with runtime CPU/GPU select

The embedder module exposes an `Embedder` ABC with `embed(texts) -> np.ndarray[N, 1536]`. Concrete implementations:

- `JinaCodeGPUEmbedder` — `transformers` + `torch.float16` on CUDA, batch 32. Selected when `torch.cuda.is_available()` is True (and not overridden).
- `JinaCodeCPUEmbedder` — `llama-cpp-python` with GGUF INT4, batch 8. Selected otherwise. The GGUF file is downloaded via `huggingface_hub.hf_hub_download` on first use; the repo and filename are env-configurable.
- `StubEmbedder` — deterministic SHA-256-derived fake embeddings. Selected when `CBV_STUB_EMBEDDER=1` is set. Used by integration tests to avoid the model download on CI.

The factory `make_embedder()` returns the right implementation. Integration tests inject the stub by setting the env var.

**Files:**
- Create: `scripts/cbv/embedder.py`
- Create: `tests/unit/test_embedder.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_embedder.py`:

```python
"""Tests for cbv.embedder.

Slice 1 only covers the stub embedder behavior and the factory. The
real Jina embedder is exercised by the integration test (which skips
in stub mode by default) and by manual smoke runs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import numpy as np

from cbv import embedder  # noqa: E402


def test_stub_embedder_shape_and_dtype():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed(["hello", "world", "foo bar"])
    assert out.shape == (3, 1536)
    assert out.dtype == np.float32


def test_stub_embedder_deterministic():
    e = embedder.StubEmbedder(dim=1536)
    a = e.embed(["same text"])
    b = e.embed(["same text"])
    assert np.array_equal(a, b)


def test_stub_embedder_distinguishes_inputs():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed(["alpha", "beta"])
    # Different inputs produce different embeddings.
    assert not np.array_equal(out[0], out[1])


def test_stub_embedder_normalized():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed(["x", "yy", "zzz"])
    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, np.ones(3), atol=1e-5)


def test_factory_returns_stub_when_env_set(monkeypatch):
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    e = embedder.make_embedder()
    assert isinstance(e, embedder.StubEmbedder)


def test_factory_default_dim_matches_v1_schema(monkeypatch):
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    e = embedder.make_embedder()
    assert e.dim == 1536
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_embedder.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement scripts/cbv/embedder.py**

Create `scripts/cbv/embedder.py`:

```python
"""Embedder for codebase-vectorizer v1.0 (Slice 1).

Default model: `jinaai/jina-code-embeddings-1.5b` — 1.5B-param encoder,
1536-dim output. Runtime selection:

  - GPU path: transformers + torch.float16, batch 32
  - CPU path: llama-cpp-python + GGUF INT4, batch 8
  - Stub path: deterministic SHA-256 hash-derived embeddings (tests)

The factory `make_embedder()` reads CBV_STUB_EMBEDDER first (tests),
then auto-detects CUDA via torch. To force the CPU path on a CUDA box
set CBV_FORCE_CPU=1.

The GGUF repo and filename are env-configurable:
  CBV_GGUF_REPO   default 'jinaai/jina-code-embeddings-1.5b-GGUF'
  CBV_GGUF_FILE   default 'jina-code-embeddings-1.5b.Q4_K_M.gguf'

Slice 2 adds tree-sitter chunking; the embedder itself doesn't change.
Slice 5 adds the cross-encoder reranker (separate module).
"""
from __future__ import annotations

import abc
import hashlib
import os
from typing import List

import numpy as np

DEFAULT_DIM = 1536
DEFAULT_MODEL_ID = "jinaai/jina-code-embeddings-1.5b"


class Embedder(abc.ABC):
    """Embedder interface. All implementations return L2-normalized float32."""

    model_id: str = DEFAULT_MODEL_ID
    dim: int = DEFAULT_DIM

    @abc.abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        """Return an (N, dim) float32 array. Rows are L2-normalized."""


class StubEmbedder(Embedder):
    """Deterministic, hash-based embedder for tests.

    Distinct inputs yield distinct outputs; identical inputs yield identical
    outputs. Outputs are L2-normalized. This is sufficient for testing the
    indexing/retrieval pipeline without downloading the real model.
    """
    model_id = "stub://sha256"

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self.dim = dim

    def embed(self, texts: List[str]) -> np.ndarray:
        rows = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            rows.append(v)
        return np.stack(rows, axis=0) if rows else np.zeros((0, self.dim), dtype=np.float32)


class JinaCodeGPUEmbedder(Embedder):
    """transformers + torch.float16 on CUDA."""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, batch_size: int = 32) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.model_id = model_id
        self.batch_size = batch_size
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(
            model_id, torch_dtype=torch.float16
        ).eval().to("cuda")
        self.dim = self.model.config.hidden_size

    def embed(self, texts: List[str]) -> np.ndarray:
        import torch
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            enc = self.tokenizer(
                batch, padding=True, truncation=True, max_length=512,
                return_tensors="pt",
            ).to("cuda")
            with torch.inference_mode():
                hidden = self.model(**enc).last_hidden_state
                # Mean-pool over non-padding tokens.
                mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(pooled.float().cpu().numpy())
        return np.concatenate(out, axis=0) if out else np.zeros((0, self.dim), dtype=np.float32)


class JinaCodeCPUEmbedder(Embedder):
    """llama-cpp-python with GGUF INT4."""

    def __init__(
        self,
        gguf_repo: str | None = None,
        gguf_file: str | None = None,
        batch_size: int = 8,
    ) -> None:
        from llama_cpp import Llama
        from huggingface_hub import hf_hub_download

        repo = gguf_repo or os.environ.get(
            "CBV_GGUF_REPO", "jinaai/jina-code-embeddings-1.5b-GGUF"
        )
        fname = gguf_file or os.environ.get(
            "CBV_GGUF_FILE", "jina-code-embeddings-1.5b.Q4_K_M.gguf"
        )
        path = hf_hub_download(repo_id=repo, filename=fname)
        self.model_id = f"{repo}/{fname}"
        self.batch_size = batch_size
        self.llm = Llama(
            model_path=path,
            embedding=True,
            n_ctx=512,
            n_threads=os.cpu_count() or 4,
            verbose=False,
        )
        self.dim = DEFAULT_DIM

    def embed(self, texts: List[str]) -> np.ndarray:
        out_rows = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            for t in batch:
                # llama-cpp's create_embedding returns one row per input.
                r = self.llm.create_embedding(t)
                vec = np.array(r["data"][0]["embedding"], dtype=np.float32)
                norm = np.linalg.norm(vec) or 1.0
                out_rows.append(vec / norm)
        if not out_rows:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out_rows, axis=0)


def make_embedder() -> Embedder:
    """Factory honoring CBV_STUB_EMBEDDER then CBV_FORCE_CPU then auto-detect."""
    if os.environ.get("CBV_STUB_EMBEDDER") == "1":
        return StubEmbedder()

    if os.environ.get("CBV_FORCE_CPU") == "1":
        return JinaCodeCPUEmbedder()

    try:
        import torch
        if torch.cuda.is_available():
            return JinaCodeGPUEmbedder()
    except ImportError:
        pass

    return JinaCodeCPUEmbedder()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_embedder.py -v`
Expected: all stub-embedder tests pass. The real Jina embedders are not invoked by unit tests.

- [ ] **Step 5: (Optional) Manual smoke test of the real embedder**

This step is gated on developer choice; not required to land Slice 1's CI green. To verify the real model works end-to-end:

Run (PowerShell, inside the plugin venv):
```powershell
& "$env:CODEBASE_VECTORIZER_HOME\python-env\Scripts\python.exe" -c @"
import sys, os
sys.path.insert(0, r'$(Resolve-Path scripts)')
from cbv.embedder import make_embedder
e = make_embedder()
out = e.embed(['def foo(x): return x + 1'])
print('shape:', out.shape, 'dim:', e.dim, 'model:', e.model_id)
"@
```

Expected: prints `shape: (1, 1536) dim: 1536 model: ...jina-code-embeddings-1.5b...`. The first run downloads ~750 MB of GGUF and may take several minutes.

If `huggingface_hub` raises `EntryNotFoundError` because the default GGUF doesn't exist at the configured repo/filename, set `CBV_GGUF_REPO` and `CBV_GGUF_FILE` to a known-good GGUF (e.g., search HuggingFace for a community quant) and re-run. This is a known integration risk called out in the spec — record the working repo/file pair in `scripts/cbv/embedder.py`'s docstring once verified.

- [ ] **Step 6: Commit**

```bash
git add scripts/cbv/embedder.py tests/unit/test_embedder.py
git commit -m "slice 1 t9: cbv.embedder — jina-code-1.5b w/ CPU/GPU/stub factory"
```

---

### Task 10: scripts/cbv/commands/vectorize.py — full indexing orchestration

Compose the modules built so far into the indexing pipeline:

1. resolve `source` (URL or local) into `<repo_dir>/source/`
2. walk the source tree
3. chunk each file
4. embed all chunks in batches
5. write chunks → `chunks`, FTS rows are auto-synced via triggers, embeddings → `vec_chunks`
6. write `meta` keys per the spec
7. write `manifest.json` with the file inventory + indexing stats + warnings
8. print the v1.0 JSON summary

**Files:**
- Replace stub: `scripts/cbv/commands/vectorize.py`
- Create: `tests/unit/test_vectorize_cmd.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vectorize_cmd.py`:

```python
"""Tests for cbv.commands.vectorize — exercises the full pipeline with the
StubEmbedder and a tmp source tree."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import paths  # noqa: E402
from cbv.commands import vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    yield tmp_path


@pytest.fixture
def source_repo(tmp_home):
    src = tmp_home / "upstream"
    src.mkdir()
    (src / "main.py").write_text("def main():\n    print('hello')\n")
    (src / "lib.py").write_text("def helper(x):\n    return x * 2\n")
    (src / "README.md").write_text("# upstream\n\nThis is a test repo.\n")
    return src


def test_vectorize_creates_index_sqlite(tmp_home, source_repo, capsys):
    ns = argparse.Namespace(
        source=str(source_repo), output_dir=None, max_file_mb=1.5,
    )
    rc = vec_cmd.run(ns)
    assert rc == 0
    repo_dir = paths.repo_dir("upstream")
    assert (repo_dir / "index.sqlite").exists()
    assert (repo_dir / "manifest.json").exists()
    assert (repo_dir / "source" / "main.py").exists()


def test_vectorize_populates_chunks(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    db_path = paths.repo_dir("upstream") / "index.sqlite"
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert n >= 3  # at least one chunk per file


def test_vectorize_populates_vec_chunks(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    db_path = paths.repo_dir("upstream") / "index.sqlite"
    # Use cbv.db.open_db so sqlite-vec is loaded.
    from cbv import db
    conn = db.open_db(db_path)
    chunks_n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    vec_n = conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    assert vec_n == chunks_n


def test_vectorize_populates_fts(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    rows = conn.execute(
        "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'helper'"
    ).fetchone()[0]
    assert rows >= 1


def test_vectorize_writes_meta(tmp_home, source_repo):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    from cbv import db
    conn = db.open_db(paths.repo_dir("upstream") / "index.sqlite")
    assert db.read_meta(conn, "schema_version") == "1.0"
    assert db.read_meta(conn, "embedder_dim") == "1536"
    assert db.read_meta(conn, "embedder_model") == "stub://sha256"
    assert db.read_meta(conn, "embedder_quant") == "int8"
    assert int(db.read_meta(conn, "total_chunks")) >= 3
    # Future-slice keys must exist with zero/empty sentinels.
    assert db.read_meta(conn, "total_nodes_symbol") == "0"
    assert db.read_meta(conn, "total_edges_symbol") == "0"
    assert db.read_meta(conn, "total_clusters") == "0"
    assert db.read_meta(conn, "reranker_model") == ""


def test_vectorize_prints_v1_summary_json(tmp_home, source_repo, capsys):
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vec_cmd.run(ns)
    out = capsys.readouterr().out
    # The last non-empty line is the JSON blob.
    line = [l for l in out.strip().splitlines() if l.strip()][-1]
    blob = json.loads(line)
    assert blob["repo_name"] == "upstream"
    assert blob["files_indexed"] >= 3
    assert blob["chunks_indexed"] >= 3
    # Slice 1 placeholders.
    assert blob["nodes_symbol"] == 0
    assert blob["nodes_block"] == 0
    assert blob["edges_symbol"] == 0
    assert blob["edges_flow"] == 0
    assert blob["clusters_indexed"] == 0
    assert "warnings" in blob and isinstance(blob["warnings"], list)
    assert "elapsed_seconds" in blob
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv_python> -m pytest tests/unit/test_vectorize_cmd.py -v`
Expected: FAIL — `vec_cmd.run()` still raises `NotImplementedError` from the Task 3 stub.

- [ ] **Step 3: Implement scripts/cbv/commands/vectorize.py**

Replace `scripts/cbv/commands/vectorize.py` with:

```python
"""`vectorize` verb — index a repo into <data_home>/repos/<name>/.

Slice 1 pipeline:
  1. resolve source (URL → git clone --depth 1; local → recursive copy)
  2. open <repo_dir>/index.sqlite and init the full v1.0 schema
  3. walk source/ honoring gitignore/size/binary filters
  4. chunk each file (line-aware text windows; tree-sitter+cAST lands in Slice 2)
  5. embed every chunk via the configured embedder
  6. write chunks (FTS5 trigger syncs) + INT8 quantized embeddings (vec_chunks)
  7. write meta keys and manifest.json
  8. print v1.0 summary JSON to stdout
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import List

from cbv import chunker, db, embedder, paths, quantize, source, walker

BATCH_SIZE = 32


def run(ns: argparse.Namespace) -> int:
    t_start = time.time()
    spec = ns.source
    repo_name = source.derive_repo_name(spec)
    repo_dir = paths.repo_dir(repo_name) if not ns.output_dir else Path(ns.output_dir).expanduser().resolve()
    src_dir = repo_dir / "source"
    repo_dir.mkdir(parents=True, exist_ok=True)

    print(f"[vectorize] target: {repo_dir}", flush=True)

    # Step 1: resolve source.
    if source.is_git_url(spec):
        commit_sha = source.populate_from_url(spec, src_dir)
    else:
        commit_sha = source.populate_from_local(Path(spec), src_dir)

    # Step 2: open db, init schema.
    db_path = repo_dir / "index.sqlite"
    if db_path.exists():
        db_path.unlink()  # fresh index every run in Slice 1; incremental in Slice 12
    conn = db.open_db(db_path)
    db.init_schema(conn)

    # Step 3+4: walk and chunk.
    chunks_buf: list[chunker.Chunk] = []
    file_count = 0
    warnings: list[str] = []
    for entry in walker.walk(src_dir, max_file_mb=ns.max_file_mb):
        file_count += 1
        try:
            file_chunks = list(chunker.chunk_file(entry.abspath))
        except Exception as e:  # broad: per-file failure must not kill the run
            warnings.append(f"chunk failed for {entry.relpath}: {e}")
            continue
        # rewrite file_path to be repo-relative for storage
        for c in file_chunks:
            chunks_buf.append(chunker.Chunk(
                file_path=entry.relpath.as_posix(),
                language=c.language, kind=c.kind, name=c.name,
                ast_path=c.ast_path, start_line=c.start_line,
                end_line=c.end_line, start_byte=c.start_byte,
                end_byte=c.end_byte, content=c.content,
                content_hash=c.content_hash, token_count=c.token_count,
            ))

    print(f"[vectorize] {file_count} files → {len(chunks_buf)} chunks", flush=True)

    # Step 5: embed.
    emb = embedder.make_embedder()
    print(f"[vectorize] embedder: {emb.model_id}", flush=True)
    embeddings = _embed_in_batches(emb, [c.content for c in chunks_buf], BATCH_SIZE)

    # Step 6: write chunks + embeddings.
    with conn:
        for c in chunks_buf:
            conn.execute(
                "INSERT INTO chunks (file_path, language, kind, name, ast_path, "
                "start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (c.file_path, c.language, c.kind, c.name, c.ast_path,
                 c.start_line, c.end_line, c.start_byte, c.end_byte,
                 c.content, c.content_hash, c.token_count),
            )
        ids = [row[0] for row in conn.execute("SELECT id FROM chunks ORDER BY id").fetchall()]
        assert len(ids) == len(chunks_buf)
        for chunk_id, emb_row in zip(ids, embeddings):
            q = quantize.quantize_int8(emb_row.reshape(1, -1))
            conn.execute(
                "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, q.tobytes()),
            )

    # Step 7: meta + manifest.
    _write_meta(conn, repo_name, spec, commit_sha, emb, len(chunks_buf))
    manifest = _build_manifest(repo_name, spec, src_dir, repo_dir, db_path,
                                file_count, len(chunks_buf), warnings)
    (repo_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    conn.close()

    # Step 8: emit v1.0 summary JSON on stdout (last line).
    elapsed = time.time() - t_start
    summary = {
        "repo_name": repo_name,
        "source_dir": str(src_dir),
        "db_path": str(db_path),
        "manifest_path": str(repo_dir / "manifest.json"),
        "files_indexed": file_count,
        "chunks_indexed": len(chunks_buf),
        "nodes_symbol": 0,      # Slice 3
        "nodes_block": 0,       # Slice 9
        "edges_symbol": 0,      # Slice 3
        "edges_flow": 0,        # Slices 9-10
        "clusters_indexed": 0,  # Slice 7
        "elapsed_seconds": round(elapsed, 2),
        "embedding_cache_hit_rate": 0.0,   # Slice 11
        "warnings": warnings,
        "bench_results": {},               # Slice 14
    }
    print(json.dumps(summary), flush=True)
    return 0


def _embed_in_batches(emb: embedder.Embedder, texts: List[str], batch: int):
    if not texts:
        import numpy as np
        return np.zeros((0, emb.dim), dtype="float32")
    rows = []
    for i in range(0, len(texts), batch):
        rows.append(emb.embed(texts[i:i + batch]))
    import numpy as np
    return np.concatenate(rows, axis=0)


def _write_meta(conn, repo_name, repo_origin, commit_sha, emb, total_chunks):
    db.write_meta(conn, "schema_version", "1.0")
    db.write_meta(conn, "indexed_at", str(int(time.time())))
    db.write_meta(conn, "repo_origin", repo_origin)
    db.write_meta(conn, "commit_sha", commit_sha or "")
    db.write_meta(conn, "embedder_model", emb.model_id)
    db.write_meta(conn, "embedder_dim", str(emb.dim))
    db.write_meta(conn, "embedder_quant", "int8")
    # Sentinels for future slices (so meta always has the full required key set).
    db.write_meta(conn, "reranker_model", "")
    db.write_meta(conn, "total_chunks", str(total_chunks))
    db.write_meta(conn, "total_nodes_symbol", "0")
    db.write_meta(conn, "total_nodes_block", "0")
    db.write_meta(conn, "total_edges_symbol", "0")
    db.write_meta(conn, "total_edges_flow", "0")
    db.write_meta(conn, "total_clusters", "0")
    db.write_meta(conn, "merkle_root_sha", "")


def _build_manifest(repo_name, repo_origin, src_dir, repo_dir, db_path,
                     files_indexed, chunks_indexed, warnings):
    return {
        "repo_name": repo_name,
        "repo_origin": repo_origin,
        "source_dir": str(src_dir),
        "repo_dir": str(repo_dir),
        "db_path": str(db_path),
        "files_indexed": files_indexed,
        "chunks_indexed": chunks_indexed,
        "warnings": warnings,
        "schema_version": "1.0",
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv_python> -m pytest tests/unit/test_vectorize_cmd.py -v`
Expected: all tests pass. The first run also doubles as proof that:
- the schema is created end-to-end,
- the FTS triggers fire,
- the INT8 vec_chunks insert succeeds,
- meta has every required key.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/commands/vectorize.py tests/unit/test_vectorize_cmd.py
git commit -m "slice 1 t10: cbv.commands.vectorize — full indexing pipeline orchestration"
```

---

### Task 11: scripts/cbv/commands/query.py — BM25 + dense + RRF query

Implement the full-lane retrieval minus rerank/graph/clusters (those land in later slices). The query is embedded, BM25 and dense searches run sequentially, RRF fuses the two ranked lists, and the top-k hits are returned in v1.0 JSON shape.

The query command also enforces the legacy-schema check from Task 4 — pointing at a v0.3.0 index emits the spec-mandated error.

**Files:**
- Replace stub: `scripts/cbv/commands/query.py`
- Create: `tests/unit/test_query_cmd.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_query_cmd.py`:

```python
"""Tests for cbv.commands.query — BM25 + dense + RRF, plus legacy detector."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import paths  # noqa: E402
from cbv.commands import query as query_cmd, vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def indexed_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "auth.py").write_text(
        "def authenticate_user(username, password):\n"
        "    return check_credentials(username, password)\n"
    )
    (src / "router.py").write_text(
        "def route_request(req):\n"
        "    if req.path.startswith('/api'):\n"
        "        return api_handler(req)\n"
        "    return static_handler(req)\n"
    )
    (src / "db.py").write_text(
        "def query_user(uid):\n"
        "    return fetch('SELECT * FROM users WHERE id = ?', uid)\n"
    )
    ns = argparse.Namespace(source=str(src), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "upstream"


def test_query_returns_v1_shape(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="authenticate user", top_k=3)
    rc = query_cmd.run(ns)
    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["repo"] == indexed_repo
    assert blob["query"] == "authenticate user"
    assert blob["pipeline_used"] == "full"   # Slice 1 only has the full lane
    assert "results" in blob and isinstance(blob["results"], list)
    assert "refined_queries" in blob   # always present, empty list in Slice 1
    assert blob["expansion_size"] == 0  # graph expansion lands in Slice 3


def test_query_results_have_required_fields(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="authenticate user", top_k=3)
    query_cmd.run(ns)
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["results"], "expected at least one result"
    r = blob["results"][0]
    for k in ("rank", "file_absolute", "file_relative", "start_line",
              "end_line", "kind", "score", "preview", "why_this_was_returned"):
        assert k in r, f"missing key {k!r}"


def test_query_top_k_caps_result_count(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="route request handler", top_k=1)
    query_cmd.run(ns)
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert len(blob["results"]) <= 1


def test_query_missing_repo_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "empty_home"))
    ns = argparse.Namespace(repo="nonexistent", question="anything", top_k=3)
    rc = query_cmd.run(ns)
    assert rc != 0
    err = capsys.readouterr().err
    assert "No index found" in err
    assert "nonexistent" in err


def test_query_legacy_schema_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    # Create a fake v0.3.0-shaped index: chunks table, no meta.
    legacy_dir = tmp_path / "home" / "repos" / "oldrepo"
    legacy_dir.mkdir(parents=True)
    db_path = legacy_dir / "index.sqlite"
    raw = sqlite3.connect(db_path)
    raw.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    raw.commit()
    raw.close()

    ns = argparse.Namespace(repo="oldrepo", question="x", top_k=3)
    rc = query_cmd.run(ns)
    assert rc != 0
    err = capsys.readouterr().err
    assert "older codebase-vectorizer index" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv_python> -m pytest tests/unit/test_query_cmd.py -v`
Expected: FAIL — `query_cmd.run()` still raises `NotImplementedError`.

- [ ] **Step 3: Implement scripts/cbv/commands/query.py**

Replace `scripts/cbv/commands/query.py` with:

```python
"""`query` verb — BM25 + dense + RRF retrieval.

Slice 1 implements only the spec's "full lane" minus rerank/graph/clusters:
  Stage 1 (parallel seed in spec; sequential here):
    - BM25 top-50 over chunks_fts
    - dense top-50 over vec_chunks
  Stage 2:
    - Reciprocal Rank Fusion (k=60 constant per RRF paper) of the two lists
  Stage 3-6: deferred to later slices.

Slices that extend this command:
  Slice 3 — graph expansion + symbol-exact seed
  Slice 4 — fast lane + query router
  Slice 5 — cross-encoder rerank
  Slice 6 — Personalized PageRank
  Slice 15 — confidence + refined_queries hints
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np

from cbv import db, embedder, paths, quantize

RRF_K = 60  # standard RRF damping constant


def run(ns: argparse.Namespace) -> int:
    repo_dir = paths.find_repo(ns.repo)
    if repo_dir is None:
        print(
            f"No index found for repo {ns.repo!r}. "
            f"Run `run.sh list` to see available indexes, or `run.sh "
            f"vectorize <url|path>` to create one.",
            file=sys.stderr,
        )
        return 2

    db_path = repo_dir / "index.sqlite"
    conn = db.open_db(db_path)
    try:
        db.assert_schema_v1(conn)
    except db.LegacySchemaError as e:
        print(str(e), file=sys.stderr)
        return 2

    # Stage 1a: BM25.
    bm25_hits = _bm25(conn, ns.question, limit=50)

    # Stage 1b: dense.
    emb = embedder.make_embedder()
    qv = emb.embed([ns.question])[0]
    qbytes = quantize.quantize_int8(qv.reshape(1, -1)).tobytes()
    dense_hits = _dense(conn, qbytes, limit=50)

    # Stage 2: RRF fuse.
    fused = _rrf([bm25_hits, dense_hits], k=RRF_K)
    top = fused[: ns.top_k]

    # Materialize result rows.
    results = []
    for rank, (chunk_id, score, sources) in enumerate(top, start=1):
        row = conn.execute(
            "SELECT file_path, kind, name, start_line, end_line, content "
            "FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            continue
        file_rel, kind, name, sl, el, content = row
        file_abs = (repo_dir / "source" / file_rel).resolve()
        results.append({
            "rank": rank,
            "file_absolute": str(file_abs),
            "file_relative": file_rel,
            "start_line": sl,
            "end_line": el,
            "kind": kind,
            "name": name,
            "score": round(float(score), 4),
            "preview": (content[:200] + "…") if len(content) > 200 else content,
            "why_this_was_returned": "+".join(sorted(sources)),
        })

    blob = {
        "repo": ns.repo,
        "query": ns.question,
        "repo_dir": str(repo_dir),
        "pipeline_used": "full",
        "results": results,
        "refined_queries": [],   # Slice 15
        "expansion_size": 0,      # Slice 3
    }
    print(json.dumps(blob), flush=True)
    conn.close()
    return 0


def _bm25(conn, query: str, *, limit: int) -> Dict[int, float]:
    """Return {chunk_id: bm25 rank-score} for top BM25 hits."""
    rows = conn.execute(
        "SELECT rowid, bm25(chunks_fts) FROM chunks_fts "
        "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
        (_fts_escape(query), limit),
    ).fetchall()
    return {int(r[0]): float(r[1]) for r in rows}


def _fts_escape(query: str) -> str:
    """Wrap each whitespace-split token in double quotes so FTS5 treats them as
    literal terms (no syntax injection through user input)."""
    parts = [p for p in query.split() if p]
    if not parts:
        return '""'
    quoted = ['"' + p.replace('"', '""') + '"' for p in parts]
    return " OR ".join(quoted)


def _dense(conn, query_bytes: bytes, *, limit: int) -> Dict[int, float]:
    """Return {chunk_id: -distance} for top sqlite-vec KNN hits.

    We invert distance so that 'higher is better' is consistent with bm25
    where smaller bm25 = better (we sort ascending in BM25). The RRF
    fuse below normalizes via rank ordering, so absolute scales don't matter.
    """
    rows = conn.execute(
        "SELECT chunk_id, distance FROM vec_chunks "
        "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (query_bytes, limit),
    ).fetchall()
    return {int(r[0]): -float(r[1]) for r in rows}


def _rrf(rankings: List[Dict[int, float]], *, k: int) -> List[tuple]:
    """Reciprocal Rank Fusion. Sources is a tag list per chunk for debug."""
    SOURCE_NAMES = ["bm25", "dense"]
    aggregate: Dict[int, float] = {}
    sources: Dict[int, list] = {}
    for tag, ranking in zip(SOURCE_NAMES, rankings):
        # Order: BM25 ascending (smaller is better); dense was inverted to "higher is better".
        # Normalize to ascending best-first by sorting:
        if tag == "bm25":
            sorted_ids = [cid for cid, _ in sorted(ranking.items(), key=lambda kv: kv[1])]
        else:
            sorted_ids = [cid for cid, _ in sorted(ranking.items(), key=lambda kv: -kv[1])]
        for rank, cid in enumerate(sorted_ids, start=1):
            aggregate[cid] = aggregate.get(cid, 0.0) + 1.0 / (k + rank)
            sources.setdefault(cid, []).append(tag)
    fused = sorted(
        ((cid, score, sources[cid]) for cid, score in aggregate.items()),
        key=lambda t: -t[1],
    )
    return fused
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv_python> -m pytest tests/unit/test_query_cmd.py -v`
Expected: all tests pass — including the missing-repo and legacy-schema error tests.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/commands/query.py tests/unit/test_query_cmd.py
git commit -m "slice 1 t11: cbv.commands.query — BM25 + dense + RRF (no rerank/graph yet)"
```

---

### Task 12: scripts/cbv/commands/list_cmd.py + info.py

Implement the two trivial verbs. Both read paths.py and print human-readable output (not JSON — they're for humans, the skills don't parse them).

**Files:**
- Replace stub: `scripts/cbv/commands/list_cmd.py`
- Replace stub: `scripts/cbv/commands/info.py`
- Create: `tests/unit/test_list_info_cmd.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_list_info_cmd.py`:

```python
"""Tests for cbv.commands.list_cmd and cbv.commands.info."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv.commands import list_cmd, info as info_cmd  # noqa: E402


@pytest.fixture
def home_with_repos(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repos = tmp_path / "home" / "repos"
    for name in ("alpha", "beta"):
        (repos / name).mkdir(parents=True)
        (repos / name / "index.sqlite").write_bytes(b"")
    return repos


def test_list_prints_repo_names(home_with_repos, capsys):
    rc = list_cmd.run(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


def test_list_handles_empty(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "empty"))
    rc = list_cmd.run(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "No indexed repos" in out


def test_info_prints_paths(home_with_repos, capsys):
    rc = info_cmd.run(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    for k in ("data_home:", "python_env:", "repos_dir:", "indexed_repos:"):
        assert k in out
    assert "alpha" in out
    assert "beta" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_list_info_cmd.py -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement scripts/cbv/commands/list_cmd.py**

Replace `scripts/cbv/commands/list_cmd.py`:

```python
"""`list` verb — print every indexed repo (human-readable)."""
from __future__ import annotations

import argparse

from cbv import db, paths


def run(_ns: argparse.Namespace) -> int:
    repos = paths.list_indexed_repos()
    if not repos:
        print("No indexed repos found.")
        print(f"  Searched: {paths.repos_dir()}")
        return 0
    for r in repos:
        version = "?"
        try:
            conn = db.open_db(r / "index.sqlite")
            v = db.read_meta(conn, "schema_version")
            conn.close()
            version = v or "legacy"
        except Exception:
            version = "unreadable"
        print(f"{r.name}\tschema={version}\t{r}")
    return 0
```

- [ ] **Step 4: Implement scripts/cbv/commands/info.py**

Replace `scripts/cbv/commands/info.py`:

```python
"""`info` verb — print plugin paths + readiness for debugging."""
from __future__ import annotations

import argparse

from cbv import paths


def run(_ns: argparse.Namespace) -> int:
    print(f"data_home:        {paths.data_home()}")
    print(f"python_env:       {paths.python_env_dir()}")
    print(f"python_env_bin:   {paths.python_env_executable()}")
    print(f"python_env_ready: {paths.python_env_executable().exists()}")
    print(f"repos_dir:        {paths.repos_dir()}")
    repos = paths.list_indexed_repos()
    print(f"indexed_repos:    {len(repos)}")
    for r in repos:
        print(f"  - {r.name}  @  {r}")
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_list_info_cmd.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/cbv/commands/list_cmd.py scripts/cbv/commands/info.py \
        tests/unit/test_list_info_cmd.py
git commit -m "slice 1 t12: cbv.commands.list_cmd + info — trivial verbs"
```

---

### Task 13: Update skills/vectorize-repo/SKILL.md and skills/codebase-query/SKILL.md to v1.0

Update the two existing skill markdown files to reflect:
- v1.0 invocation paths (unchanged — `run.sh vectorize` / `run.ps1 vectorize`)
- new JSON output shape from the `vectorize` and `query` verbs
- model name change from BGE-small to jina-code-embeddings-1.5b
- bump `metadata.version` from `"0.3.0"` to `"1.0.0"`

NOTE: a separate `codebase-relate` skill ships in Slice 8; do NOT add it here.

**Files:**
- Modify: `skills/vectorize-repo/SKILL.md`
- Modify: `skills/codebase-query/SKILL.md`

- [ ] **Step 1: Update skills/vectorize-repo/SKILL.md**

Replace the entire file with:

```markdown
---
name: vectorize-repo
description: >
  Clone, chunk, and vector-index a public GitHub repo (or local folder) for cheap
  future queries. Use when the user says "vectorize this repo", "index this codebase",
  "index <repo>", "build an index for <repo>", "make this repo searchable", "RAG this
  repo", or provides a GitHub URL and asks to index/learn/explore it. Also triggers
  when the user wants to set up a codebase for later querying via the codebase-query
  skill.
metadata:
  version: "1.0.0"
---

# Vectorize Repo

Index a public GitHub repo (or local folder) into a local SQLite database (FTS5 +
`sqlite-vec`) so future codebase questions cost a few hundred tokens instead of
tens of thousands.

The user provides a GitHub URL or a local path. Extract that argument from their
message and pass it to the indexer verbatim.

## What v1.0 indexing does

The Slice 1 indexer pipeline:

1. **Resolve source** — clone (URL) or copy (local) into `<repo_dir>/source/`.
2. **Walk + filter** — `.gitignore` (root), files > 1.5 MB, binaries via NUL sniff.
3. **Chunk** — line-aware text windows, 1500-byte budget. (Tree-sitter + cAST
   chunking arrives in a future indexing pass.)
4. **Embed** — `jinaai/jina-code-embeddings-1.5b` (1536-dim). GPU path uses
   transformers FP16; CPU path uses llama-cpp-python GGUF INT4. Embeddings are
   INT8-quantized into `sqlite-vec`.
5. **Write** — `chunks`, `chunks_fts`, `vec_chunks`, and `meta` (schema version,
   embedder model/dim/quant, indexed_at, repo_origin, commit_sha, counts).

The full v1.0 schema (ten tables — symbol graph, flow graph, clusters, Merkle,
etc.) is created at index time so future indexing passes add no migrations. Slice 1
populates only the four tables above; the rest stay empty.

## Where things live

All plugin data is stored under `${CLAUDE_PLUGIN_DATA}` (Claude Code sets this
env var per plugin; it persists across plugin updates):

```
${CLAUDE_PLUGIN_DATA}/
├── python-env/         the plugin's isolated Python interpreter + deps
└── repos/
    └── <repo-name>/
        ├── source/     the cloned repo (no .git/)
        ├── index.sqlite
        └── manifest.json
```

The venv is named `python-env/` — not `.venv` — so it can never be mistaken for
a project's own virtual environment. It is invoked by absolute path and **never
activated**.

`ARCHITECTURE.md` lands in a later indexing pass; do not generate it from this
skill yet.

## Step 1 — Run the indexer

The launcher (`run.sh` on POSIX, `run.ps1` on Windows) handles everything: finds
Python 3.10–3.13, bootstraps the venv, installs deps (`sqlite-vec`,
`transformers`, `torch`, `llama-cpp-python`, etc.), downloads the embedding
model (~750 MB GGUF, one-time, into the user's HuggingFace cache), then indexes.

**On POSIX (macOS, Linux, WSL):**

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" vectorize "<github_url_or_path>"
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" vectorize "<github_url_or_path>"
```

First invocation takes 5–15 minutes (venv + deps + model). Subsequent runs
amortize most of that — only the per-repo index work happens.

The script ends with a JSON summary on the last line of stdout:

```json
{
  "repo_name": "react",
  "source_dir": ".../repos/react/source",
  "db_path": ".../repos/react/index.sqlite",
  "manifest_path": ".../repos/react/manifest.json",
  "files_indexed": 1247,
  "chunks_indexed": 18402,
  "nodes_symbol": 0,
  "nodes_block": 0,
  "edges_symbol": 0,
  "edges_flow": 0,
  "clusters_indexed": 0,
  "elapsed_seconds": 281.4,
  "embedding_cache_hit_rate": 0.0,
  "warnings": [],
  "bench_results": {}
}
```

The zero-valued fields are placeholders for capabilities that future slices
populate (symbol graph, flow graph, concept clusters, cross-repo embedding
cache, benchmark suite). Their presence in the v1.0 schema means no future
re-indexing for those features.

If the script errors, surface the error and stop.

## Step 2 — Report to user

Tell the user in plain English:

- Repo name + counts (files, chunks, elapsed) from the JSON summary.
- Where the index lives (the `db_path` directory).
- That they can now ask codebase questions **from any working directory** and
  the `codebase-query` skill will answer using the index.

**Do not** read further into the repo after this. Future questions go through
the query skill, not by burning tokens here.

## Troubleshooting

- **"No Python 3.10–3.13 found"** — install Python 3.12.
  - Windows: `winget install Python.Python.3.12`
  - Debian/Ubuntu/WSL: `sudo apt install python3.12 python3.12-venv`
  - macOS: `brew install python@3.12`
- **Wheels fail on first install** — almost always because the user's Python is
  too new (3.14+) and `torch` or `llama-cpp-python` has no prebuilt wheel yet.
  Install Python 3.12 and re-run.
- **Model download fails** — the default GGUF repo/file may not exist for
  jina-code-embeddings-1.5b. Set `CBV_GGUF_REPO` and `CBV_GGUF_FILE` env vars
  to a known-good community quant, then re-run.
- **Reset the plugin's state** — delete `${CLAUDE_PLUGIN_DATA}/python-env/` and
  re-run; deps reinstall. Delete `${CLAUDE_PLUGIN_DATA}/repos/<name>/` to drop a
  single index. The user's v0.3.0 indexes will return a "legacy schema, please
  re-vectorize" error on query — same fix.
```

- [ ] **Step 2: Update skills/codebase-query/SKILL.md**

Replace the entire file with:

```markdown
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
(SQLite + FTS5 + `sqlite-vec`), then reading only the specific file ranges the
query returns. **Never scan the indexed repo with Glob/Grep/Read on full files
unless the query tool comes back empty.** That defeats the entire purpose of
this plugin.

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
bash "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" query <repo_name> "<exact user question>" --top-k 6
```

**On Windows (PowerShell):**

```powershell
& "${env:CLAUDE_PLUGIN_ROOT}\scripts\run.ps1" query <repo_name> "<exact user question>" --top-k 6
```

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
  "expansion_size": 0
}
```

`refined_queries` is always present but empty until a later indexing pass adds
confidence-based hints; `expansion_size` is zero until graph expansion lands.
`pipeline_used` is always `"full"` in v1.0 Slice 1 — the fast lane / router
arrives later.

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
- **Do not** re-index the repo. If the user wants a fresh index, run
  `vectorize-repo` again.
- **Do not** answer from training-data memory.
- If the query script errors with "No index found", run `list` (Step 1) and
  tell the user what's available.
- If the query script errors with "older codebase-vectorizer index", tell the
  user the index is from an earlier version and needs re-vectorizing.
```

- [ ] **Step 3: Manual review**

Read both files end-to-end (`cat skills/vectorize-repo/SKILL.md skills/codebase-query/SKILL.md`)
and verify:
- `metadata.version` is `"1.0.0"` in both files.
- No references to `BAAI/bge-small-en-v1.5` or `fastembed` remain.
- The query JSON shape includes `pipeline_used`, `refined_queries`, and
  `expansion_size` keys.
- The vectorize JSON shape includes `nodes_symbol`, `nodes_block`,
  `edges_symbol`, `edges_flow`, `clusters_indexed`, `embedding_cache_hit_rate`,
  `bench_results`.

- [ ] **Step 4: Commit**

```bash
git add skills/vectorize-repo/SKILL.md skills/codebase-query/SKILL.md
git commit -m "slice 1 t13: skills SKILL.md → v1.0 invocations and JSON shape"
```

---

### Task 14: Fixture repo + end-to-end integration test

Build the simple-python fixture referenced by the spec's test layout and a single
integration test that exercises the entire indexing+query loop against it using
the StubEmbedder (fast CI). One optional test path runs with the real Jina
embedder when `CBV_RUN_REAL_EMBEDDER=1` is set; that path is not required for
this slice to land.

**Files:**
- Create: `tests/fixtures/simple-python/pkg/__init__.py`
- Create: `tests/fixtures/simple-python/pkg/auth.py`
- Create: `tests/fixtures/simple-python/pkg/router.py`
- Create: `tests/fixtures/simple-python/pkg/db.py`
- Create: `tests/fixtures/simple-python/pkg/utils.py`
- Create: `tests/fixtures/simple-python/tests/test_auth.py`
- Create: `tests/fixtures/simple-python/README.md`
- Create: `tests/fixtures/simple-python/pyproject.toml`
- Create: `tests/fixtures/simple-python/main.py`
- Create: `tests/fixtures/simple-python/.gitignore`
- Create: `tests/integration/test_full_index.py`

- [ ] **Step 1: Create the fixture files**

Create `tests/fixtures/simple-python/pkg/__init__.py`:

```python
"""simple-python — a 10-file fixture for codebase-vectorizer Slice 1 tests."""
```

Create `tests/fixtures/simple-python/pkg/auth.py`:

```python
"""Authentication helpers."""
from __future__ import annotations

from pkg.db import fetch_one
from pkg.utils import constant_time_compare


def authenticate_user(username: str, password_hash: str) -> bool:
    """Return True iff the credentials match a row in the users table."""
    row = fetch_one("SELECT password_hash FROM users WHERE username = ?",
                    (username,))
    if row is None:
        return False
    return constant_time_compare(row[0], password_hash)


def issue_session_token(user_id: int) -> str:
    """Create an opaque session token for the given user id."""
    import secrets
    return secrets.token_urlsafe(32)
```

Create `tests/fixtures/simple-python/pkg/router.py`:

```python
"""URL → handler routing for the toy app."""
from __future__ import annotations

from pkg.auth import authenticate_user


def route_request(method: str, path: str):
    """Return the handler for (method, path) or None."""
    if path == "/login" and method == "POST":
        return _handle_login
    if path.startswith("/api/"):
        return _api_dispatch
    return _static_handler


def _handle_login(req):
    return {"ok": authenticate_user(req["user"], req["pw_hash"])}


def _api_dispatch(req):
    return {"echo": req}


def _static_handler(req):
    return {"static": True}
```

Create `tests/fixtures/simple-python/pkg/db.py`:

```python
"""Tiny SQLite wrapper for the fixture."""
from __future__ import annotations

import sqlite3
from typing import Iterable, Optional, Tuple


def open_conn(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path)


def fetch_one(sql: str, params: Iterable = ()) -> Optional[Tuple]:
    conn = open_conn(":memory:")
    return conn.execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable = ()) -> None:
    conn = open_conn(":memory:")
    with conn:
        conn.execute(sql, tuple(params))
```

Create `tests/fixtures/simple-python/pkg/utils.py`:

```python
"""Small helpers."""
from __future__ import annotations

import hmac


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to avoid timing attacks."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def slugify(s: str) -> str:
    """Lowercase, replace spaces with dashes, drop non-alnum."""
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")
```

Create `tests/fixtures/simple-python/tests/test_auth.py`:

```python
"""Tests for the auth module."""
from __future__ import annotations

import pytest

from pkg.auth import authenticate_user


def test_authenticate_user_returns_bool():
    assert isinstance(authenticate_user("u", "h"), bool)
```

Create `tests/fixtures/simple-python/README.md`:

```markdown
# simple-python fixture

A 10-file Python fixture exercised by codebase-vectorizer Slice 1's integration
test. Modules: auth, router, db, utils, plus a single test and a launcher.

Do not import this fixture into the real cbv codebase — it lives under tests/.
```

Create `tests/fixtures/simple-python/pyproject.toml`:

```toml
[project]
name = "simple-python"
version = "0.0.1"
description = "fixture for codebase-vectorizer tests"
requires-python = ">=3.10"
```

Create `tests/fixtures/simple-python/main.py`:

```python
"""Entry point for the simple-python fixture."""
from __future__ import annotations

from pkg.router import route_request


def main() -> int:
    handler = route_request("POST", "/login")
    if handler is None:
        return 1
    out = handler({"user": "alice", "pw_hash": "x"})
    return 0 if out["ok"] is False else 0  # demo only


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `tests/fixtures/simple-python/.gitignore`:

```
__pycache__/
*.pyc
.venv/
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration/test_full_index.py`:

```python
"""End-to-end test: index simple-python fixture, run queries, assert results.

Default mode uses StubEmbedder (fast, deterministic). Setting
CBV_RUN_REAL_EMBEDDER=1 reruns with the real Jina embedder — that path
is exercised manually and is not required for Slice 1 to land.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv.commands import query as query_cmd, vectorize as vec_cmd  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "simple-python"


@pytest.fixture
def indexed(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    if os.environ.get("CBV_RUN_REAL_EMBEDDER") != "1":
        monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    ns = argparse.Namespace(source=str(FIXTURE), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "simple-python"


def test_index_files_count_matches_fixture(indexed):
    """The fixture has 10 indexable files (after gitignore)."""
    from cbv import db, paths
    conn = db.open_db(paths.repo_dir(indexed) / "index.sqlite")
    n_files = conn.execute(
        "SELECT COUNT(DISTINCT file_path) FROM chunks"
    ).fetchone()[0]
    # 5 pkg/*.py + tests/test_auth.py + main.py + README.md + pyproject.toml + .gitignore
    assert n_files == 10


def test_query_for_authenticate_finds_auth_py(indexed, capsys):
    ns = argparse.Namespace(repo=indexed, question="authenticate user credentials", top_k=5)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    # At least one result should be from pkg/auth.py within the top-5.
    found = any("pkg/auth.py" in r["file_relative"] for r in blob["results"])
    assert found, f"results: {[r['file_relative'] for r in blob['results']]}"


def test_query_for_routing_finds_router_py(indexed, capsys):
    ns = argparse.Namespace(repo=indexed, question="route_request POST login handler", top_k=5)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    found = any("pkg/router.py" in r["file_relative"] for r in blob["results"])
    assert found, f"results: {[r['file_relative'] for r in blob['results']]}"


def test_query_for_db_finds_db_py(indexed, capsys):
    ns = argparse.Namespace(repo=indexed, question="SQLite fetch_one query helper", top_k=5)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    found = any("pkg/db.py" in r["file_relative"] for r in blob["results"])
    assert found, f"results: {[r['file_relative'] for r in blob['results']]}"


def test_query_result_line_ranges_valid(indexed, capsys):
    """Every returned (start_line, end_line) range must be valid and content
    at that range must be readable from the file."""
    ns = argparse.Namespace(repo=indexed, question="authenticate", top_k=3)
    query_cmd.run(ns)
    blob = json.loads([l for l in capsys.readouterr().out.strip().splitlines() if l.strip()][-1])
    for r in blob["results"]:
        f = Path(r["file_absolute"])
        assert f.exists(), f"{f} not found"
        lines = f.read_text(encoding="utf-8").splitlines()
        assert 1 <= r["start_line"] <= r["end_line"] <= len(lines)
```

- [ ] **Step 3: Run tests to verify they fail (or pass — verify the meaning)**

Run: `<venv_python> -m pytest tests/integration/test_full_index.py -v`

If Tasks 1–12 are complete, these tests should already pass — the integration
test is exercising existing functionality end-to-end. If they fail, the failure
mode reveals where unit-test coverage was insufficient:

- `assert n_files == 10` fails → walker/gitignore wrong
- `assert found, ...` fails → query/RRF or chunker selection wrong
- line-range assert fails → chunker line accounting is off

Fix any failure by adding a focused unit test in the matching module's test
file, fixing the module, then re-running this integration test.

- [ ] **Step 4: Run the entire test suite**

Run: `<venv_python> -m pytest tests/ -v`
Expected: every test under `tests/unit/` and `tests/integration/` passes. No
warnings beyond pytest collection notices.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/simple-python tests/integration/test_full_index.py
git commit -m "slice 1 t14: simple-python fixture + end-to-end integration test"
```

---

### Task 15: README.md update for v1.0 Slice 1

Update the project's README to reflect the v1.0 implementation: new embedder,
new schema, what Slice 1 ships vs what comes later.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README.md sections**

Open `README.md` and apply the following changes:

In the "What it does" section, replace the bullet about retrieval with:

```markdown
- **`vectorize-repo` skill** — clone, chunk, embed, and store a repo in a local
  SQLite database (FTS5 keyword index + `sqlite-vec` ANN vector index). Slice 1
  uses line-aware text-window chunking and `jinaai/jina-code-embeddings-1.5b`
  (1536-dim, INT8-quantized). Tree-sitter + cAST chunking, symbol graph, flow
  graph, concept clusters, and the `codebase-relate` skill ship in subsequent
  slices.
- **`codebase-query` skill** — auto-triggers on questions about an indexed
  codebase. Runs BM25 + dense KNN + Reciprocal Rank Fusion and returns the
  top-k file:line ranges. Cross-encoder rerank, graph expansion, fast-lane
  routing, and confidence-based query refinement land in later slices.
```

In the "Requirements" section, replace the model line with:

```markdown
- **Internet on first use** for ~250 MB of Python wheels (one-time, cached) and
  ~750 MB for the embedding model (`jinaai/jina-code-embeddings-1.5b` GGUF
  INT4, one-time, cached under `~/.cache/huggingface/`). Subsequent runs are
  fully offline.
```

Replace the "How retrieval works" section with:

```markdown
## How retrieval works (Slice 1)

1. **Chunking**: line-aware text-window splitter (1500-byte budget) preserves
   the concat == file invariant. Future slices use tree-sitter + cAST.
2. **Embeddings**: every chunk is embedded with `jinaai/jina-code-embeddings-1.5b`
   (1536-dim, INT8-quantized). GPU path uses transformers FP16; CPU path uses
   `llama-cpp-python` with GGUF INT4. Local, no API keys.
3. **Storage**: full v1.0 schema (ten tables) created at index time;
   Slice 1 populates `chunks` (canonical), `chunks_fts` (FTS5 BM25),
   `vec_chunks` (`sqlite-vec` INT8 ANN), and `meta`. Same `rowid` across
   `chunks` and the FTS view; `chunk_id` links to `vec_chunks`.
4. **Query**: the query is embedded; BM25 and dense KNN run top-50 each, then
   Reciprocal Rank Fusion picks the top-k. Output is v1.0-shape JSON with
   `pipeline_used`, `refined_queries`, and `expansion_size` keys (the latter
   two stay zero/empty until later slices).
5. **Read**: Claude opens each returned file at the specified line range using
   `Read(file_path, offset, limit)`.
```

Replace the "Limits & known trade-offs" section with:

```markdown
## Limits & known trade-offs (Slice 1)

- **Text-window chunking, not tree-sitter**: chunks respect line boundaries
  and the byte budget, but do not align to function/class boundaries. Slice 2
  adds tree-sitter + cAST chunking.
- **No symbol graph yet**: caller/callee questions don't get graph expansion
  until Slice 3.
- **No cross-encoder rerank**: top-k is RRF-only. Slice 5 adds
  `mxbai-rerank-large-v2`.
- **No incremental re-indexing**: each `vectorize` is a full re-clone + re-embed.
  Slice 12 adds Merkle-based incremental updates.
- **No fast-lane router**: identifier-like queries take the full pipeline.
  Slice 4 adds the router + identifier trigram index.
- **Default file limit is 1.5 MB** per file. Use `--max-file-mb` to raise it.
- **Indexes from v0.3.0 are not auto-upgraded**: queries against them return a
  clean "legacy schema" error; re-run `vectorize-repo` to upgrade.
```

Leave the "Install", "Where data lives", and "Usage" sections unchanged (their
content is still correct for v1.0).

- [ ] **Step 2: Manual review**

`cat README.md` and verify:
- No remaining references to `BAAI/bge-small-en-v1.5`, `fastembed`, or `BGE-small`.
- The schema description references the ten v1.0 tables.
- The capability statement makes clear what Slice 1 has and what later slices add.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "slice 1 t15: README — v1.0 Slice 1 capabilities and trade-offs"
```

---

## Self-review summary

Coverage check — every spec requirement that falls inside Slice 1's scope boundary:

- ✅ v1.0 schema (10 tables, including legacy ones that stay empty) — Task 4
- ✅ FTS5 BM25 with porter+unicode61+code separators tokenize — Task 4
- ✅ `sqlite-vec` INT8[1536] vector storage with cosine distance — Task 4 + 8
- ✅ jina-code-embeddings-1.5b embedder, CPU GGUF + GPU FP16 paths — Task 9
- ✅ INT8 quantization at storage — Task 8 + Task 10
- ✅ File walk + `.gitignore` (root) + size + binary filters — Task 5
- ✅ git clone (URL) + local recursive copy — Task 6
- ✅ Line-aware text-window chunker with concat invariant — Task 7
- ✅ Indexing pipeline orchestration with meta + manifest — Task 10
- ✅ v1.0 vectorize JSON shape with zero-valued placeholders — Task 10
- ✅ Query pipeline: BM25 + dense + RRF, v1.0 query JSON shape — Task 11
- ✅ Legacy schema detection — Task 4 + Task 11
- ✅ Three failure modes from the spec (missing repo, legacy schema, sqlite-vec extension load) — Task 4 + Task 11
- ✅ `list`, `info` verbs — Task 12
- ✅ Launcher chain (run.sh, run.ps1, bootstrap.py) — Task 3
- ✅ Skill SKILL.md updates for v1.0 invocations/JSON — Task 13
- ✅ End-to-end integration test on simple-python fixture — Task 14
- ✅ README updated — Task 15

Out-of-scope items remain explicitly deferred to future slices and are NOT
implemented in Slice 1 — see the "Scope boundary" section at the top.

Type consistency:
- `Chunk` dataclass — defined in chunker.py (Task 7), used by vectorize (Task 10). Same shape.
- `WalkEntry` dataclass — defined in walker.py (Task 5), used by vectorize (Task 10). Same shape.
- `Embedder.embed(texts) -> np.ndarray[N, dim]` — defined in embedder.py (Task 9), used by vectorize (Task 10) and query (Task 11). Same signature.
- `db.LegacySchemaError`, `db.open_db`, `db.init_schema`, `db.read_meta`, `db.write_meta`, `db.assert_schema_v1` — defined in db.py (Task 4), consumed by every command. Same names.
- `paths.find_repo`, `paths.repo_dir`, `paths.list_indexed_repos`, `paths.data_home`, `paths.repos_dir`, `paths.python_env_executable` — defined in paths.py (Task 2), consumed everywhere. Same names.
- v1.0 vectorize output JSON keys — same set produced in Task 10 and asserted in Task 14 integration.
- v1.0 query output JSON keys — same set produced in Task 11 and asserted in Task 14 integration.
- `meta` required-key set — written in Task 10, read/asserted in Tasks 10 (test) and 11.

No placeholders survive in this plan: every step contains the actual code or
exact command an engineer needs to execute, and every test has assertions
verifying observable behavior rather than describing it.
