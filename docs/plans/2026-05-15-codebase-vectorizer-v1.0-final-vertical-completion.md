# codebase-vectorizer v1.0 Final Vertical Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish v1.0 from the current Slice 2 baseline by adding the remaining retrieval capabilities vertically: symbol/trigram indexing, fast-lane routing, graph expansion, `codebase-relate`, reranking/confidence, embedding cache, incremental indexing, concept clusters, flow edges, architecture output, and bench reporting.

**Architecture:** Keep the current end-to-end CLI stable: `vectorize` always creates or updates a usable `index.sqlite`, and `query` always returns the v1.0 JSON shape. Each milestone adds one retrieval capability through storage, indexing, query/skill surface, and tests before moving on. Deterministic local implementations and stubs are for tests, tiny fixtures, and spec-defined failure fallbacks only; they do not replace the spec-required production path.

**Tech Stack:** Current Slice 2 stack: Python 3.10-3.13, SQLite + FTS5 + sqlite-vec, tree-sitter-language-pack, numpy, pathspec, transformers/torch/llama-cpp optional embedding runtime, pytest. Add `networkx`, `sentence-transformers`, `umap-learn`, and `hdbscan` only in the milestones that first need them.

**Current baseline before this plan starts:**
- `dev` contains Slice 1 and Slice 2.
- Full test suite baseline: `224 passed, 1 skipped`.
- Working vertical path: `cbv vectorize <repo>` -> chunks + FTS + vec embeddings -> `cbv query <repo> "<question>"`.
- Current populated tables: `chunks`, `chunks_fts`, `vec_chunks`, `meta`.
- Current empty-but-created tables: `symbol_trigrams`, `nodes`, `edges`, `clusters`, `chunk_clusters`, `merkle_files`.

**Completion policy:** This plan is code-complete before final polish. After this plan, run one final polish pass for docs wording, README drift, CLI help text, dependency comments, and any small review-driven cleanup. Do not mix polish into the capability milestones unless a polish issue blocks correctness or tests.

**Completion tracking directive:** When a task can be safely designated as done, mark the task as complete by editing this completion plan. A task is safe to mark complete only after its required implementation, verification command, and commit step have succeeded, or after the task is explicitly superseded by a later spec-aligned edit in this same plan.

**Spec authority and completion bar:** `specs/2026-05-14-codebase-vectorizer-v1.0-design.md` is the master document. A reduced local MVP is allowed only as an intermediate task inside this plan, never as the final definition of done. The final verification gate must prove the spec-required behavior exists, including broad tree-sitter symbol extraction, identifier trigrams, fast/full query lanes, graph expansion with query-time Personalized PageRank, cross-encoder reranking, refined-query hints, content-hash embedding cache, Merkle incremental indexing, UMAP + HDBSCAN concept clusters with an LLM label path, intra-procedural CFG/DFG flow edges, `codebase-relate` verbs, `ARCHITECTURE.md`, and benchmark output.

**Allowed fallback behavior:** Fallbacks must match the spec's failure-mode table. Parser failure can fall back to text-window chunking; symbol extraction failure can skip edges for that file while preserving chunks; CFG/DFG failure can skip flow for that function while preserving symbol edges; UMAP failure on tiny repos can skip L4; HDBSCAN all-noise can produce empty clusters; LLM label failure can use deterministic `cluster_N` labels with a manifest warning; PageRank divergence can use uniform PageRank with a warning. Fallback behavior must be tested separately and must not become the default production path.

**Post-v1.0 polish only:** README phrasing, CLI help wording, dependency comments, output example prettiness, tuning constants, and larger manual real-repo benchmarks are polish. Tier coverage, PPR, LLM label path, flow verbs, cache/incremental correctness, and benchmark command support are not polish; they are required for v1.0.

---

## File Structure After This Plan

```
scripts/
├── bootstrap.py
├── requirements.txt
└── cbv/
    ├── architecture.py              NEW: one-pass LLM architecture writer with deterministic failure fallback
    ├── bench.py                     NEW: CoIR/RepoEval-style benchmark runner and metric helpers
    ├── cache.py                     NEW: embedding_cache.sqlite helpers
    ├── chunker.py                   EXISTING: stable Chunk shape
    ├── clusters.py                  NEW: UMAP + HDBSCAN concept clusters + LLM labels
    ├── commands/
    │   ├── bench_cmd.py             NEW: `cbv bench <repo>`
    │   ├── flow_cmd.py              NEW: `cbv flow <repo> <function>`
    │   ├── graph_cmd.py             NEW: `cbv graph <repo> <symbol>`
    │   ├── relate.py                NEW: `cbv relate <repo> <verb> ...`
    │   ├── stats.py                 NEW: `cbv stats <repo>`
    │   ├── query.py                 MODIFIED: router, fast/full lanes, graph expansion, rerank/confidence
    │   └── vectorize.py             MODIFIED: symbols, trigrams, cache, incremental, clusters, flow, architecture, bench
    ├── flow.py                      NEW: tiered intra-procedural CFG/DFG extraction
    ├── graph.py                     NEW: node/edge writes, graph expansion, global PR, query-time PPR
    ├── incremental.py               NEW: file hashes, Merkle root, delta planning
    ├── identifiers.py               NEW: identifier extraction + trigram index helpers
    ├── reranker.py                  NEW: CrossEncoder adapter + deterministic stub
    ├── symbols.py                   NEW: tags.scm-backed tree-sitter symbol/import/call extraction
    └── query_router.py              NEW: lane classification and query normalization

skills/
├── codebase-query/SKILL.md          MODIFIED: fast/full/relate behavior
├── codebase-relate/SKILL.md         NEW: graph and flow query skill
└── vectorize-repo/SKILL.md          MODIFIED: complete v1.0 output fields

tests/
├── fixtures/
│   ├── flow-heavy/                  NEW: fixtures for CFG/DFG and relate flow verbs
│   └── polyglot-mini/               NEW: Tier-A fixture for symbol graph/trigrams
├── integration/
│   ├── test_full_index.py           MODIFIED: v1.0 populated fields
│   ├── test_incremental.py          NEW
│   ├── test_query_lanes.py          NEW
│   └── test_relate_cmd.py           NEW
└── unit/
    ├── test_architecture.py         NEW
    ├── test_bench.py                NEW
    ├── test_cache.py                NEW
    ├── test_clusters.py             NEW
    ├── test_flow.py                 NEW
    ├── test_graph.py                NEW
    ├── test_incremental.py          NEW
    ├── test_identifiers.py          NEW
    ├── test_query_router.py         NEW
    ├── test_reranker.py             NEW
    └── test_symbols.py              NEW
```

---

## Milestone 1: Symbols, Trigrams, Fast Lane, and Graph-Aware Query

This is the highest-value remaining vertical. After this milestone, identifier-like queries become cheap and caller/callee/import neighborhoods influence normal query results.

**Completion tracking directive:** At the end of each Task 1-4 verification block, if the task is safe to designate as done, edit this plan and change that task's relevant checklist items from `- [ ]` to `- [x]`. Do not rely on memory, commit messages, or chat history as the source of truth.

### Task 1: Identifier trigram indexing

**Files:**
- Create: `scripts/cbv/identifiers.py`
- Create: `tests/unit/test_identifiers.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Modify: `tests/unit/test_vectorize_cmd.py`

- [x] **Step 1: Write failing identifier tests**

Create `tests/unit/test_identifiers.py`:

```python
from cbv import identifiers


def test_extract_identifiers_splits_common_code_names():
    text = "authenticate_user camelCase HTTPServer2 user_id"
    assert identifiers.extract_identifiers(text) == {
        "authenticate_user", "authenticate", "user",
        "camelCase", "camel", "Case",
        "HTTPServer2", "HTTP", "Server2", "user_id", "id",
    }


def test_trigrams_pad_and_lowercase():
    assert identifiers.trigrams("Auth") == {"  a", " au", "aut", "uth", "th "}


def test_symbol_rows_count_occurrences_by_chunk():
    rows = identifiers.symbol_trigram_rows(7, "auth auth user")
    assert ("aut", 7, "auth", 2) in rows
    assert ("use", 7, "user", 1) in rows
```

- [x] **Step 2: Run tests and verify failure**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_identifiers.py -v
```

Expected: import failure because `cbv.identifiers` does not exist.

- [x] **Step 3: Implement `scripts/cbv/identifiers.py`**

Create:

```python
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Set

IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+")


def extract_identifiers(text: str) -> Set[str]:
    found: set[str] = set()
    for match in IDENT_RE.finditer(text):
        token = match.group(0)
        found.add(token)
        for part in token.split("_"):
            if len(part) >= 3:
                found.add(part)
            for camel in CAMEL_RE.findall(part):
                if len(camel) >= 3:
                    found.add(camel)
    return found


def trigrams(symbol: str) -> set[str]:
    s = f"  {symbol.lower()} "
    if len(s) < 3:
        return set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def symbol_trigram_rows(chunk_id: int, content: str) -> list[tuple[str, int, str, int]]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for symbol in extract_identifiers(content):
        for gram in trigrams(symbol):
            counts[(gram, symbol)] += 1
    return [(gram, chunk_id, symbol, occurrences)
            for (gram, symbol), occurrences in sorted(counts.items())]
```

- [x] **Step 4: Wire vectorize writes**

In `scripts/cbv/commands/vectorize.py`, after chunk IDs are known, insert rows:

```python
from cbv import identifiers

...

for chunk_id, c in zip(ids, chunks_buf):
    conn.executemany(
        "INSERT INTO symbol_trigrams (trigram, chunk_id, symbol, occurrences) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(trigram, chunk_id, symbol) DO UPDATE SET "
        "occurrences = occurrences + excluded.occurrences",
        identifiers.symbol_trigram_rows(chunk_id, c.content),
    )
```

- [x] **Step 5: Add vectorize assertion**

Add to `tests/unit/test_vectorize_cmd.py`:

```python
def test_vectorize_populates_symbol_trigrams(tmp_home, source_repo):
    from cbv.commands import vectorize
    ns = argparse.Namespace(source=str(source_repo), output_dir=None, max_file_mb=1.5)
    vectorize.run(ns)
    conn = db.open_db(paths.repo_dir("src") / "index.sqlite")
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM symbol_trigrams WHERE symbol = 'helper'"
        ).fetchone()
        assert row[0] > 0
    finally:
        conn.close()
```

- [x] **Step 6: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_identifiers.py tests\unit\test_vectorize_cmd.py -v
```

Expected: all selected tests pass.

Commit:

```bash
git add scripts/cbv/identifiers.py scripts/cbv/commands/vectorize.py tests/unit/test_identifiers.py tests/unit/test_vectorize_cmd.py
git commit -m "slice 3 t1: index identifier trigrams"
```

### Task 2: Symbol nodes and symbolic edges

This task may start with focused extraction code, but it is not spec-complete until Task 2A passes. The final implementation must use tree-sitter query captures in the style of `tags.scm` for broad Tier-A coverage; hard-coded Python/JavaScript traversal is only a bootstrap scaffold.

**Files:**
- Create: `scripts/cbv/symbols.py`
- Create: `scripts/cbv/graph.py`
- Create: `tests/unit/test_symbols.py`
- Create: `tests/unit/test_graph.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Modify: `tests/integration/test_full_index.py`

- [x] **Step 1: Write failing symbol extraction tests**

Create `tests/unit/test_symbols.py`:

```python
from pathlib import Path

from cbv import parser, symbols


def test_python_symbols_extract_defs_imports_calls():
    src = b"from pkg.auth import authenticate_user\n\ndef route(req):\n    return authenticate_user(req['u'], req['p'])\n"
    lang = parser.language_for_name("python")
    tree = parser.parse(src, lang)
    extracted = symbols.extract_symbols(Path("pkg/router.py"), "python", src, tree)
    assert ("function", "pkg/router.py::route", "route") in [
        (n.kind, n.name, n.short_name) for n in extracted.nodes
    ]
    assert any(e.kind == "imports" and e.dst_name == "authenticate_user" for e in extracted.edges)
    assert any(e.kind == "calls" and e.dst_name == "authenticate_user" for e in extracted.edges)


def test_javascript_symbols_extract_function_and_call():
    src = b"export function camelCase(x) { return snakeCase(x); }\n"
    lang = parser.language_for_name("javascript")
    tree = parser.parse(src, lang)
    extracted = symbols.extract_symbols(Path("util.js"), "javascript", src, tree)
    assert any(n.short_name == "camelCase" and n.kind == "function" for n in extracted.nodes)
    assert any(e.kind == "calls" and e.dst_name == "snakeCase" for e in extracted.edges)
```

- [x] **Step 2: Implement symbol dataclasses and extraction**

Create `scripts/cbv/symbols.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class SymbolNode:
    kind: str
    name: str
    short_name: str
    file_path: str
    start_line: int | None
    end_line: int | None
    signature: str | None
    parent_name: str | None
    chunk_id: int | None = None


@dataclass(frozen=True)
class SymbolEdge:
    src_name: str
    dst_name: str
    kind: str
    weight: float
    metadata: str | None = None


@dataclass(frozen=True)
class ExtractedSymbols:
    nodes: list[SymbolNode]
    edges: list[SymbolEdge]


EDGE_WEIGHTS = {
    "defines": 5.0,
    "calls": 3.0,
    "imports": 1.5,
    "inherits": 3.0,
    "references": 2.0,
    "contains": 1.0,
}


def extract_symbols(file_path: Path, language: str, source: bytes, tree) -> ExtractedSymbols:
    if tree is None:
        return ExtractedSymbols([], [])
    nodes: list[SymbolNode] = []
    edges: list[SymbolEdge] = []
    module_name = file_path.as_posix()
    nodes.append(SymbolNode("file", module_name, file_path.name, file_path.as_posix(), 1, 1, None, None))

    def text(node) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def line(node) -> int:
        return int(node.start_point[0]) + 1

    def name_child(node) -> str | None:
        child = node.child_by_field_name("name")
        return text(child) if child is not None else None

    def walk(node, parent_symbol: str) -> None:
        node_type = node.type
        short = name_child(node)
        kind = None
        if language == "python" and node_type in {"function_definition", "class_definition"}:
            kind = "class" if node_type == "class_definition" else "function"
        elif language in {"javascript", "typescript", "tsx"} and node_type in {
            "function_declaration", "method_definition", "class_declaration",
        }:
            kind = "class" if node_type == "class_declaration" else "function"
        if kind and short:
            full = f"{module_name}::{short}"
            nodes.append(SymbolNode(kind, full, short, file_path.as_posix(), line(node),
                                    int(node.end_point[0]) + 1, text(node).splitlines()[0],
                                    parent_symbol))
            edges.append(SymbolEdge(parent_symbol, full, "contains", EDGE_WEIGHTS["contains"]))
            parent_symbol = full
        if language == "python" and node_type in {"import_from_statement", "import_statement"}:
            for child in node.children:
                if child.type == "dotted_name" or child.type == "identifier":
                    dst = text(child).split(".")[-1]
                    edges.append(SymbolEdge(parent_symbol, dst, "imports", EDGE_WEIGHTS["imports"]))
        if node_type == "call":
            fn = node.child_by_field_name("function")
            if fn is not None:
                dst = text(fn).split(".")[-1]
                edges.append(SymbolEdge(parent_symbol, dst, "calls", EDGE_WEIGHTS["calls"]))
        if node_type in {"call_expression"}:
            fn = node.child_by_field_name("function")
            if fn is not None:
                dst = text(fn).split(".")[-1]
                edges.append(SymbolEdge(parent_symbol, dst, "calls", EDGE_WEIGHTS["calls"]))
        for child in node.children:
            walk(child, parent_symbol)

    walk(tree.root_node, module_name)
    return ExtractedSymbols(nodes, edges)
```

- [x] **Step 3: Implement graph persistence**

Create `scripts/cbv/graph.py`:

```python
from __future__ import annotations

from cbv.symbols import SymbolEdge, SymbolNode


def insert_nodes(conn, nodes: list[SymbolNode]) -> dict[str, int]:
    ids: dict[str, int] = {}
    for n in nodes:
        parent_id = ids.get(n.parent_name or "")
        cur = conn.execute(
            "INSERT INTO nodes (kind, name, short_name, file_path, start_line, end_line, signature, parent_id, chunk_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (n.kind, n.name, n.short_name, n.file_path, n.start_line, n.end_line,
             n.signature, parent_id, n.chunk_id),
        )
        ids[n.name] = int(cur.lastrowid)
    return ids


def insert_edges(conn, edges: list[SymbolEdge], ids: dict[str, int]) -> int:
    by_short = {}
    for name, node_id in ids.items():
        by_short.setdefault(name.rsplit("::", 1)[-1], node_id)
    written = 0
    for e in edges:
        src = ids.get(e.src_name) or by_short.get(e.src_name)
        dst = ids.get(e.dst_name) or by_short.get(e.dst_name)
        if src is None or dst is None or src == dst:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO edges (src, dst, kind, weight, metadata) VALUES (?, ?, ?, ?, ?)",
            (src, dst, e.kind, e.weight, e.metadata),
        )
        written += 1
    return written
```

- [x] **Step 4: Wire vectorize**

In `vectorize.py`, keep a mapping from stored chunks to parsed source files. After chunks and embeddings are inserted, parse supported files again and write nodes/edges. Link a symbol node to the first chunk in the same file whose byte range contains the node start byte.

Implementation rule: if symbol extraction raises for one file, append `symbol extraction failed for <file>: <error>` to `warnings` and keep indexing.

- [x] **Step 5: Verify metadata counts**

Update `_write_meta` call to receive actual counts and write:

```python
db.write_meta(conn, "total_nodes_symbol", str(nodes_symbol))
db.write_meta(conn, "total_edges_symbol", str(edges_symbol))
```

Update summary:

```python
"nodes_symbol": nodes_symbol,
"edges_symbol": edges_symbol,
```

- [x] **Step 6: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_symbols.py tests\unit\test_graph.py tests\integration\test_full_index.py -v
```

Expected: selected tests pass; integration asserts `nodes_symbol > 0` and `edges_symbol > 0`.

Commit:

```bash
git add scripts/cbv/symbols.py scripts/cbv/graph.py scripts/cbv/commands/vectorize.py tests/unit/test_symbols.py tests/unit/test_graph.py tests/integration/test_full_index.py
git commit -m "slice 3 t2: populate symbol graph"
```

### Task 2A: Spec-complete tags.scm-backed symbol extraction

**Files:**
- Modify: `scripts/cbv/symbols.py`
- Create: `scripts/cbv/tag_queries.py`
- Create: `scripts/cbv/tag_queries/python.scm`
- Create: `scripts/cbv/tag_queries/javascript.scm`
- Create: `scripts/cbv/tag_queries/typescript.scm`
- Create: `scripts/cbv/tag_queries/tsx.scm`
- Create: `scripts/cbv/tag_queries/go.scm`
- Create: `scripts/cbv/tag_queries/rust.scm`
- Create: `scripts/cbv/tag_queries/java.scm`
- Create: `scripts/cbv/tag_queries/c.scm`
- Create: `scripts/cbv/tag_queries/cpp.scm`
- Create: `scripts/cbv/tag_queries/ruby.scm`
- Create: `scripts/cbv/tag_queries/csharp.scm`
- Create: `tests/fixtures/polyglot-mini/`
- Modify: `tests/unit/test_symbols.py`
- Modify: `tests/integration/test_full_index.py`

- [x] **Step 1: Add failing Tier-A symbol extraction tests**

Add parametrized coverage to `tests/unit/test_symbols.py`:

```python
import pytest


@pytest.mark.parametrize(
    "language, filename, source, expected_defs, expected_edges",
    [
        ("python", "pkg/auth.py", b"import os\nclass Auth:\n    def login(self):\n        return os.getenv('X')\n", {"Auth", "login"}, {"imports", "calls", "contains"}),
        ("javascript", "util.js", b"import { snakeCase } from './fmt.js';\nexport function camelCase(x) { return snakeCase(x); }\n", {"camelCase"}, {"imports", "calls"}),
        ("typescript", "svc.ts", b"interface User { name: string }\nfunction loadUser(): User { return fetchUser(); }\n", {"User", "loadUser"}, {"calls"}),
        ("tsx", "view.tsx", b"export function Login() { return <button onClick={submit}>Go</button>; }\n", {"Login"}, {"references"}),
        ("go", "main.go", b"package main\nimport \"fmt\"\nfunc run() { fmt.Println(\"x\") }\n", {"run"}, {"imports", "calls"}),
        ("rust", "lib.rs", b"use crate::auth;\nstruct User;\nfn login() { auth::check(); }\n", {"User", "login"}, {"imports", "calls"}),
        ("java", "Auth.java", b"import java.util.List; class Auth { void login() { check(); } }\n", {"Auth", "login"}, {"imports", "calls"}),
        ("c", "auth.c", b"#include <stdio.h>\nint login() { return check(); }\n", {"login"}, {"imports", "calls"}),
        ("cpp", "auth.cpp", b"#include <vector>\nclass Auth {}; int login() { return check(); }\n", {"Auth", "login"}, {"imports", "calls"}),
        ("ruby", "auth.rb", b"require 'json'\ndef login\n  check\nend\n", {"login"}, {"imports", "calls"}),
        ("csharp", "Auth.cs", b"using System; class Auth { void Login() { Check(); } }\n", {"Auth", "Login"}, {"imports", "calls"}),
    ],
)
def test_tier_a_tags_extract_defs_and_edges(language, filename, source, expected_defs, expected_edges):
    lang = parser.language_for_name(language)
    tree = parser.parse(source, lang)
    extracted = symbols.extract_symbols(Path(filename), language, source, tree)
    short_names = {n.short_name for n in extracted.nodes}
    edge_kinds = {e.kind for e in extracted.edges}
    assert expected_defs <= short_names
    assert expected_edges <= edge_kinds
```

- [x] **Step 2: Run test and verify failure**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_symbols.py::test_tier_a_tags_extract_defs_and_edges -v
```

Expected: FAIL for unsupported language query/capture coverage.

- [x] **Step 3: Create query loader**

Create `scripts/cbv/tag_queries.py`:

```python
from __future__ import annotations

from functools import lru_cache
from importlib import resources


CAPTURE_TO_NODE_KIND = {
    "definition.class": "class",
    "definition.function": "function",
    "definition.method": "method",
    "definition.variable": "variable",
    "definition.module": "module",
}


CAPTURE_TO_EDGE_KIND = {
    "reference.call": "calls",
    "reference.import": "imports",
    "reference.inherits": "inherits",
    "reference.identifier": "references",
}


@lru_cache(maxsize=None)
def query_source(language_name: str) -> str:
    return resources.files("cbv.tag_queries").joinpath(f"{language_name}.scm").read_text(encoding="utf-8")
```

Also create `scripts/cbv/tag_queries/__init__.py` as an empty package marker.

- [x] **Step 4: Add query files**

Each `*.scm` file must expose captures using only these names:

```scheme
@definition.class
@definition.function
@definition.method
@definition.variable
@definition.module
@reference.call
@reference.import
@reference.inherits
@reference.identifier
```

Use tree-sitter-language-pack's query API and the language-specific node names validated by `tests/unit/test_cast_chunker.py`. Keep query files small and explicit; do not depend on external runtime downloads.

- [x] **Step 5: Update `symbols.extract_symbols` to execute queries**

Implementation requirements:
- Load the tree-sitter `Language` object used by `parser.parse`.
- Compile the language query from `tag_queries.query_source(language)`.
- For every `definition.*` capture, create a `SymbolNode` with fully-qualified `name`, `short_name`, file path, lines, signature, `parent_name`, and eventual `chunk_id`.
- For every `reference.*` capture, create a `SymbolEdge` with the nearest enclosing definition as `src_name`, the captured identifier as `dst_name`, and weight from `EDGE_WEIGHTS`.
- Emit `contains` edges from file -> class/function and class -> method based on AST nesting.
- Resolve same-file references by exact `short_name`; resolve cross-file references by `short_name` + compatible kind, preferring same directory/package prefix. Leave ambiguous references unresolved rather than inventing edges.
- Extract `tests`, `documents`, and `mentions` edges only when source file paths or comment/doc nodes make that relationship explicit.

- [x] **Step 6: Add integration assertions**

In `tests/integration/test_full_index.py`, add assertions that the indexed simple fixture contains:

```python
assert conn.execute("SELECT COUNT(*) FROM nodes WHERE kind IN ('file','class','function','method')").fetchone()[0] > 0
assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind IN ('contains','calls','imports','references')").fetchone()[0] > 0
assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind='calls'").fetchone()[0] > 0
```

- [x] **Step 7: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_symbols.py tests\unit\test_graph.py tests\integration\test_full_index.py -v
```

Expected: Tier-A extraction tests pass; fixture integration has nonzero symbol nodes and symbolic edges.

Commit:

```bash
git add scripts/cbv/symbols.py scripts/cbv/tag_queries.py scripts/cbv/tag_queries tests/unit/test_symbols.py tests/integration/test_full_index.py
git commit -m "slice 3 t2a: complete tags-based tier-a symbol extraction"
```

### Task 3: Query router, fast lane, and graph expansion

**Files:**
- Create: `scripts/cbv/query_router.py`
- Create: `tests/unit/test_query_router.py`
- Modify: `scripts/cbv/cli.py`
- Modify: `scripts/cbv/commands/query.py`
- Create: `tests/integration/test_query_lanes.py`

- [x] **Step 1: Write router tests**

Create `tests/unit/test_query_router.py`:

```python
from cbv import query_router


def test_identifier_routes_fast():
    assert query_router.route("authenticate_user") == "fast"
    assert query_router.route("where is authenticate_user") == "fast"


def test_natural_language_routes_full():
    assert query_router.route("how does login authenticate users") == "full"


def test_forced_lane_wins():
    assert query_router.route("authenticate_user", forced="full") == "full"
    assert query_router.route("how does auth work", forced="fast") == "fast"
```

- [x] **Step 2: Add `--lane` CLI argument**

In `cli.py`, add:

```python
pq.add_argument("--lane", choices=("auto", "fast", "full"), default="auto",
                help="query lane: auto, fast, or full (default auto)")
```

- [x] **Step 3: Implement router**

Create `scripts/cbv/query_router.py`:

```python
from __future__ import annotations

import re

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def route(query: str, forced: str = "auto") -> str:
    if forced in {"fast", "full"}:
        return forced
    q = query.strip()
    lowered = q.lower()
    if q.startswith("regex:"):
        return "fast"
    for prefix in ("find ", "where is "):
        if lowered.startswith(prefix) and IDENT.match(q[len(prefix):].strip()):
            return "fast"
    if IDENT.match(q):
        return "fast"
    if len(q.split()) < 4 and all(IDENT.match(part) for part in q.split()):
        return "fast"
    return "full"
```

- [x] **Step 4: Refactor query into lane helpers**

In `query.py`, keep `_bm25`, `_dense`, and `_rrf`. Add:

```python
def _symbol_exact(conn, query: str, *, limit: int) -> dict[int, float]:
    q = query.strip().split()[-1]
    rows = conn.execute(
        "SELECT DISTINCT chunk_id FROM nodes "
        "WHERE chunk_id IS NOT NULL AND kind != 'block' "
        "AND (short_name = ? OR name = ?) LIMIT ?",
        (q, q, limit),
    ).fetchall()
    return {int(row[0]): float(limit - idx) for idx, row in enumerate(rows)}


def _trigram(conn, query: str, *, limit: int) -> dict[int, float]:
    from cbv import identifiers
    grams = sorted(identifiers.trigrams(query.strip().split()[-1]))
    if not grams:
        return {}
    placeholders = ",".join("?" for _ in grams)
    rows = conn.execute(
        f"SELECT chunk_id, SUM(occurrences) AS score FROM symbol_trigrams "
        f"WHERE trigram IN ({placeholders}) GROUP BY chunk_id "
        f"ORDER BY score DESC LIMIT ?",
        (*grams, limit),
    ).fetchall()
    return {int(row[0]): float(row[1]) for row in rows}


def _graph_expand(conn, seed_chunk_ids: list[int], *, per_node: int = 3) -> dict[int, float]:
    if not seed_chunk_ids:
        return {}
    placeholders = ",".join("?" for _ in seed_chunk_ids)
    rows = conn.execute(
        f"SELECT DISTINCT neighbor.chunk_id, edge.weight "
        f"FROM nodes seed "
        f"JOIN edges edge ON edge.src = seed.id OR edge.dst = seed.id "
        f"JOIN nodes neighbor ON neighbor.id = CASE WHEN edge.src = seed.id THEN edge.dst ELSE edge.src END "
        f"WHERE seed.chunk_id IN ({placeholders}) AND neighbor.chunk_id IS NOT NULL "
        f"LIMIT ?",
        (*seed_chunk_ids, max(1, len(seed_chunk_ids) * per_node)),
    ).fetchall()
    return {int(row[0]): float(row[1]) for row in rows}
```

Use lane behavior:

```python
lane = query_router.route(ns.question, ns.lane)
if lane == "fast":
    fused = _rrf([_symbol_exact(conn, ns.question, limit=50),
                  _trigram(conn, ns.question, limit=50),
                  _bm25(conn, ns.question, limit=50)], k=RRF_K)
else:
    bm25_hits = _bm25(conn, ns.question, limit=50)
    dense_hits = _dense(conn, q_int8, limit=50)
    sym_hits = _symbol_exact(conn, ns.question, limit=50)
    seed = _rrf([bm25_hits, dense_hits, sym_hits], k=RRF_K)
    expansion = _graph_expand(conn, [cid for cid, _, _ in seed[:20]])
    fused = _rrf([bm25_hits, dense_hits, sym_hits, expansion], k=RRF_K)
```

Set:

```python
"pipeline_used": lane,
"expansion_size": len(expansion) if lane == "full" else 0,
```

- [x] **Step 5: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_query_router.py tests\unit\test_query_cmd.py tests\integration\test_query_lanes.py -v
```

Expected: fast-lane query returns `pipeline_used == "fast"` and full-lane query returns `pipeline_used == "full"` with nonzero `expansion_size` on the fixture.

Commit:

```bash
git add scripts/cbv/query_router.py scripts/cbv/cli.py scripts/cbv/commands/query.py tests/unit/test_query_router.py tests/unit/test_query_cmd.py tests/integration/test_query_lanes.py
git commit -m "slice 3 t3: add query lanes and graph expansion"
```

### Task 4: Checkpoint verification

**Completion tracking directive:** After this checkpoint passes, edit this plan to mark all safely completed Milestone 1 tasks and checkpoint steps complete before starting Milestone 2.

- [x] **Step 1: Run full suite**

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests/ -v
```

Expected: all tests pass, one network clone test may remain skipped.

- [x] **Step 2: Run smoke**

```powershell
$ErrorActionPreference='Stop'
$env:CBV_STUB_EMBEDDER='1'
$env:CODEBASE_VECTORIZER_HOME="$env:TEMP\cbv-final-slice3-smoke"
$env:PYTHONPATH=(Resolve-Path .\scripts).Path
Remove-Item -Recurse -Force $env:CODEBASE_VECTORIZER_HOME -ErrorAction SilentlyContinue
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv vectorize tests\fixtures\simple-python
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv query simple-python "authenticate_user" --lane fast --top-k 3
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv query simple-python "how does login authenticate users" --lane full --top-k 3
Remove-Item -Recurse -Force $env:CODEBASE_VECTORIZER_HOME -ErrorAction SilentlyContinue
```

Expected: vectorize summary has `nodes_symbol > 0`, `edges_symbol > 0`; first query reports `pipeline_used: fast`; second reports `pipeline_used: full`.

- [x] **Step 3: Commit only if files changed during fixes**

```bash
git status --short
git add <changed-files>
git commit -m "slice 3 final: stabilize symbol-aware retrieval"
```

---

## Milestone 2: `codebase-relate`, Stats, and PageRank

After this milestone, users can ask explicit structural questions without forcing the normal query path to overload every response.

**Completion tracking directive:** At the end of each Task 5, Task 5A, and Task 6 verification block, if the task is safe to designate as done, edit this plan and mark the task checklist complete. Keep incomplete subtasks unchecked even if later tasks pass.

### Task 5: PageRank helper and `stats`

This task computes the global PageRank stored on `nodes.pagerank`. It is necessary but not sufficient for the spec's retrieval path. Task 5A adds query-time Personalized PageRank and must land before the full lane can be called spec-complete.

**Files:**
- Modify: `scripts/requirements.txt` (`networkx>=3.2`)
- Modify: `scripts/bootstrap.py` dependency probe (`networkx`)
- Modify: `scripts/cbv/graph.py`
- Create: `scripts/cbv/commands/stats.py`
- Modify: `scripts/cbv/cli.py`
- Create: `tests/unit/test_graph.py`
- Create: `tests/unit/test_stats_cmd.py`

- [x] **Step 1: Add dependency and probe**

Append:

```text
networkx>=3.2
```

Add `networkx` to the bootstrap core probe import list.

- [x] **Step 2: Add PageRank function**

In `graph.py`:

```python
def compute_pagerank(conn) -> int:
    import networkx as nx

    g = nx.DiGraph()
    for node_id, in conn.execute("SELECT id FROM nodes WHERE kind != 'block'"):
        g.add_node(int(node_id))
    for src, dst, weight in conn.execute(
        "SELECT src, dst, weight FROM edges WHERE kind IN "
        "('defines','calls','imports','inherits','references','contains','tests','documents','mentions')"
    ):
        g.add_edge(int(src), int(dst), weight=float(weight))
    scores = nx.pagerank(g, weight="weight") if g.number_of_nodes() else {}
    with conn:
        for node_id, score in scores.items():
            conn.execute("UPDATE nodes SET pagerank = ? WHERE id = ?", (float(score), int(node_id)))
    return len(scores)
```

- [x] **Step 3: Add `stats` command**

Create `scripts/cbv/commands/stats.py`:

```python
from __future__ import annotations

import argparse
import json
import sys

from cbv import db, paths


def run(ns: argparse.Namespace) -> int:
    repo_dir = paths.find_repo(ns.repo)
    if repo_dir is None:
        print(f"No index found for repo {ns.repo!r}.", file=sys.stderr)
        return 2
    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        db.assert_schema_v1(conn)
        counts = {
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "clusters": conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0],
        }
        top_nodes = [
            {"name": name, "kind": kind, "pagerank": round(float(pr), 6)}
            for name, kind, pr in conn.execute(
                "SELECT name, kind, pagerank FROM nodes ORDER BY pagerank DESC LIMIT ?",
                (ns.top_k,),
            )
        ]
        print(json.dumps({"repo": ns.repo, "counts": counts, "top_nodes": top_nodes}), flush=True)
        return 0
    finally:
        conn.close()
```

Add CLI:

```python
ps = sub.add_parser("stats", help="Print counts and top PageRank nodes")
ps.add_argument("repo")
ps.add_argument("--top-k", type=int, default=10)
```

Add dispatch entry for `stats`.

- [x] **Step 4: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_graph.py tests\unit\test_stats_cmd.py tests\unit\test_bootstrap_dispatch.py -v
```

Commit:

```bash
git add scripts/requirements.txt scripts/bootstrap.py scripts/cbv/graph.py scripts/cbv/cli.py scripts/cbv/commands/stats.py tests/unit/test_graph.py tests/unit/test_stats_cmd.py tests/unit/test_bootstrap_dispatch.py
git commit -m "slice 4 t1: compute pagerank and expose stats"
```

### Task 5A: Query-time Personalized PageRank for the full lane

**Files:**
- Modify: `scripts/cbv/graph.py`
- Modify: `scripts/cbv/commands/query.py`
- Create: `tests/unit/test_retrieval.py`
- Modify: `tests/integration/test_query_lanes.py`

- [x] **Step 1: Write failing PPR tests**

Create `tests/unit/test_retrieval.py`:

```python
import sqlite3

from cbv import db, graph


def _node(conn, name, chunk_id):
    cur = conn.execute(
        "INSERT INTO nodes (kind, name, short_name, file_path, chunk_id) VALUES ('function', ?, ?, 'pkg/a.py', ?)",
        (name, name.rsplit("::", 1)[-1], chunk_id),
    )
    return cur.lastrowid


def test_personalized_pagerank_boosts_seed_neighborhood(tmp_path):
    conn = db.open_db(tmp_path / "idx.sqlite")
    db.init_schema(conn)
    with conn:
        for cid in range(1, 5):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, start_line, end_line, start_byte, end_byte, content, content_hash, token_count) "
                "VALUES (?, 'pkg/a.py', 'python', 'function', 1, 1, 0, 1, 'x', ?, 1)",
                (cid, f"h{cid}"),
            )
        a = _node(conn, "pkg/a.py::seed", 1)
        b = _node(conn, "pkg/a.py::callee", 2)
        c = _node(conn, "pkg/a.py::far", 3)
        conn.execute("INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'calls', 3.0)", (a, b))
        conn.execute("INSERT INTO edges (src, dst, kind, weight) VALUES (?, ?, 'calls', 3.0)", (c, b))
    scores = graph.personalized_pagerank(conn, seed_chunk_ids=[1], iterations=10)
    assert scores[2] > scores.get(3, 0.0)
```

- [x] **Step 2: Implement PPR helper**

In `scripts/cbv/graph.py`, add:

```python
def personalized_pagerank(conn, seed_chunk_ids: list[int], *, iterations: int = 10) -> dict[int, float]:
    import networkx as nx

    seed_chunk_ids = [int(x) for x in seed_chunk_ids]
    if not seed_chunk_ids:
        return {}
    rows = conn.execute(
        "SELECT id, chunk_id FROM nodes WHERE kind != 'block' AND chunk_id IS NOT NULL"
    ).fetchall()
    node_to_chunk = {int(node_id): int(chunk_id) for node_id, chunk_id in rows}
    g = nx.DiGraph()
    g.add_nodes_from(node_to_chunk)
    for src, dst, weight in conn.execute(
        "SELECT src, dst, weight FROM edges WHERE kind IN "
        "('defines','calls','imports','inherits','references','contains','tests','documents','mentions')"
    ):
        if int(src) in node_to_chunk and int(dst) in node_to_chunk:
            g.add_edge(int(src), int(dst), weight=float(weight))
    if not g:
        return {}
    seed_nodes = {node for node, chunk_id in node_to_chunk.items() if chunk_id in seed_chunk_ids}
    if not seed_nodes:
        return {}
    base = 0.1
    personalization = {
        node: (1.0 if node in seed_nodes else base)
        for node in g.nodes
    }
    scores = nx.pagerank(g, personalization=personalization, max_iter=iterations, weight="weight")
    chunk_scores: dict[int, float] = {}
    for node_id, score in scores.items():
        chunk_id = node_to_chunk[node_id]
        chunk_scores[chunk_id] = max(chunk_scores.get(chunk_id, 0.0), float(score))
    return chunk_scores
```

- [x] **Step 3: Use PPR in full lane**

In `query.py`, after BM25/dense/symbol seed fusion and 1-hop expansion:

```python
seed_ids = [cid for cid, _, _ in seed[:20]]
expansion = _graph_expand(conn, seed_ids)
ppr_hits = graph.personalized_pagerank(conn, seed_ids, iterations=10)
fused = _rrf([bm25_hits, dense_hits, sym_hits, expansion, ppr_hits], k=RRF_K)
```

Update `why_this_was_returned` source tags so PPR-sourced candidates can report `ppr` alongside `bm25`, `dense`, `symbol`, and `graph`.

- [x] **Step 4: Verify full-lane JSON**

In `tests/integration/test_query_lanes.py`, assert:

```python
assert blob["pipeline_used"] == "full"
assert blob["expansion_size"] > 0
assert any("ppr" in r["why_this_was_returned"] or "graph" in r["why_this_was_returned"] for r in blob["results"])
```

- [x] **Step 5: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_retrieval.py tests\integration\test_query_lanes.py tests\unit\test_query_cmd.py -v
```

Expected: PPR ranks graph-neighborhood chunks above unrelated nodes and full-lane query output records graph/PPR involvement.

Commit:

```bash
git add scripts/cbv/graph.py scripts/cbv/commands/query.py tests/unit/test_retrieval.py tests/integration/test_query_lanes.py tests/unit/test_query_cmd.py
git commit -m "slice 4 t1a: add personalized pagerank to full lane"
```

### Task 6: `relate` command and skill

**Files:**
- Create: `scripts/cbv/commands/relate.py`
- Create: `scripts/cbv/commands/graph_cmd.py`
- Create: `scripts/cbv/commands/flow_cmd.py`
- Modify: `scripts/cbv/cli.py`
- Create: `skills/codebase-relate/SKILL.md`
- Create: `tests/integration/test_relate_cmd.py`

- [x] **Step 1: Add CLI surface**

Add parser:

```python
pr = sub.add_parser("relate", help="Run graph and flow relationship queries")
pr.add_argument("repo")
pr.add_argument(
    "verb",
    choices=(
        "callers", "callees", "inheritance-chain", "neighbors",
        "concept-cluster", "pagerank-top", "shortest-path",
        "paths-through", "reaching-definitions", "reachable-uses",
        "conditions-for",
    ),
)
pr.add_argument("args", nargs="*")
pr.add_argument("--hops", type=int, default=1)
pr.add_argument("--top-k", type=int, default=10)
```

Add dispatch entry for `relate`.

Add spec-compatible aliases:

```python
pg = sub.add_parser("graph", help="Print symbol neighborhood")
pg.add_argument("repo")
pg.add_argument("symbol")
pg.add_argument("--hops", type=int, default=1)
pg.add_argument("--top-k", type=int, default=10)

pf = sub.add_parser("flow", help="Print CFG/DFG for a function")
pf.add_argument("repo")
pf.add_argument("function")
pf.add_argument("--top-k", type=int, default=20)
```

`graph` delegates to `relate neighbors`; `flow` delegates to `relate paths-through`.

- [x] **Step 2: Implement relate**

Create `scripts/cbv/commands/relate.py`:

```python
from __future__ import annotations

import argparse
import json
import sys

from cbv import db, paths


def run(ns: argparse.Namespace) -> int:
    repo_dir = paths.find_repo(ns.repo)
    if repo_dir is None:
        print(f"No index found for repo {ns.repo!r}.", file=sys.stderr)
        return 2
    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        db.assert_schema_v1(conn)
        if ns.verb == "pagerank-top":
            rows = conn.execute(
                "SELECT name, short_name, kind, file_path, start_line, end_line, pagerank "
                "FROM nodes WHERE kind != 'block' ORDER BY pagerank DESC LIMIT ?",
                (ns.top_k,),
            ).fetchall()
        elif ns.verb in {"callers", "callees", "neighbors"}:
            if not ns.args:
                print(f"{ns.verb} requires a symbol argument", file=sys.stderr)
                return 2
            symbol = ns.args[0]
            direction = "incoming" if ns.verb == "callers" else "outgoing"
            rows = _neighbors(conn, symbol, direction=direction, top_k=ns.top_k)
        elif ns.verb == "shortest-path":
            if len(ns.args) != 2:
                print("shortest-path requires <from_symbol> <to_symbol>", file=sys.stderr)
                return 2
            rows = _shortest_path(conn, ns.args[0], ns.args[1], hops=ns.hops)
        else:
            rows = []
        print(json.dumps({"repo": ns.repo, "verb": ns.verb, "results": _format(rows)}), flush=True)
        return 0
    finally:
        conn.close()


def _neighbors(conn, symbol: str, *, direction: str, top_k: int):
    if direction == "incoming":
        sql = (
            "SELECT src.name, src.short_name, src.kind, src.file_path, src.start_line, src.end_line, src.pagerank "
            "FROM nodes dst JOIN edges e ON e.dst = dst.id JOIN nodes src ON src.id = e.src "
            "WHERE dst.short_name = ? OR dst.name = ? ORDER BY src.pagerank DESC LIMIT ?"
        )
    else:
        sql = (
            "SELECT dst.name, dst.short_name, dst.kind, dst.file_path, dst.start_line, dst.end_line, dst.pagerank "
            "FROM nodes src JOIN edges e ON e.src = src.id JOIN nodes dst ON dst.id = e.dst "
            "WHERE src.short_name = ? OR src.name = ? ORDER BY dst.pagerank DESC LIMIT ?"
        )
    return conn.execute(sql, (symbol, symbol, top_k)).fetchall()


def _shortest_path(conn, start: str, end: str, *, hops: int):
    return conn.execute(
        "WITH RECURSIVE walk(id, path, depth) AS ("
        "  SELECT id, name, 0 FROM nodes WHERE short_name = ? OR name = ?"
        "  UNION ALL "
        "  SELECT e.dst, walk.path || ' -> ' || n.name, walk.depth + 1 "
        "  FROM walk JOIN edges e ON e.src = walk.id JOIN nodes n ON n.id = e.dst "
        "  WHERE walk.depth < ?"
        ") SELECT n.name, n.short_name, n.kind, n.file_path, n.start_line, n.end_line, n.pagerank "
        "FROM walk JOIN nodes n ON n.id = walk.id WHERE n.short_name = ? OR n.name = ? LIMIT 1",
        (start, start, hops, end, end),
    ).fetchall()


def _format(rows):
    return [
        {
            "name": r[0], "short_name": r[1], "kind": r[2], "file_relative": r[3],
            "start_line": r[4], "end_line": r[5], "score": round(float(r[6] or 0.0), 6),
        }
        for r in rows
    ]
```

- [x] **Step 2A: Complete every spec-listed relate verb**

Before this task is complete, `relate.py` must implement all verbs listed in the CLI parser, not only caller/callee neighbors:

```python
RELATE_VERBS = {
    "callers", "callees", "inheritance-chain", "neighbors",
    "concept-cluster", "pagerank-top", "shortest-path",
    "paths-through", "reaching-definitions", "reachable-uses",
    "conditions-for",
}
```

Implementation requirements:
- `inheritance-chain` uses recursive CTEs over `edges.kind='inherits'`.
- `neighbors` accepts `--hops` and returns PageRank-ranked bounded graph walks.
- `concept-cluster` queries `clusters` and `chunk_clusters`; before Task 11 lands it returns a clean "clusters not indexed" JSON result rather than an error.
- `paths-through`, `reaching-definitions`, `reachable-uses`, and `conditions-for` query block nodes and `controls`/`dataflow`/`guards` edges; before Task 10 lands they return a clean "flow not indexed" JSON result rather than an error.
- Every verb returns the same top-level JSON keys: `repo`, `verb`, `query`, `results`, `warnings`.

- [x] **Step 3: Add skill**

Create `skills/codebase-relate/SKILL.md`:

```markdown
---
name: codebase-relate
description: Use when the user asks graph, caller/callee, neighbor, shortest-path, concept, or flow questions about a repository already indexed by codebase-vectorizer.
---

# codebase-relate

Use `scripts/run.ps1 relate <repo> <verb> ...` on Windows or `scripts/run.sh relate <repo> <verb> ...` on POSIX.

Supported verbs:
- `callers <symbol>`
- `callees <symbol>`
- `inheritance-chain <symbol>`
- `neighbors <symbol>`
- `concept-cluster <query-or-label>`
- `pagerank-top`
- `shortest-path <from_symbol> <to_symbol> --hops N`
- `paths-through <function> [from_line] [to_line]`
- `reaching-definitions <variable_use_site>`
- `reachable-uses <variable_def_site>`
- `conditions-for <symbol_or_state>`

Read returned file ranges before answering. If no repo is indexed, ask the user to run `vectorize-repo` first.
```

- [x] **Step 4: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\integration\test_relate_cmd.py tests\unit\test_bootstrap_dispatch.py -v
```

Commit:

```bash
git add scripts/cbv/commands/relate.py scripts/cbv/commands/graph_cmd.py scripts/cbv/commands/flow_cmd.py scripts/cbv/cli.py skills/codebase-relate/SKILL.md tests/integration/test_relate_cmd.py tests/unit/test_bootstrap_dispatch.py
git commit -m "slice 4 t2: add codebase-relate graph queries"
```

---

## Milestone 3: Reranking, Confidence, and Refined Queries

This milestone improves answer ordering without changing indexing.

**Completion tracking directive:** When Task 7's reranker tests and commit succeed, immediately edit this plan to mark Task 7 complete. Do this before beginning cache or incremental indexing work.

### Task 7: Reranker adapter with deterministic test path

**Files:**
- Modify: `scripts/requirements.txt` (`sentence-transformers>=3.0`)
- Modify: `scripts/bootstrap.py`
- Create: `scripts/cbv/reranker.py`
- Create: `tests/unit/test_reranker.py`
- Modify: `scripts/cbv/commands/query.py`
- Modify: `tests/unit/test_query_cmd.py`

- [x] **Step 1: Implement reranker adapter**

Create `scripts/cbv/reranker.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_RERANKER = "mixedbread-ai/mxbai-rerank-large-v2"


class Reranker:
    model_id = DEFAULT_RERANKER

    def score(self, query: str, passages: list[str]) -> list[float]:
        raise NotImplementedError


class StubReranker(Reranker):
    model_id = "stub://lexical-overlap-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = {p.lower() for p in query.split()}
        return [float(len(q & {p.lower().strip(".,:;()[]{}") for p in passage.split()}))
                for passage in passages]


class SentenceTransformerReranker(Reranker):
    def __init__(self, model_id: str = DEFAULT_RERANKER) -> None:
        from sentence_transformers import CrossEncoder
        self.model_id = model_id
        self._model = CrossEncoder(model_id)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(x) for x in self._model.predict([(query, p[:512]) for p in passages])]


def make_reranker() -> Reranker:
    if os.environ.get("CBV_STUB_RERANKER") == "1" or os.environ.get("CBV_STUB_EMBEDDER") == "1":
        return StubReranker()
    return SentenceTransformerReranker()
```

- [x] **Step 2: Wire reranking and confidence**

In `query.py`, after candidate chunks are materialized and before final formatting:

```python
from cbv import reranker

...

rr = reranker.make_reranker()
scores = rr.score(ns.question, [row["preview"] for row in candidate_rows])
for row, score in zip(candidate_rows, scores):
    row["score"] = float(score)
candidate_rows.sort(key=lambda row: row["score"], reverse=True)
final_rows = candidate_rows[:ns.top_k]
refined_queries = _refined_queries(ns.question, final_rows)
```

Add:

```python
def _refined_queries(query: str, rows: list[dict]) -> list[str]:
    if not rows:
        return [query]
    top_score = float(rows[0].get("score", 0.0))
    if top_score >= 1.0:
        return []
    names = [r.get("name") for r in rows[:5] if r.get("name")]
    return [f"{query} {name}" for name in names[:3]]
```

Write `reranker_model` meta during vectorize only after the first query is not possible; keep `meta.reranker_model` empty at index time and report reranker in query output as:

```python
"reranker_model": rr.model_id,
```

- [x] **Step 3: Verify and commit**

Run:

```powershell
$env:CBV_STUB_RERANKER='1'
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_reranker.py tests\unit\test_query_cmd.py -v
Remove-Item Env:\CBV_STUB_RERANKER -ErrorAction SilentlyContinue
```

Commit:

```bash
git add scripts/requirements.txt scripts/bootstrap.py scripts/cbv/reranker.py scripts/cbv/commands/query.py tests/unit/test_reranker.py tests/unit/test_query_cmd.py
git commit -m "slice 5 t1: rerank query candidates and emit confidence hints"
```

---

## Milestone 4: Embedding Cache and Incremental Indexing

This is the main performance-completion milestone. It should preserve the existing query behavior while making repeat indexing cheap.

**Completion tracking directive:** When Task 8 or Task 9 can be safely designated as done, edit this plan in the same session and mark the corresponding checklist items complete. Do not leave completion status only in terminal output.

### Task 8: Embedding cache

**Files:**
- Create: `scripts/cbv/cache.py`
- Create: `tests/unit/test_cache.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Modify: `tests/unit/test_vectorize_cmd.py`

- [x] **Step 1: Implement cache**

Create `scripts/cbv/cache.py`:

```python
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import numpy as np


def open_cache(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS embedding_cache ("
        "content_hash TEXT PRIMARY KEY, "
        "embedding BLOB NOT NULL, "
        "model_id TEXT NOT NULL, "
        "created_at INTEGER NOT NULL)"
    )
    return conn


def get(conn: sqlite3.Connection, content_hash: str, model_id: str) -> np.ndarray | None:
    row = conn.execute(
        "SELECT embedding FROM embedding_cache WHERE content_hash = ? AND model_id = ?",
        (content_hash, model_id),
    ).fetchone()
    if row is None:
        return None
    return np.frombuffer(row[0], dtype=np.int8).copy()


def put(conn: sqlite3.Connection, content_hash: str, model_id: str, embedding: np.ndarray) -> None:
    conn.execute(
        "INSERT INTO embedding_cache (content_hash, embedding, model_id, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(content_hash) DO UPDATE SET embedding = excluded.embedding, "
        "model_id = excluded.model_id, created_at = excluded.created_at",
        (content_hash, embedding.astype("int8").tobytes(), model_id, int(time.time())),
    )
```

- [x] **Step 2: Wire vectorize cache**

In `vectorize.py`, before embedding, open `paths.embedding_cache_path()` unless a future `--no-cache` flag is set. For each chunk, try `cache.get(content_hash, emb.model_id)`. Embed only misses. Compute:

```python
embedding_cache_hit_rate = hits / len(chunks_buf) if chunks_buf else 0.0
```

Write the hit rate to manifest and summary.

- [x] **Step 3: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_cache.py tests\unit\test_vectorize_cmd.py -v
```

Commit:

```bash
git add scripts/cbv/cache.py scripts/cbv/commands/vectorize.py tests/unit/test_cache.py tests/unit/test_vectorize_cmd.py
git commit -m "slice 6 t1: cache embeddings by content hash"
```

### Task 9: Merkle file table and incremental update mode

**Files:**
- Create: `scripts/cbv/incremental.py`
- Create: `tests/unit/test_incremental.py`
- Modify: `scripts/cbv/cli.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Create: `tests/integration/test_incremental.py`

- [x] **Step 1: Add CLI flags**

Add to `vectorize` parser:

```python
pv.add_argument("--update", action="store_true",
                help="update an existing index instead of rebuilding when possible")
pv.add_argument("--no-cache", action="store_true",
                help="disable cross-repo embedding cache for this run")
```

- [x] **Step 2: Implement delta planner**

Create `scripts/cbv/incremental.py`:

```python
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from cbv.walker import WalkEntry


@dataclass(frozen=True)
class Delta:
    added: set[str]
    modified: set[str]
    removed: set[str]
    unchanged: set[str]


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def merkle_root(items: dict[str, str]) -> str:
    h = hashlib.sha256()
    for rel, sha in sorted(items.items()):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(sha.encode("ascii"))
        h.update(b"\0")
    return h.hexdigest()


def plan_delta(conn, current: dict[str, str]) -> Delta:
    prior = {row[0]: row[1] for row in conn.execute("SELECT file_path, blob_sha FROM merkle_files")}
    cur_keys = set(current)
    prior_keys = set(prior)
    added = cur_keys - prior_keys
    removed = prior_keys - cur_keys
    modified = {k for k in cur_keys & prior_keys if current[k] != prior[k]}
    unchanged = (cur_keys & prior_keys) - modified
    return Delta(added, modified, removed, unchanged)


def write_merkle(conn, files: dict[str, tuple[str, int]]) -> None:
    now = int(time.time())
    conn.execute("DELETE FROM merkle_files")
    conn.executemany(
        "INSERT INTO merkle_files (file_path, blob_sha, size_bytes, last_indexed_at) VALUES (?, ?, ?, ?)",
        [(rel, sha, size, now) for rel, (sha, size) in sorted(files.items())],
    )
```

- [x] **Step 3: Update vectorize behavior**

When `--update` and `index.sqlite` exists:
- do not delete the DB,
- delete rows from `chunks` for removed and modified files,
- chunk/embed/write only added and modified files,
- leave unchanged files intact,
- rewrite `merkle_files`, counts, `indexed_at`, `commit_sha`, and `merkle_root_sha`.

When not `--update`, preserve current fresh rebuild behavior but also populate `merkle_files` and `merkle_root_sha`.

- [x] **Step 4: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_incremental.py tests\integration\test_incremental.py -v
```

Commit:

```bash
git add scripts/cbv/incremental.py scripts/cbv/cli.py scripts/cbv/commands/vectorize.py tests/unit/test_incremental.py tests/integration/test_incremental.py
git commit -m "slice 6 t2: add merkle incremental indexing"
```

---

## Milestone 5: Flow, Clusters, Architecture, and Bench

This milestone finishes the remaining spec surfaces. Keep these implementations intentionally small and deterministic first; final polish can deepen language coverage after the product is complete.

**Completion tracking directive:** Flow, clusters, architecture, and bench are spec-critical. Mark Task 10, Task 10A, Task 11, and Task 12 complete in this plan only after their verification commands pass and the implementation satisfies the spec authority section above.

### Task 10: Python CFG/DFG bootstrap for flow-heavy questions

This task creates the first working flow path. It is not the final completion bar. Task 10A must follow before flow is spec-complete.

**Files:**
- Create: `scripts/cbv/flow.py`
- Create: `tests/fixtures/flow-heavy/flow_app.py`
- Create: `tests/unit/test_flow.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Modify: `scripts/cbv/commands/relate.py`

- [x] **Step 1: Add flow fixture**

Create `tests/fixtures/flow-heavy/flow_app.py`:

```python
def decide(user, amount):
    approved = False
    if user.is_admin:
        approved = True
    elif amount < 100:
        approved = True
    return approved
```

- [x] **Step 2: Implement conservative Python flow extraction**

Create `scripts/cbv/flow.py`:

```python
from __future__ import annotations

import ast
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class FlowNode:
    name: str
    short_name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    parent_symbol: str


@dataclass(frozen=True)
class FlowEdge:
    src_name: str
    dst_name: str
    kind: str
    metadata: str | None


def extract_python_flow(file_path: str, source: str) -> tuple[list[FlowNode], list[FlowEdge]]:
    tree = ast.parse(source)
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        parent = f"{file_path}::{fn.name}"
        previous = None
        for idx, stmt in enumerate(fn.body, start=1):
            start = getattr(stmt, "lineno", fn.lineno)
            end = getattr(stmt, "end_lineno", start)
            name = f"{parent}#block_{idx}"
            signature = ast.get_source_segment(source, stmt) or type(stmt).__name__
            nodes.append(FlowNode(name, f"block_{idx}", file_path, start, end, signature, parent))
            if previous is not None:
                edges.append(FlowEdge(previous, name, "controls", None))
            previous = name
            if isinstance(stmt, ast.If):
                edges.append(FlowEdge(parent, name, "guards", json.dumps({"predicate": ast.unparse(stmt.test)})))
            assigned = [t.id for t in ast.walk(stmt) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)]
            used = [t.id for t in ast.walk(stmt) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Load)]
            for var in set(assigned) & set(used):
                edges.append(FlowEdge(name, name, "dataflow", json.dumps({"variable": var})))
    return nodes, edges
```

- [x] **Step 3: Wire vectorize and relate flow verbs**

For Python files, write `FlowNode` rows as `kind='block'`, `parent_id` pointing to the function node, and `FlowEdge` rows as `controls`, `guards`, or `dataflow`.

Extend `relate` verbs with:

```python
"paths-through", "reaching-definitions", "reachable-uses", "conditions-for"
```

For this bootstrap task, `conditions-for <symbol>` returns matching `guards` and `dataflow` metadata rows in the same function. Task 10A replaces this with the full CFG/DFG-backed path required by the spec.

- [x] **Step 4: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_flow.py tests\integration\test_relate_cmd.py -v
```

Commit:

```bash
git add scripts/cbv/flow.py scripts/cbv/commands/vectorize.py scripts/cbv/commands/relate.py tests/fixtures/flow-heavy tests/unit/test_flow.py tests/integration/test_relate_cmd.py
git commit -m "slice 7 t1: add python flow graph bootstrap"
```

### Task 10A: Spec-complete intra-procedural CFG/DFG coverage and flow relate verbs

**Files:**
- Modify: `scripts/cbv/flow.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Modify: `scripts/cbv/commands/relate.py`
- Modify: `tests/unit/test_flow.py`
- Modify: `tests/integration/test_relate_cmd.py`
- Create: `tests/fixtures/flow-heavy/go_flow.go`
- Create: `tests/fixtures/flow-heavy/js_flow.js`
- Create: `tests/fixtures/flow-heavy/ts_flow.ts`

- [x] **Step 1: Add failing CFG/DFG behavior tests**

Add tests that assert:

```python
def test_cfg_emits_true_false_loop_and_exit_blocks():
    # Python fixture includes if/else, loop, and early return.
    nodes, edges = flow.extract_flow("python", "flow.py", PY_SOURCE)
    assert any(e.kind == "controls" for e in edges)
    assert any(e.kind == "guards" and "is_admin" in (e.metadata or "") for e in edges)
    assert any("exit" in n.short_name for n in nodes)


def test_dfg_reaches_use_with_variable_metadata():
    nodes, edges = flow.extract_flow("python", "flow.py", PY_SOURCE)
    assert any(e.kind == "dataflow" and '"variable": "approved"' in (e.metadata or "") for e in edges)
```

Add parametrized best-effort coverage for Tier-A languages:

```python
@pytest.mark.parametrize("language, filename, source", [
    ("python", "flow.py", PY_SOURCE),
    ("javascript", "flow.js", JS_SOURCE),
    ("typescript", "flow.ts", TS_SOURCE),
    ("go", "flow.go", GO_SOURCE),
])
def test_tier_a_flow_extractors_do_not_fail_and_emit_blocks(language, filename, source):
    nodes, edges = flow.extract_flow(language, filename, source)
    assert nodes
    assert any(e.kind == "controls" for e in edges)
```

- [x] **Step 2: Generalize flow API**

Replace language-specific entrypoints with:

```python
def extract_flow(language: str, file_path: str, source: str) -> tuple[list[FlowNode], list[FlowEdge]]:
    ...
```

Requirements:
- Use Python `ast` for Python.
- Use tree-sitter AST traversal for JavaScript, TypeScript, TSX, Go, Rust, Java, C, C++, Ruby, and C# where grammars expose if/loop/return/assignment/call nodes.
- Emit at least function entry, statement/basic blocks, and exit blocks.
- Emit `controls` edges for sequential flow, branches, loop bodies, loop back-edges, and function exit.
- Emit `guards` edges with JSON predicate metadata for branch and loop conditions.
- Emit `dataflow` edges for intra-procedural def-use pairs where a definition reaches a use along the CFG.
- Unsupported or failed per-function extraction must append a warning and preserve symbol graph output.

- [x] **Step 3: Complete flow relate verbs**

`relate.py` must answer:
- `paths-through(function, [from_line, to_line])`: bounded CFG path sequences with guard predicates.
- `reaching-definitions(variable_use_site)`: backward DFG slice from use to definitions.
- `reachable-uses(variable_def_site)`: forward DFG slice from definition to uses.
- `conditions-for(symbol_or_state)`: guard predicates and dataflow paths that produce the target state.

Add JSON fields per result:

```json
{
  "file_relative": "pkg/auth.py",
  "function": "authenticate_user",
  "path": ["block_1", "block_2"],
  "guards": ["password_hash == expected"],
  "variables": ["password_hash"],
  "score": 1.0
}
```

- [x] **Step 4: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_flow.py tests\integration\test_relate_cmd.py -v
```

Expected: flow extraction emits block nodes plus `controls`, `guards`, and `dataflow`; every flow relate verb returns useful JSON on `flow-heavy`.

Commit:

```bash
git add scripts/cbv/flow.py scripts/cbv/commands/vectorize.py scripts/cbv/commands/relate.py tests/unit/test_flow.py tests/integration/test_relate_cmd.py tests/fixtures/flow-heavy
git commit -m "slice 7 t1a: complete intra-procedural flow extraction"
```

### Task 11: Concept clusters

This task must implement the spec's L4 path: UMAP dimensionality reduction, HDBSCAN clustering, soft memberships above threshold, centroid storage, and an LLM label path. Deterministic labels are allowed only when LLM labeling fails and must be accompanied by a warning.

**Files:**
- Modify: `scripts/requirements.txt` (`umap-learn>=0.5.5`, `hdbscan>=0.8.33`)
- Modify: `scripts/bootstrap.py`
- Create: `scripts/cbv/clusters.py`
- Create: `tests/unit/test_clusters.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Modify: `scripts/cbv/commands/relate.py`

- [ ] **Step 1: Implement cluster tests**

Add to `tests/unit/test_clusters.py`:

```python
import numpy as np

from cbv import clusters


def test_umap_hdbscan_cluster_embeddings_returns_labels_and_memberships():
    embeddings = np.vstack([
        np.ones((6, 8), dtype="float32"),
        np.zeros((6, 8), dtype="float32"),
    ])
    result = clusters.cluster_embeddings(embeddings, min_cluster_size=3, random_state=42)
    assert len(result.labels) == len(embeddings)
    assert len(result.memberships) == len(embeddings)
    assert all(0.0 <= m <= 1.0 for m in result.memberships)


def test_label_cluster_uses_llm_and_falls_back_with_warning(monkeypatch):
    class FakeLabeler:
        def label(self, samples):
            return ("auth session", "Authentication and session handling.")

    label, summary, warning = clusters.label_cluster(["def authenticate_user(): pass"], FakeLabeler())
    assert label == "auth session"
    assert summary.startswith("Authentication")
    assert warning is None
```

- [ ] **Step 2: Implement UMAP + HDBSCAN clustering and label fallback**

Create `scripts/cbv/clusters.py`:

```python
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ClusterResult:
    labels: list[int]
    memberships: list[float]
    reduced: np.ndarray


class ClusterLabeler:
    def label(self, samples: list[str]) -> tuple[str, str]:
        raise NotImplementedError


class LocalLLMClusterLabeler(ClusterLabeler):
    def label(self, samples: list[str]) -> tuple[str, str]:
        # Use the configured local model adapter from the environment.
        # Implementation may share the project's future LLM adapter; tests use a fake labeler.
        raise RuntimeError("local LLM labeler is not configured")


def deterministic_label_for_texts(texts: list[str]) -> tuple[str, str]:
    words = Counter()
    for text in texts:
        for word in text.replace("_", " ").split():
            clean = word.strip(".,:;()[]{}<>!?\"'").lower()
            if len(clean) >= 4:
                words[clean] += 1
    common = [w for w, _ in words.most_common(3)] or ["code"]
    label = " ".join(common)
    return label, f"Code related to {label}."


def cluster_embeddings(
    embeddings: np.ndarray,
    *,
    min_cluster_size: int = 10,
    min_samples: int = 5,
    random_state: int = 42,
) -> ClusterResult:
    if len(embeddings) < min_cluster_size:
        return ClusterResult([-1 for _ in range(len(embeddings))], [0.0 for _ in range(len(embeddings))], embeddings)
    try:
        import umap
        import hdbscan
        reduced = umap.UMAP(n_components=8, min_dist=0.0, random_state=random_state).fit_transform(embeddings.astype("float32"))
        model = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples, prediction_data=True)
        labels = model.fit_predict(reduced)
        memberships = getattr(model, "probabilities_", np.ones(len(labels), dtype="float32"))
        return ClusterResult([int(x) for x in labels], [float(x) for x in memberships], reduced)
    except Exception:
        return ClusterResult([-1 for _ in range(len(embeddings))], [0.0 for _ in range(len(embeddings))], embeddings)


def label_cluster(samples: list[str], labeler: ClusterLabeler) -> tuple[str, str, str | None]:
    try:
        label, summary = labeler.label(samples[:5])
        return label, summary, None
    except Exception as e:
        label, summary = deterministic_label_for_texts(samples)
        return label, summary, f"LLM cluster labeling failed; used deterministic label: {e}"
```

- [ ] **Step 3: Wire vectorize**

After embeddings are known:
- Run `clusters.cluster_embeddings`.
- For each non-noise label, sample up to five representative chunks by highest membership.
- Call the configured `ClusterLabeler`.
- Write `clusters.label`, `clusters.summary`, `clusters.centroid`, and `clusters.size`.
- Write `chunk_clusters` for memberships `> 0.1`.
- Append labeler fallback warnings to `manifest.warnings[]`.

Set summary `clusters_indexed` and meta `total_clusters`.

- [ ] **Step 4: Add relate `concept-cluster`**

`relate <repo> concept-cluster <label-or-query>` returns chunks in matching clusters by label substring first, then by nearest centroid.

- [ ] **Step 5: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_clusters.py tests\integration\test_relate_cmd.py -v
```

Commit:

```bash
git add scripts/requirements.txt scripts/bootstrap.py scripts/cbv/clusters.py scripts/cbv/commands/vectorize.py scripts/cbv/commands/relate.py tests/unit/test_clusters.py tests/integration/test_relate_cmd.py
git commit -m "slice 7 t2: add concept clusters"
```

### Task 12: Architecture document and bench command

This task must implement the spec's artifact path. `ARCHITECTURE.md` is a one-pass LLM-written orientation map with deterministic fallback only on LLM failure. Bench output must support CoIR/RepoEval-style JSONL inputs and report MRR@10, NDCG@10, Recall@5, and Recall@10.

**Files:**
- Create: `scripts/cbv/architecture.py`
- Create: `scripts/cbv/bench.py`
- Create: `scripts/cbv/commands/bench_cmd.py`
- Modify: `scripts/cbv/cli.py`
- Modify: `scripts/cbv/commands/vectorize.py`
- Create: `tests/unit/test_architecture.py`
- Create: `tests/unit/test_bench.py`

- [ ] **Step 1: Implement architecture writer tests**

Create `tests/unit/test_architecture.py`:

```python
from cbv import architecture


class FakeArchitectureWriter:
    def write(self, payload):
        return "# demo Architecture\n\n## Overview\nLLM-written summary.\n"


def test_architecture_uses_llm_writer():
    text, warning = architecture.render_architecture(
        {"repo_name": "demo", "counts": {"chunks": 2}, "top_nodes": []},
        writer=FakeArchitectureWriter(),
    )
    assert text.startswith("# demo Architecture")
    assert warning is None


def test_architecture_fallback_warns():
    class BrokenWriter:
        def write(self, payload):
            raise RuntimeError("offline")

    text, warning = architecture.render_architecture(
        {"repo_name": "demo", "counts": {"chunks": 2}, "top_nodes": []},
        writer=BrokenWriter(),
    )
    assert "# demo Architecture" in text
    assert "LLM architecture generation failed" in warning
```

- [ ] **Step 2: Implement one-pass LLM architecture writer**

Create `scripts/cbv/architecture.py`:

```python
from __future__ import annotations


class ArchitectureWriter:
    def write(self, payload: dict) -> str:
        raise NotImplementedError


class LocalLLMArchitectureWriter(ArchitectureWriter):
    def write(self, payload: dict) -> str:
        # Use the configured local LLM adapter. Tests inject a fake writer.
        raise RuntimeError("local LLM architecture writer is not configured")


def _fallback(payload: dict) -> str:
    repo_name = payload["repo_name"]
    counts = payload.get("counts", {})
    top_nodes = payload.get("top_nodes", [])
    lines = [
        f"# {repo_name} Architecture",
        "",
        "## Index Summary",
        "",
        f"- Chunks: {counts.get('chunks', 0)}",
        f"- Symbol nodes: {counts.get('nodes_symbol', 0)}",
        f"- Symbol edges: {counts.get('edges_symbol', 0)}",
        f"- Flow nodes: {counts.get('nodes_block', 0)}",
        f"- Flow edges: {counts.get('edges_flow', 0)}",
        f"- Clusters: {counts.get('clusters', 0)}",
        "",
        "## Central Symbols",
        "",
    ]
    for node in top_nodes[:20]:
        lines.append(f"- `{node['name']}` ({node['kind']})")
    lines.append("")
    return "\n".join(lines)


def render_architecture(payload: dict, writer: ArchitectureWriter) -> tuple[str, str | None]:
    try:
        text = writer.write(payload)
        return text, None
    except Exception as e:
        return _fallback(payload), f"LLM architecture generation failed; used deterministic fallback: {e}"
```

- [ ] **Step 3: Implement bench tests**

Create `tests/unit/test_bench.py`:

```python
from cbv import bench


def test_metrics_include_mrr_ndcg_and_recall():
    actual = ["pkg/auth.py", "pkg/router.py", "pkg/db.py"]
    expected = {"pkg/router.py"}
    metrics = bench.metrics_for_query(expected, actual)
    assert metrics["mrr_at_10"] == 0.5
    assert metrics["recall_at_5"] == 1.0
    assert "ndcg_at_10" in metrics
    assert "recall_at_10" in metrics
```

- [ ] **Step 4: Implement bench helpers**

Create `scripts/cbv/bench.py`:

```python
from __future__ import annotations

import math


def recall_at_k(expected: set[str], actual: list[str], k: int) -> float:
    if not expected:
        return 1.0
    return len(expected & set(actual[:k])) / len(expected)


def mrr_at_k(expected: set[str], actual: list[str], k: int) -> float:
    for idx, item in enumerate(actual[:k], start=1):
        if item in expected:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(expected: set[str], actual: list[str], k: int) -> float:
    dcg = 0.0
    for idx, item in enumerate(actual[:k], start=1):
        if item in expected:
            dcg += 1.0 / math.log2(idx + 1)
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 1.0


def metrics_for_query(expected: set[str], actual: list[str]) -> dict[str, float]:
    return {
        "mrr_at_10": mrr_at_k(expected, actual, 10),
        "ndcg_at_10": ndcg_at_k(expected, actual, 10),
        "recall_at_5": recall_at_k(expected, actual, 5),
        "recall_at_10": recall_at_k(expected, actual, 10),
    }
```

- [ ] **Step 5: Add `bench` CLI**

`bench <repo>` reads `bench/coir_subset.jsonl`, `bench/repoeval_mini.jsonl`, and any repo-local `bench/queries.jsonl` when present. It runs each query through the full pipeline, writes `bench/results.json`, and prints:

```json
{"repo":"...","mrr_at_10":0.0,"ndcg_at_10":0.0,"recall_at_5":0.0,"recall_at_10":0.0,"queries":0}
```

Each JSONL row uses:

```json
{"query":"authenticate user","expected_files":["pkg/auth.py"]}
```

- [ ] **Step 6: Wire vectorize optional artifacts**

After vectorize completes, build an architecture payload from `manifest.json`, cluster summaries, top PageRank nodes, and up to 10 pivotal files. Write `ARCHITECTURE.md` using `architecture.render_architecture(payload, writer=LocalLLMArchitectureWriter())`; if fallback is used, append the warning to `manifest.warnings[]`. If `--bench` is added to the parser and passed, run the bench command and include results in summary `bench_results`.

- [ ] **Step 7: Verify and commit**

Run:

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests\unit\test_architecture.py tests\unit\test_bench.py tests\unit\test_bootstrap_dispatch.py -v
```

Commit:

```bash
git add scripts/cbv/architecture.py scripts/cbv/bench.py scripts/cbv/commands/bench_cmd.py scripts/cbv/cli.py scripts/cbv/commands/vectorize.py tests/unit/test_architecture.py tests/unit/test_bench.py tests/unit/test_bootstrap_dispatch.py
git commit -m "slice 7 t3: write architecture summary and bench results"
```

---

## Milestone 6: Skill Docs, README, and Code-Complete Verification

**Completion tracking directive:** Before declaring v1.0 code-complete, edit this plan to mark every safely completed task and the final verification gate complete. Any unchecked task at this point is a blocker or must be explicitly documented as superseded by a spec-aligned replacement.

### Task 13: Update skill docs and README to match final behavior

**Files:**
- Modify: `README.md`
- Modify: `skills/vectorize-repo/SKILL.md`
- Modify: `skills/codebase-query/SKILL.md`
- Modify: `skills/codebase-relate/SKILL.md`
- Modify: `docs/HANDOFF.md`

- [ ] **Step 1: Update README capability sections**

Required wording changes:
- Replace Slice 1/2 limits with complete v1.0 behavior.
- Document `query --lane auto|fast|full`.
- Document `relate`, `stats`, `graph`, `flow`, and `bench`.
- Document cache and incremental `vectorize --update`.
- Keep data location text unchanged unless code changed it.

- [ ] **Step 2: Update skill docs**

`vectorize-repo` must mention:

```json
{
  "nodes_symbol": 0,
  "nodes_block": 0,
  "edges_symbol": 0,
  "edges_flow": 0,
  "clusters_indexed": 0,
  "embedding_cache_hit_rate": 0.0,
  "bench_results": {}
}
```

with the zeros replaced by real counts after final implementation.

`codebase-query` must mention:

```json
{
  "pipeline_used": "fast|full",
  "refined_queries": [],
  "expansion_size": 0,
  "reranker_model": "..."
}
```

`codebase-relate` must list every supported verb exactly as the CLI parser accepts it.

- [ ] **Step 3: Verify docs mention every command**

Run:

```powershell
rg "vectorize|query|relate|stats|graph|flow|bench|--lane|--update|codebase-relate" README.md skills docs\HANDOFF.md
```

Expected: every final command appears in README and at least one skill or handoff doc.

- [ ] **Step 4: Commit**

```bash
git add README.md skills/vectorize-repo/SKILL.md skills/codebase-query/SKILL.md skills/codebase-relate/SKILL.md docs/HANDOFF.md
git commit -m "docs: update v1.0 code-complete surfaces"
```

### Task 14: Full verification gate

**Completion tracking directive:** After the full suite, final smoke, and git-state checks pass, edit this plan to mark Task 14 complete. This edit is part of the definition of done for the final verification gate.

- [ ] **Step 1: Run full unit/integration suite**

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pytest tests/ -v
```

Expected: all tests pass, network clone test may be skipped.

- [ ] **Step 2: Run final CLI smoke**

```powershell
$ErrorActionPreference='Stop'
$env:CBV_STUB_EMBEDDER='1'
$env:CBV_STUB_RERANKER='1'
$env:CODEBASE_VECTORIZER_HOME="$env:TEMP\cbv-v1-final-smoke"
$env:PYTHONPATH=(Resolve-Path .\scripts).Path
Remove-Item -Recurse -Force $env:CODEBASE_VECTORIZER_HOME -ErrorAction SilentlyContinue
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv vectorize tests\fixtures\simple-python --bench
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv query simple-python "authenticate_user" --lane fast --top-k 3
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv query simple-python "how does login authenticate users" --lane full --top-k 3
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv relate simple-python callers authenticate_user --top-k 5
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv graph simple-python authenticate_user --hops 1 --top-k 5
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv flow simple-python authenticate_user --top-k 5
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv stats simple-python --top-k 5
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv bench simple-python
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m cbv vectorize tests\fixtures\simple-python --update
Remove-Item -Recurse -Force $env:CODEBASE_VECTORIZER_HOME -ErrorAction SilentlyContinue
Remove-Item Env:\CBV_STUB_EMBEDDER -ErrorAction SilentlyContinue
Remove-Item Env:\CBV_STUB_RERANKER -ErrorAction SilentlyContinue
```

Expected:
- first vectorize summary has nonzero chunks, symbol nodes, symbol edges;
- fast query uses `pipeline_used: fast`;
- full query uses `pipeline_used: full`;
- relate returns JSON with `results`;
- graph and flow aliases return JSON with `results`;
- stats returns counts;
- bench writes/prints result JSON;
- update run completes and reports a nonzero cache hit rate.

- [ ] **Step 3: Inspect final git state**

```bash
git status --short --branch
git log --oneline --decorate -8
```

Expected: clean working tree on `dev`, ahead of `origin/dev` by the final plan commits.

- [ ] **Step 4: Optional final branch integration**

Because the user requested this plan to be written and executed directly on `dev`, no worktree merge is needed for this plan. If a future execution session uses a worktree anyway, merge back to `dev` with `--no-ff` and re-run this verification gate before cleanup.

---

## Self-Review

**Spec coverage:** This plan covers every remaining spec surface after Slice 2: identifier trigrams, tags.scm-backed Tier-A symbol graph extraction, query router, fast/full lanes, graph expansion, query-time Personalized PageRank, `codebase-relate`, `graph`, `flow`, cross-encoder rerank, refined queries, embedding cache, Merkle incremental indexing, UMAP + HDBSCAN concept clusters, LLM cluster labels with spec-defined fallback, CFG/DFG flow edges and flow queries, one-pass LLM `ARCHITECTURE.md` with spec-defined fallback, CoIR/RepoEval-style benchmark results, README, and skill docs.

**Intentional sequencing:** The plan does not implement isolated layers. Each milestone ends with a usable vectorize/query/relate path and a full green checkpoint before the next capability starts.

**Known final-polish candidates after code-complete:** tune graph weights, tune cluster-label wording, improve output formatting, update README examples with real output, add more real-repo benchmark fixtures, and profile large-repo performance. These are polish only after the spec-required surfaces pass the final verification gate.
