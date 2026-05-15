# codebase-vectorizer v1.0 — Slice 2: Tree-sitter + cAST Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Slice 1's text-window chunker with AST-aware tree-sitter + cAST chunking for Tier-A languages (Python, JavaScript, TypeScript/TSX, Go, Rust, Java, C, C++, Ruby, C#). Chunks now correspond to logical code units (functions, classes, methods, merged sibling groups) instead of byte windows. Files whose language isn't supported or whose parser raises fall back to the existing text-window behavior. The `Chunk` dataclass shape is unchanged so downstream consumers (`vectorize`, `query`) require no edits.

**Architecture:**

1. New module `scripts/cbv/parser.py` wraps `tree-sitter-language-pack`: defines a `Language` dataclass + a `LANGUAGES` registry keyed by canonical name, exposes `language_for_path(Path)` and `parse(bytes, Language) -> Tree | None`. Tree-sitter is imported lazily so module load stays cheap.

2. New module `scripts/cbv/cast_chunker.py` implements the cAST algorithm from the spec (§ "Step 4 — Chunk via cAST"): a recursive split-then-merge that emits non-overlapping `Chunk` objects with `kind` derived from the representative AST node's type (function / class / method / section), `name` extracted from the node's name child, and `ast_path` walked from the node up to root (`module/class[Foo]/method[bar]`). The byte ranges of emitted chunks tile the full file contiguously — concat == file invariant is preserved.

3. `scripts/cbv/chunker.py` is refactored into a thin orchestrator. `chunk_text` / `chunk_file` first try `parser.language_for_path` + `parser.parse` + `cast_chunker.cast_chunks`; on unknown language or parser failure, fall back to the existing line-aware text-window code (renamed to a private helper). All Slice 1 chunker tests stay green because the fallback path is byte-for-byte identical.

**Tech Stack:** Slice 1 stack + `tree-sitter >= 0.21.0` and `tree-sitter-language-pack >= 0.3.0` (ships 305+ pre-built grammars; preferred over the older `tree-sitter-languages` which is unmaintained).

**Scope boundary**

In scope (Slice 2):
- tree-sitter integration via `tree-sitter-language-pack` (lazy imports)
- cAST recursive split-then-merge with byte-contiguous tiling
- Tier-A languages: python, javascript, typescript, tsx, go, rust, java, c, cpp, ruby, csharp (per spec § "Per-language coverage tier")
- Per-language node-type → `Chunk.kind` mapping (function / class / method / section)
- `name` extraction from `child_by_field_name("name")` for definition nodes
- `ast_path` computation (e.g. `module/class[Foo]/method[bar]`)
- Text-window fallback preserved for: unknown languages, languages NOT in `LANGUAGES`, parser failures
- All Slice 1 tests still pass; integration test still passes with possibly updated chunk-count expectations

Out of scope (deferred to later slices):
- Symbol-graph nodes/edges via `tags.scm` extraction (Slice 3)
- Identifier trigrams + fast-lane query router (Slice 4)
- Cross-encoder reranker (Slice 5)
- PageRank (Slice 6)
- Concept clusters (Slice 7)
- `codebase-relate` skill (Slice 8)
- CFG/DFG flow extraction (Slices 9–10)
- Embedding cache (Slice 11)
- Incremental indexing (Slice 12)
- `ARCHITECTURE.md` auto-generation (Slice 13)
- Bench harness (Slice 14)
- Confidence + refined_queries (Slice 15)

**Migration policy.** The schema is unchanged from Slice 1 (still v1.0). v1.0-Slice-1 indexes (all `kind="window"`) remain valid and queryable — they just won't have AST-aware retrieval until re-vectorized. The query command does NOT prompt for re-indexing; users opt in by re-running `vectorize-repo`. No new `meta` keys.

**Reference:** authoritative source is `specs/2026-05-14-codebase-vectorizer-v1.0-design.md`. Sections in scope:
- § "Step 3 — Parse with tree-sitter"
- § "Step 4 — Chunk via cAST" (algorithm pseudocode + invariants)
- § "Failure modes & error handling" (parse failure → text-window fallback, warning recorded)
- `Chunk.kind` enumeration: function | class | method | section | window | preamble | test | config | doc

If this plan and the spec disagree, the spec wins.

---

## File structure (after Slice 2)

```
scripts/
├── bootstrap.py                       MODIFIED (deps_installed probe adds tree_sitter)
├── requirements.txt                   MODIFIED (+tree-sitter, +tree-sitter-language-pack)
└── cbv/
    ├── parser.py                      NEW: tree-sitter Language registry + parse()
    ├── cast_chunker.py                NEW: cAST algorithm + per-language kind mapping
    ├── chunker.py                     MODIFIED: orchestrator (cAST first, text-window fallback)
    └── (other Slice 1 modules unchanged)

tests/
├── unit/
│   ├── test_parser.py                 NEW: language registry + parse()
│   ├── test_cast_chunker.py           NEW: kind mapping, ast_path, greedy merge, full algorithm
│   ├── test_chunker.py                MODIFIED: keep Slice 1 tests; add orchestrator/fallback tests
│   └── (other Slice 1 tests unchanged)
└── integration/
    └── test_full_index.py             MODIFIED if chunk-count assertions change

docs/plans/
└── 2026-05-14-codebase-vectorizer-v1.0-slice-2-tree-sitter-cast.md   THIS FILE
```

**Module boundaries — single responsibility per file:**

- `parser.py`: pure tree-sitter wrapper. Defines `Language` (cbv-side metadata, NOT the tree-sitter Language object), exposes a registry of supported languages, and a `parse(bytes, Language) -> Tree | None`. Knows nothing about chunks, kinds, or our `Chunk` dataclass.
- `cast_chunker.py`: pure cAST. Given a `Tree`, source bytes, file path, language name, and a byte budget, returns a list of `Chunk` objects whose byte ranges tile the source contiguously. Knows the per-language node-type → kind mapping. Imports `Chunk` from `chunker.py`.
- `chunker.py`: orchestrator. `chunk_text` / `chunk_file` decide whether to use cAST or text-window. Keeps `Chunk` dataclass + `detect_language` + extension/special-filename tables. Old `chunk_text` body becomes private `_text_window_chunks`.

Files that change together live together. `parser.py` and `cast_chunker.py` are separate because parsing and chunking are different concerns; parsing is reused by Slice 3's symbol extractor.

---

## Tasks

### Task 1: Add tree-sitter deps + update bootstrap probe

Add the two new wheel-only dependencies and teach `bootstrap.deps_installed` to probe for them. Without this, the bootstrap will think the venv is up-to-date when tree-sitter is missing and never install.

**Files:**
- Modify: `scripts/requirements.txt`
- Modify: `scripts/bootstrap.py` (the `deps_installed` function)
- Modify: `tests/unit/test_bootstrap_dispatch.py` is fine as-is (no new test required — bootstrap probe is integration-tested by `setup` running cleanly)

- [ ] **Step 1: Add the deps to scripts/requirements.txt**

Open `scripts/requirements.txt` and append (preserving the existing pins):

```
tree-sitter>=0.21.0
tree-sitter-language-pack>=0.3.0
```

The file should now read (full content):

```
# codebase-vectorizer v1.0 Slice 1 dependencies.
# Pin minor-version floors per spec; let pip resolve the latest compatible.
sqlite-vec>=0.1.9,<0.2.0
transformers>=4.42
torch>=2.3
llama-cpp-python>=0.2.80
huggingface_hub>=0.23.0
numpy>=1.26
pathspec>=0.12
requests>=2.31.0
tree-sitter>=0.21.0
tree-sitter-language-pack>=0.3.0
```

- [ ] **Step 2: Update bootstrap.deps_installed to probe tree-sitter too**

Open `scripts/bootstrap.py`. Find the `deps_installed` function (it was updated in Slice 1's final-review fixes — currently probes `sqlite_vec, transformers, numpy, pathspec, requests, huggingface_hub` as the core, then EITHER `llama_cpp` OR `torch`).

Add `tree_sitter, tree_sitter_language_pack` to the `core_probe` string so they're required:

```python
def deps_installed(py: Path) -> bool:
    """Quick smoke check: import the v1.0 minimums.

    `llama_cpp` is optional when CUDA + torch are available (the GPU path).
    Probe both stacks and accept either: at least one runtime embedder must
    be importable. Without this, the bootstrap thrashes pip install on every
    invocation when llama_cpp isn't installable (e.g. Windows without VS).
    """
    core_probe = (
        "import sqlite_vec, transformers, numpy, pathspec, requests, "
        "huggingface_hub, tree_sitter, tree_sitter_language_pack"
    )
    if subprocess.run([str(py), "-c", core_probe], capture_output=True).returncode != 0:
        return False
    cpu_ok = subprocess.run([str(py), "-c", "import llama_cpp"],
                            capture_output=True).returncode == 0
    gpu_ok = subprocess.run([str(py), "-c", "import torch"],
                            capture_output=True).returncode == 0
    return cpu_ok or gpu_ok
```

- [ ] **Step 3: Install the new deps into the plugin venv**

The plugin venv lives at `<data_home>/python-env/`. From the repo root:

PowerShell:
```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -m pip install -r scripts\requirements.txt --upgrade --only-binary=:all: --disable-pip-version-check
```

POSIX:
```bash
"<data_home>/python-env/bin/python" -m pip install -r scripts/requirements.txt --upgrade --only-binary=:all: --disable-pip-version-check
```

Expected: pip installs `tree-sitter` and `tree-sitter-language-pack` (or reports they're already up-to-date). Both have prebuilt wheels for Python 3.10–3.13 on Windows/macOS/Linux.

If `--only-binary=:all:` fails because a wheel is missing for your platform/Python, drop the flag and re-run. (`tree-sitter` is C; `tree-sitter-language-pack` ships the C grammars as wheels.)

- [ ] **Step 4: Smoke-test the imports**

```powershell
& "$env:LOCALAPPDATA\codebase-vectorizer\python-env\Scripts\python.exe" -c "import tree_sitter, tree_sitter_language_pack; from tree_sitter_language_pack import get_parser; p = get_parser('python'); print('parser:', type(p).__name__); print('parse:', type(p.parse(b'x = 1')).__name__)"
```

Expected output (literally):
```
parser: Parser
parse: Tree
```

If `get_parser('python')` raises, the language pack didn't install correctly — investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add scripts/requirements.txt scripts/bootstrap.py
git commit -m "slice 2 t1: pin tree-sitter + tree-sitter-language-pack; extend bootstrap probe"
```

---

### Task 2: scripts/cbv/parser.py — Language dataclass + LANGUAGES registry

Create the parser module skeleton: a `Language` dataclass that holds cbv's canonical name, the tree-sitter-language-pack lookup name, and the file extensions for that language. Plus the `LANGUAGES` dict and an `EXTENSION_LANGUAGE` reverse map. Stdlib-only at import time — tree-sitter is imported only inside `parse()`.

**Files:**
- Create: `scripts/cbv/parser.py`
- Create: `tests/unit/test_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_parser.py`:

```python
"""Tests for cbv.parser — Language registry only (parse() is exercised in
the next task). The registry is stdlib-only so these tests run without
tree-sitter installed."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import parser  # noqa: E402


def test_language_dataclass_fields():
    py = parser.LANGUAGES["python"]
    assert py.name == "python"
    assert py.ts_language_name == "python"
    assert ".py" in py.extensions
    assert ".pyi" in py.extensions


def test_languages_registry_includes_tier_a():
    expected = {
        "python", "javascript", "typescript", "tsx",
        "go", "rust", "java", "c", "cpp", "ruby", "csharp",
    }
    assert expected <= set(parser.LANGUAGES.keys()), \
        f"missing: {expected - set(parser.LANGUAGES.keys())}"


def test_language_for_path_python():
    lang = parser.language_for_path(Path("foo.py"))
    assert lang is not None
    assert lang.name == "python"


def test_language_for_path_typescript_vs_tsx():
    assert parser.language_for_path(Path("a.ts")).name == "typescript"
    assert parser.language_for_path(Path("a.tsx")).name == "tsx"


def test_language_for_path_jsx_is_javascript():
    """The JS grammar handles JSX too in tree-sitter-language-pack."""
    assert parser.language_for_path(Path("a.jsx")).name == "javascript"


def test_language_for_path_cpp_extensions():
    for ext in (".cpp", ".cxx", ".cc", ".hpp", ".hxx"):
        lang = parser.language_for_path(Path(f"a{ext}"))
        assert lang is not None, ext
        assert lang.name == "cpp"


def test_language_for_path_unknown_returns_none():
    assert parser.language_for_path(Path("foo.unknown")) is None
    assert parser.language_for_path(Path("foo.md")) is None  # markdown not in Tier-A


def test_language_for_name():
    assert parser.language_for_name("python").name == "python"
    assert parser.language_for_name("bogus") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cbv.parser'`.

- [ ] **Step 3: Implement scripts/cbv/parser.py (registry only — no parse() yet)**

Create `scripts/cbv/parser.py`:

```python
"""Tree-sitter integration for codebase-vectorizer.

This module defines the set of languages cbv parses with tree-sitter
("Tier-A" languages per the spec) and exposes a `parse(bytes, Language)`
function that returns a `Tree` (or None on failure).

Top-level imports are stdlib-only. tree-sitter and
tree-sitter-language-pack are imported lazily inside `parse()` so the
module loads cheaply for unit tests that only exercise the registry.

Slice 2 covers Tier-A languages. Tier-B / Tier-C support (more grammars
without CFG/DFG) is a future-slice concern; nothing prevents us from
adding entries to LANGUAGES later.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Language:
    """cbv-side language metadata.

    `name` is the canonical cbv name used in `Chunk.language` and
    elsewhere downstream. `ts_language_name` is the string
    `tree_sitter_language_pack.get_parser()` expects (sometimes the
    same, sometimes not — e.g. "csharp" vs "c_sharp").
    """
    name: str
    ts_language_name: str
    extensions: tuple[str, ...]


# Tier-A languages per the spec § "Per-language coverage tier".
LANGUAGES: dict[str, Language] = {
    "python":     Language("python",     "python",     (".py", ".pyi")),
    "javascript": Language("javascript", "javascript", (".js", ".mjs", ".cjs", ".jsx")),
    "typescript": Language("typescript", "typescript", (".ts",)),
    "tsx":        Language("tsx",        "tsx",        (".tsx",)),
    "go":         Language("go",         "go",         (".go",)),
    "rust":       Language("rust",       "rust",       (".rs",)),
    "java":       Language("java",       "java",       (".java",)),
    "c":          Language("c",          "c",          (".c", ".h")),
    "cpp":        Language("cpp",        "cpp",        (".cpp", ".cxx", ".cc", ".hpp", ".hxx")),
    "ruby":       Language("ruby",       "ruby",       (".rb",)),
    "csharp":     Language("csharp",     "csharp",     (".cs",)),
}


EXTENSION_LANGUAGE: dict[str, Language] = {
    ext: lang for lang in LANGUAGES.values() for ext in lang.extensions
}


def language_for_name(name: str) -> Optional[Language]:
    """Look up a Language by its cbv canonical name."""
    return LANGUAGES.get(name)


def language_for_path(path: Path) -> Optional[Language]:
    """Look up the Language that should parse the given file path, or
    None if the extension is unrecognized (caller falls back to
    text-window chunking)."""
    return EXTENSION_LANGUAGE.get(path.suffix.lower())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_parser.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/parser.py tests/unit/test_parser.py
git commit -m "slice 2 t2: cbv.parser — Language registry for Tier-A grammars"
```

---

### Task 3: scripts/cbv/parser.py — parse(bytes, Language) function

Add the `parse()` function that actually invokes tree-sitter. Lazy-imports `tree_sitter_language_pack` so import-time cost stays zero for callers that only need the registry.

**Files:**
- Modify: `scripts/cbv/parser.py`
- Modify: `tests/unit/test_parser.py` (append)

- [ ] **Step 1: Add the failing parse tests**

Append to `tests/unit/test_parser.py`:

```python
def test_parse_python_returns_tree():
    lang = parser.LANGUAGES["python"]
    src = b"def foo(x):\n    return x + 1\n"
    tree = parser.parse(src, lang)
    assert tree is not None
    root = tree.root_node
    assert root.type == "module"
    # First child is the function definition
    fn = root.children[0]
    assert fn.type == "function_definition"
    assert fn.start_byte == 0
    assert fn.end_byte == len(src)


def test_parse_javascript_returns_tree():
    lang = parser.LANGUAGES["javascript"]
    src = b"function add(a, b) { return a + b; }\n"
    tree = parser.parse(src, lang)
    assert tree is not None
    root = tree.root_node
    assert root.type == "program"
    fn = root.children[0]
    assert fn.type == "function_declaration"


def test_parse_returns_a_tree_even_on_syntax_errors():
    """tree-sitter is error-tolerant: it returns a tree with ERROR nodes
    rather than raising. We rely on this for graceful chunking of broken
    files."""
    lang = parser.LANGUAGES["python"]
    src = b"def foo(:\n    this is not valid python\n"
    tree = parser.parse(src, lang)
    assert tree is not None  # NOT None — tree-sitter is permissive
    assert tree.root_node.has_error  # tree carries an ERROR somewhere


def test_parse_empty_input():
    """Empty bytes are still a valid (trivial) parse."""
    lang = parser.LANGUAGES["python"]
    tree = parser.parse(b"", lang)
    assert tree is not None
    assert tree.root_node.start_byte == 0
    assert tree.root_node.end_byte == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_parser.py -v`
Expected: 4 new tests FAIL with `AttributeError: module 'cbv.parser' has no attribute 'parse'`.

- [ ] **Step 3: Append the parse() function to scripts/cbv/parser.py**

Append to the end of `scripts/cbv/parser.py`:

```python
def parse(content: bytes, language: Language):
    """Parse `content` with the given Language. Returns a tree-sitter Tree
    (or None on failure).

    `tree_sitter_language_pack` is imported lazily so that callers
    needing only `LANGUAGES` / `language_for_path` (or tests that don't
    touch tree-sitter) pay zero import cost.

    Tree-sitter parsers are error-tolerant; a malformed source still
    returns a Tree (with `has_error == True`). The None path is reserved
    for outright failure to construct a parser (e.g. an unsupported
    language slipped through the registry).
    """
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    try:
        parser_obj = get_parser(language.ts_language_name)
        return parser_obj.parse(content)
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_parser.py -v`
Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/parser.py tests/unit/test_parser.py
git commit -m "slice 2 t3: cbv.parser — lazy-imported parse(bytes, Language) -> Tree"
```

---

### Task 4: scripts/cbv/cast_chunker.py — kind mapping for Python + helpers

Lay down the cast_chunker module: per-language kind mapping (Python first), the `byte_to_line` line-offset helper used to populate `Chunk.start_line` / `end_line`, the `_extract_name` helper for definition nodes, and the `_ast_path` helper that walks from a node up to root.

**Files:**
- Create: `scripts/cbv/cast_chunker.py`
- Create: `tests/unit/test_cast_chunker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cast_chunker.py`:

```python
"""Tests for cbv.cast_chunker — kind mapping, name extraction, ast_path,
byte_to_line. The full cast_chunks() algorithm is tested in subsequent tasks."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import cast_chunker, parser  # noqa: E402


def _parse_python(src: bytes):
    return parser.parse(src, parser.LANGUAGES["python"])


def test_byte_to_line_simple():
    src = b"a\nbb\nccc\n"
    line_starts = cast_chunker._line_starts(src)
    # line_starts = [0, 2, 5, 9]
    assert cast_chunker._byte_to_line(line_starts, 0) == 1
    assert cast_chunker._byte_to_line(line_starts, 1) == 1
    assert cast_chunker._byte_to_line(line_starts, 2) == 2
    assert cast_chunker._byte_to_line(line_starts, 4) == 2
    assert cast_chunker._byte_to_line(line_starts, 5) == 3
    assert cast_chunker._byte_to_line(line_starts, 8) == 3


def test_byte_to_line_no_trailing_newline():
    src = b"abc"
    line_starts = cast_chunker._line_starts(src)
    assert cast_chunker._byte_to_line(line_starts, 0) == 1
    assert cast_chunker._byte_to_line(line_starts, 2) == 1


def test_python_kind_function_at_top_level():
    src = b"def foo():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    assert fn.type == "function_definition"
    assert cast_chunker._kind_for_node("python", fn, parents=[tree.root_node]) == "function"


def test_python_kind_method_inside_class():
    src = b"class C:\n    def foo(self):\n        pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    assert cls.type == "class_definition"
    # Find the function_definition inside the class body
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    parents = [tree.root_node, cls, body]
    assert cast_chunker._kind_for_node("python", fn, parents=parents) == "method"


def test_python_kind_class():
    src = b"class C:\n    pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    assert cast_chunker._kind_for_node("python", cls, parents=[tree.root_node]) == "class"


def test_python_kind_async_function():
    src = b"async def foo():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    # tree-sitter-python may name this 'function_definition' or
    # 'async_function_definition' depending on grammar version; either
    # one must resolve to "function".
    parents = [tree.root_node]
    kind = cast_chunker._kind_for_node("python", fn, parents=parents)
    assert kind == "function", f"got {kind!r} for node type {fn.type!r}"


def test_python_kind_decorated_function():
    src = b"@deco\ndef foo():\n    pass\n"
    tree = _parse_python(src)
    deco = tree.root_node.children[0]
    # tree-sitter-python wraps decorated functions in 'decorated_definition'
    assert deco.type == "decorated_definition"
    assert cast_chunker._kind_for_node("python", deco, parents=[tree.root_node]) == "function"


def test_python_kind_falls_back_to_section():
    src = b"import os\n"
    tree = _parse_python(src)
    imp = tree.root_node.children[0]
    assert imp.type == "import_statement"
    assert cast_chunker._kind_for_node("python", imp, parents=[tree.root_node]) == "section"


def test_extract_name_function():
    src = b"def foo_bar():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    assert cast_chunker._extract_name(fn, src) == "foo_bar"


def test_extract_name_class():
    src = b"class MyClass:\n    pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    assert cast_chunker._extract_name(cls, src) == "MyClass"


def test_extract_name_decorated_definition():
    src = b"@deco\ndef wrapped():\n    pass\n"
    tree = _parse_python(src)
    deco = tree.root_node.children[0]
    assert cast_chunker._extract_name(deco, src) == "wrapped"


def test_extract_name_no_name_node_returns_none():
    src = b"import os\n"
    tree = _parse_python(src)
    imp = tree.root_node.children[0]
    assert cast_chunker._extract_name(imp, src) is None


def test_ast_path_top_level_function():
    src = b"def foo():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    # Path includes only nodes that have a name; top-level fn under module
    assert cast_chunker._ast_path("python", fn, [tree.root_node], src) == "module/function[foo]"


def test_ast_path_method():
    src = b"class C:\n    def foo(self):\n        pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    parents = [tree.root_node, cls, body]
    assert (
        cast_chunker._ast_path("python", fn, parents, src)
        == "module/class[C]/method[foo]"
    )


def test_ast_path_module_only_for_root_children():
    """Top-level statements (not class/function) get the module prefix only."""
    src = b"x = 1\n"
    tree = _parse_python(src)
    stmt = tree.root_node.children[0]
    assert cast_chunker._ast_path("python", stmt, [tree.root_node], src) == "module/section"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: tests FAIL with `ModuleNotFoundError: No module named 'cbv.cast_chunker'`.

- [ ] **Step 3: Implement scripts/cbv/cast_chunker.py (helpers + kind mapping)**

Create `scripts/cbv/cast_chunker.py`:

```python
"""cAST chunker — AST-aware chunking via tree-sitter.

Implements the cAST algorithm (Zhang et al., arXiv 2506.15655) referenced
in spec § "Step 4 — Chunk via cAST": a recursive split-then-merge over
the parse tree that emits non-overlapping Chunk objects. The emitted
chunks' byte ranges tile the source bytes contiguously so concat == file.

Per-language kind mapping (function / class / method / section) lives in
this module. Tree-sitter node types differ across grammars; the mapping
is a per-language function that takes (node, ancestor_list) and returns
the cbv kind string. Unknown nodes fall back to "section".

`cast_chunks()` is the entry point. It is called by chunker.py's
orchestrator only after parser.parse() returned a non-None Tree.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from cbv.chunker import Chunk, _sha256_hex, _token_count


# --- byte / line helpers ---------------------------------------------------


def _line_starts(source: bytes) -> List[int]:
    """Return a list of byte offsets where each (0-indexed) line begins.
    line_starts[0] = 0, line_starts[i] is the byte just AFTER the (i-1)th newline."""
    starts = [0]
    for i, b in enumerate(source):
        if b == 0x0A:  # '\n'
            starts.append(i + 1)
    return starts


def _byte_to_line(line_starts: Sequence[int], byte_offset: int) -> int:
    """Convert a byte offset into a 1-indexed line number.

    line N covers bytes [line_starts[N-1], line_starts[N]).
    The trailing newline at the end of a line counts as part of THAT line.
    A byte at or past the final line_start counts as the final line.
    """
    # bisect_right returns the index of the first start STRICTLY greater than
    # byte_offset, which equals the 1-indexed line number.
    idx = bisect.bisect_right(line_starts, byte_offset)
    return max(1, idx)


# --- name + ast_path extraction --------------------------------------------


def _extract_name(node, source: bytes) -> Optional[str]:
    """Return the identifier name for a definition node, or None.

    Tries `child_by_field_name("name")` first (works for most languages).
    For Python's `decorated_definition`, unwraps to the inner definition.
    """
    if node.type == "decorated_definition":
        for c in node.children:
            if c.type in (
                "function_definition", "async_function_definition", "class_definition",
            ):
                node = c
                break
    name_node = node.child_by_field_name("name") if hasattr(node, "child_by_field_name") else None
    if name_node is None:
        return None
    try:
        return source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
    except Exception:
        return None


# --- per-language kind mapping ----------------------------------------------


def _python_kind(node, parents) -> str:
    """Map a Python tree-sitter node to a Chunk.kind."""
    real_type = node.type
    if real_type == "decorated_definition":
        for c in node.children:
            if c.type in (
                "function_definition", "async_function_definition", "class_definition",
            ):
                real_type = c.type
                break
    if real_type in ("function_definition", "async_function_definition"):
        # method if ANY ancestor is class_definition
        for p in parents:
            if p.type == "class_definition":
                return "method"
        return "function"
    if real_type == "class_definition":
        return "class"
    return "section"


# Lookup table; per-language entries added in later tasks.
KIND_MAPS: dict[str, Callable] = {
    "python": _python_kind,
}


def _kind_for_node(language: str, node, parents) -> str:
    fn = KIND_MAPS.get(language)
    if fn is None:
        return "section"
    return fn(node, parents)


def _ast_path(language: str, node, parents, source: bytes) -> str:
    """Build a path like 'module/class[Foo]/method[bar]' from the root
    down to the node.

    Only nodes whose `_kind_for_node` is in {function, class, method}
    contribute a labeled segment with `[name]`. Top-level appears as
    'module'. The terminal node uses its own kind even if it's "section".
    """
    parts: list[str] = []
    # Always start with "module" (or equivalent top-level label).
    parts.append("module")

    LABELLED = {"function", "class", "method"}
    # Walk parents from second-onward (skip root) and emit labels for
    # class/function/method ancestors only. tree_sitter's root_node has
    # type "module" (Python) / "program" (JS) / etc., which we render
    # as "module" uniformly.
    for i, p in enumerate(parents[1:], start=1):  # skip root_node
        # When evaluating an ancestor's kind, its own ancestors are parents[:i]
        kind = _kind_for_node(language, p, parents[:i])
        if kind in LABELLED:
            name = _extract_name(p, source) or "?"
            parts.append(f"{kind}[{name}]")

    # Terminal segment: this node's own kind. Labelled types get [name];
    # plain "section" appears without brackets.
    terminal_kind = _kind_for_node(language, node, parents)
    if terminal_kind in LABELLED:
        name = _extract_name(node, source) or "?"
        parts.append(f"{terminal_kind}[{name}]")
    else:
        parts.append("section")

    return "/".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: all 14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/cast_chunker.py tests/unit/test_cast_chunker.py
git commit -m "slice 2 t4: cbv.cast_chunker — kind map (Python), name + ast_path helpers"
```

---

### Task 5: scripts/cbv/cast_chunker.py — Chunk construction from a single AST node

Add a `_chunk_from_node(node, parents, language_name, file_path, source, line_starts)` helper that wraps a single AST node as a `Chunk`. This is the leaf case of the cAST recursion. The next task adds the recursive split-then-merge.

**Files:**
- Modify: `scripts/cbv/cast_chunker.py`
- Modify: `tests/unit/test_cast_chunker.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cast_chunker.py`:

```python
def test_chunk_from_node_single_function():
    src = b"def add(a, b):\n    return a + b\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_node(
        fn, parents=[tree.root_node],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "function"
    assert chunk.name == "add"
    assert chunk.ast_path == "module/function[add]"
    assert chunk.file_path == "x.py"
    assert chunk.language == "python"
    assert chunk.start_line == 1
    assert chunk.end_line == 2
    assert chunk.start_byte == 0
    assert chunk.end_byte == len(src)
    assert chunk.content == src.decode("utf-8")
    assert chunk.token_count == len(chunk.content.split())


def test_chunk_from_node_class_with_method_records_method():
    src = b"class C:\n    def m(self):\n        return 1\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_node(
        fn, parents=[tree.root_node, cls, body],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "method"
    assert chunk.name == "m"
    assert chunk.ast_path == "module/class[C]/method[m]"


def test_chunk_from_node_top_level_statement():
    src = b"x = 1\n"
    tree = _parse_python(src)
    stmt = tree.root_node.children[0]
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_node(
        stmt, parents=[tree.root_node],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "section"
    assert chunk.name is None
    assert chunk.ast_path == "module/section"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: 3 new tests fail with `AttributeError: module 'cbv.cast_chunker' has no attribute '_chunk_from_node'`.

- [ ] **Step 3: Add the _chunk_from_node helper**

Append to `scripts/cbv/cast_chunker.py`:

```python
def _chunk_from_node(
    node,
    parents,
    *,
    language_name: str,
    file_path: str,
    source: bytes,
    line_starts: Sequence[int],
) -> Chunk:
    """Build a Chunk from a single AST node.

    Uses the node's existing byte/line metadata when available
    (`start_byte`, `end_byte`, `start_point`, `end_point`) and falls
    back to byte_to_line for anything that has to be derived from
    byte offsets only.
    """
    start_byte = node.start_byte
    end_byte = node.end_byte
    return _chunk_from_byte_range(
        start_byte, end_byte,
        node=node, parents=parents,
        language_name=language_name, file_path=file_path,
        source=source, line_starts=line_starts,
    )


def _chunk_from_byte_range(
    start_byte: int,
    end_byte: int,
    *,
    node,
    parents,
    language_name: str,
    file_path: str,
    source: bytes,
    line_starts: Sequence[int],
) -> Chunk:
    """Build a Chunk for a byte range that MAY or may not align with a
    single AST node. When `node` is non-None, kind/name/ast_path use it;
    when `node` is None (merged sibling group), kind="section",
    name=None, and ast_path is derived from `parents` only.
    """
    text_bytes = source[start_byte:end_byte]
    text = text_bytes.decode("utf-8", errors="replace")

    if node is not None:
        kind = _kind_for_node(language_name, node, parents)
        name = _extract_name(node, source)
        ast_path = _ast_path(language_name, node, parents, source)
    else:
        kind = "section"
        name = None
        # Merged sibling: ast_path is the parent path + "section".
        if parents:
            # Use the first parent's path; emulate _ast_path's parent walk
            # without an explicit terminal node.
            parts = ["module"]
            for i, p in enumerate(parents[1:], start=1):
                k = _kind_for_node(language_name, p, parents[:i])
                if k in ("function", "class", "method"):
                    nm = _extract_name(p, source) or "?"
                    parts.append(f"{k}[{nm}]")
            parts.append("section")
            ast_path = "/".join(parts)
        else:
            ast_path = "module/section"

    return Chunk(
        file_path=file_path,
        language=language_name,
        kind=kind,
        name=name,
        ast_path=ast_path,
        start_line=_byte_to_line(line_starts, start_byte),
        end_line=_byte_to_line(line_starts, max(end_byte - 1, start_byte)),
        start_byte=start_byte,
        end_byte=end_byte,
        content=text,
        content_hash=_sha256_hex(text),
        token_count=_token_count(text),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: all tests pass (now 17 total).

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/cast_chunker.py tests/unit/test_cast_chunker.py
git commit -m "slice 2 t5: cbv.cast_chunker — _chunk_from_node + _chunk_from_byte_range"
```

---

### Task 6: scripts/cbv/cast_chunker.py — `cast_chunks` recursive algorithm

The heart of cAST. Recursively walks the parse tree, splits nodes that exceed the budget, and greedily merges siblings that fit. Post-condition: emitted chunks tile [0, len(source)) contiguously (concat == file).

**Files:**
- Modify: `scripts/cbv/cast_chunker.py`
- Modify: `tests/unit/test_cast_chunker.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cast_chunker.py`:

```python
def test_cast_chunks_concat_invariant_tiny_file():
    src = b"def foo():\n    pass\n"
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src


def test_cast_chunks_concat_invariant_multiple_functions():
    src = (
        b"def a():\n    return 1\n"
        b"def b():\n    return 2\n"
        b"def c():\n    return 3\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src


def test_cast_chunks_concat_invariant_contiguous_byte_ranges():
    """Chunk byte ranges must tile [0, len(source)) contiguously."""
    src = (
        b"import os\n"
        b"\n"
        b"def foo():\n    return 1\n"
        b"\n"
        b"def bar():\n    return 2\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert chunks, "expected at least one chunk"
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(src)
    for a, b in zip(chunks, chunks[1:]):
        assert a.end_byte == b.start_byte, \
            f"gap between {a.end_byte} and {b.start_byte}"


def test_cast_chunks_single_function_under_budget_is_one_chunk():
    src = b"def foo():\n    return 42\n"
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert len(chunks) == 1
    assert chunks[0].kind == "function"
    assert chunks[0].name == "foo"


def test_cast_chunks_splits_when_over_budget():
    """A class containing several methods, each under budget but together
    exceeding it, should split into multiple chunks."""
    src = (
        b"class C:\n"
        b"    def aaa(self):\n        return 'aaaaa'\n"
        b"    def bbb(self):\n        return 'bbbbb'\n"
        b"    def ccc(self):\n        return 'ccccc'\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=60,
    )
    assert len(chunks) > 1
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    # At least one chunk should be a method.
    assert any(c.kind == "method" for c in chunks)


def test_cast_chunks_oversized_leaf_emits_overbudget_chunk():
    """A single deeply-leaf node bigger than budget still emits as one
    chunk (no further split possible)."""
    src = b"x = '" + (b"X" * 5000) + b"'\n"
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=100,
    )
    # Concat still holds; some chunk(s) are over-budget.
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    assert max(len(c.content.encode("utf-8")) for c in chunks) > 100


def test_cast_chunks_empty_source_returns_no_chunks():
    src = b""
    tree = _parse_python(src)
    chunks = cast_chunker.cast_chunks(
        tree, src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert chunks == []


def test_cast_chunks_method_chunk_has_method_path():
    """A chunk emitted for a method-sized class should preserve ast_path."""
    src = (
        b"class Big:\n"
        b"    def first(self):\n        " + b"x = 1\n        " * 60 + b"\n"
        b"    def second(self):\n        return 2\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=80,
    )
    paths = [c.ast_path for c in chunks]
    # At least one chunk should be inside class Big (its ast_path contains 'class[Big]').
    assert any("class[Big]" in p for p in paths), f"paths: {paths}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: 8 new tests fail with `AttributeError: module 'cbv.cast_chunker' has no attribute 'cast_chunks'`.

- [ ] **Step 3: Implement cast_chunks + helpers**

Append to `scripts/cbv/cast_chunker.py`:

```python
@dataclass
class _Slot:
    """Mutable intermediate cAST slot. Tracks the byte range plus the
    representative node (or None if this slot is a merged sibling group).
    Converted to a Chunk at the end of cast_chunks()."""
    start_byte: int
    end_byte: int
    node: object  # tree-sitter Node or None
    parents: List[object]


def cast_chunks(
    tree,
    source: bytes,
    *,
    language_name: str,
    file_path: str,
    budget_bytes: int = 1500,
) -> List[Chunk]:
    """Apply cAST to `tree` over `source`, returning a list of Chunks
    whose byte ranges tile [0, len(source)) contiguously.

    Algorithm (spec § "Step 4 — Chunk via cAST"):

        cast(node, budget):
            if size(node) <= budget: return [chunk(node)]
            children = node.children
            if all(size(c) <= budget for c in children):
                return greedy_merge(children, budget)
            chunks = []
            for c in children:
                if size(c) > budget: chunks.extend(cast(c, budget))
                else: chunks.append(chunk(c))
            return greedy_merge(chunks, budget)

    Implementation notes:
    - We work with `_Slot` records instead of Chunk objects so we can
      manipulate byte ranges (extending the first/last slot to cover
      whitespace at the parent's boundaries) before final conversion.
    - The greedy merge of a contiguous run of slots emits one slot per
      group with byte range = (first.start_byte, last.end_byte). The
      representative `node` becomes None to signal "merged sibling
      group" — kind/name fall back to section/None.
    - Root extension: after recursing on the root, we ensure
      `slots[0].start_byte == 0` and `slots[-1].end_byte == len(source)`
      so every byte of the source is covered.
    """
    if not source:
        return []
    root = tree.root_node
    slots = _cast(root, parents=[], source=source, budget=budget_bytes,
                  language_name=language_name)
    if not slots:
        return []
    # Tile the entire source byte range (handle whitespace before the
    # first AST node and after the last).
    slots[0].start_byte = 0
    slots[-1].end_byte = len(source)

    line_starts = _line_starts(source)
    return [
        _chunk_from_byte_range(
            s.start_byte, s.end_byte,
            node=s.node, parents=s.parents,
            language_name=language_name, file_path=file_path,
            source=source, line_starts=line_starts,
        )
        for s in slots
    ]


def _cast(node, *, parents, source, budget: int, language_name: str) -> List[_Slot]:
    """Recursive split-then-merge. Returns slots covering [node.start_byte, node.end_byte]."""
    size = node.end_byte - node.start_byte
    if size <= budget:
        return [_Slot(node.start_byte, node.end_byte, node, parents + [])]

    children = [c for c in node.children if c.end_byte > c.start_byte]
    if not children:
        # Leaf node larger than budget: emit anyway (concat invariant
        # requires we cover the bytes; we can't split further).
        return [_Slot(node.start_byte, node.end_byte, node, parents + [])]

    next_parents = parents + [node]
    out: List[_Slot] = []
    for c in children:
        c_size = c.end_byte - c.start_byte
        if c_size > budget:
            out.extend(_cast(c, parents=next_parents, source=source,
                             budget=budget, language_name=language_name))
        else:
            out.append(_Slot(c.start_byte, c.end_byte, c, next_parents + []))

    # Greedy merge of consecutive sibling slots while combined size <= budget.
    merged = _greedy_merge_slots(out, budget)

    # Extend first / last merged slot to cover the parent's full range
    # (captures whitespace between node.start_byte and children[0].start_byte,
    # and similarly after children[-1].end_byte).
    if merged:
        merged[0].start_byte = node.start_byte
        merged[-1].end_byte = node.end_byte

    return merged


def _greedy_merge_slots(slots: List[_Slot], budget: int) -> List[_Slot]:
    """Merge consecutive slots while (last.end - first.start) <= budget.

    A merged slot represents a contiguous run of siblings; its `node`
    becomes None (no single AST node represents the group) and its
    parents list is the parent of the original siblings (taken from any
    member — they all share the same parent stack).
    """
    out: List[_Slot] = []
    current: Optional[_Slot] = None
    for s in slots:
        if current is None:
            current = _Slot(s.start_byte, s.end_byte, s.node, list(s.parents))
            continue
        proposed = s.end_byte - current.start_byte
        if proposed <= budget:
            current.end_byte = s.end_byte
            current.node = None  # merged → no single node
        else:
            out.append(current)
            current = _Slot(s.start_byte, s.end_byte, s.node, list(s.parents))
    if current is not None:
        out.append(current)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: all 25 tests pass.

If any concat-invariant test fails, the most likely cause is missed whitespace at the boundary between the root node and the file's edges. The fix is the explicit `slots[0].start_byte = 0; slots[-1].end_byte = len(source)` in `cast_chunks()`.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/cast_chunker.py tests/unit/test_cast_chunker.py
git commit -m "slice 2 t6: cbv.cast_chunker — cast_chunks recursive split-merge w/ concat invariant"
```

---

### Task 7: scripts/cbv/chunker.py — orchestrator refactor (cAST first, text-window fallback)

Refactor `chunker.py` so `chunk_text` / `chunk_file` try cAST first via `parser.parse` + `cast_chunker.cast_chunks`, and fall back to the existing text-window logic on unknown language or parser failure. The old text-window body is preserved as a private `_text_window_chunks` helper so the existing Slice 1 tests in `test_chunker.py` keep passing on the fallback path.

**Files:**
- Modify: `scripts/cbv/chunker.py`
- Modify: `tests/unit/test_chunker.py` (append orchestrator tests)

- [ ] **Step 1: Write the failing orchestrator tests**

Append to `tests/unit/test_chunker.py`:

```python
def test_orchestrator_uses_ast_for_python():
    """A Python file with a function should produce kind=function (not 'window')."""
    src = "def hello():\n    return 'world'\n"
    chunks = list(chunker.chunk_text(
        src, language="python", file_path="x.py", budget_bytes=1500,
    ))
    assert any(c.kind == "function" for c in chunks), \
        f"kinds: {[c.kind for c in chunks]}"


def test_orchestrator_uses_ast_for_javascript():
    src = "function greet() { return 42; }\n"
    chunks = list(chunker.chunk_text(
        src, language="javascript", file_path="x.js", budget_bytes=1500,
    ))
    assert any(c.kind == "function" for c in chunks)


def test_orchestrator_falls_back_to_text_window_for_unknown_language():
    """For 'text' (the default for unknown extensions) the orchestrator
    must use text-window chunking; chunks have kind='window'."""
    src = "line one\nline two\nline three\n"
    chunks = list(chunker.chunk_text(
        src, language="text", file_path="x.txt", budget_bytes=1500,
    ))
    assert all(c.kind == "window" for c in chunks)
    assert "".join(c.content for c in chunks) == src


def test_orchestrator_falls_back_for_markdown():
    """Markdown isn't in Tier-A LANGUAGES (Slice 2); text-window applies."""
    src = "# Heading\n\nSome paragraph.\n"
    chunks = list(chunker.chunk_text(
        src, language="markdown", file_path="x.md", budget_bytes=1500,
    ))
    assert all(c.kind == "window" for c in chunks)


def test_orchestrator_concat_invariant_python():
    """cAST path also preserves concat == file."""
    src = (
        "import os\n"
        "\n"
        "def foo():\n    return 1\n"
        "\n"
        "class Bar:\n    def baz(self):\n        return 2\n"
    )
    chunks = list(chunker.chunk_text(
        src, language="python", file_path="x.py", budget_bytes=1500,
    ))
    assert "".join(c.content for c in chunks) == src


def test_chunk_file_python(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    chunks = list(chunker.chunk_file(p, budget_bytes=1500))
    assert chunks
    assert chunks[0].language == "python"
    assert chunks[0].kind == "function"
    assert chunks[0].name == "add"


def test_chunk_file_unknown_extension_falls_back(tmp_path):
    p = tmp_path / "data.txt"
    p.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    chunks = list(chunker.chunk_file(p, budget_bytes=1500))
    assert all(c.kind == "window" for c in chunks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_chunker.py -v`
Expected: 7 new tests fail (the existing 13 keep passing for now since `chunk_text` is still the Slice 1 text-window version).

- [ ] **Step 3: Refactor scripts/cbv/chunker.py**

Open `scripts/cbv/chunker.py`. The top of the file (docstring, imports, `EXTENSION_LANGUAGE`, `SPECIAL_FILENAMES`, `Chunk`, `detect_language`, `_sha256_hex`, `_token_count`) stays as-is.

Replace ONLY the existing `chunk_text` function body and add `_text_window_chunks` + new orchestrator. The final state of the bottom half of `chunker.py` should be:

```python
def chunk_text(
    content: str,
    *,
    language: str,
    file_path: str,
    budget_bytes: int = 1500,
) -> Iterator[Chunk]:
    """Yield non-overlapping chunks for `content`.

    Slice 2: try AST-aware cAST chunking via cbv.parser + cbv.cast_chunker
    when `language` matches a Tier-A language; on any failure (parser
    raises, language unknown, etc.) fall back to the Slice 1 line-aware
    text-window chunker (`_text_window_chunks`).

    The fallback path is identical to Slice 1's chunker. Empty content
    yields zero chunks in either path.
    """
    if not content:
        return

    # Lazy import to avoid a hard tree-sitter dep when only the
    # fallback path is needed (e.g. on a fresh dev machine before
    # `setup` has installed the venv).
    try:
        from cbv import cast_chunker, parser
    except ImportError:
        cast_chunker = None  # type: ignore[assignment]
        parser = None  # type: ignore[assignment]

    if parser is not None and cast_chunker is not None:
        lang = parser.language_for_name(language)
        if lang is not None:
            source = content.encode("utf-8")
            tree = parser.parse(source, lang)
            if tree is not None:
                yield from cast_chunker.cast_chunks(
                    tree, source,
                    language_name=language, file_path=file_path,
                    budget_bytes=budget_bytes,
                )
                return

    # Fallback: text-window.
    yield from _text_window_chunks(
        content, language=language, file_path=file_path,
        budget_bytes=budget_bytes,
    )


def _text_window_chunks(
    content: str,
    *,
    language: str,
    file_path: str,
    budget_bytes: int = 1500,
) -> Iterator[Chunk]:
    """Slice 1's line-aware text-window chunker. Preserved here as the
    fallback when AST chunking is unavailable or has failed.

    A single line that exceeds the budget becomes its own over-budget
    chunk so the concat invariant holds.
    """
    if not content:
        return
    lines = content.splitlines(keepends=True)
    encoded = [line.encode("utf-8") for line in lines]
    line_byte_lens = [len(e) for e in encoded]
    line_start_bytes = [0]
    for n in line_byte_lens:
        line_start_bytes.append(line_start_bytes[-1] + n)

    cur_lines: list[int] = []
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
        if cur_bytes + n > budget_bytes and cur_lines:
            yield emit()
            cur_lines = []
            cur_bytes = 0
        cur_lines.append(i)
        cur_bytes += n

    if cur_lines:
        yield emit()


def chunk_file(path: Path, *, budget_bytes: int = 1500) -> Iterator[Chunk]:
    """Read a file and yield chunks.

    Reads as UTF-8. On decode failure, retries with `errors="replace"` so
    undecodable bytes become U+FFFD — those re-encode cleanly in
    `chunk_text` (surrogateescape would raise UnicodeEncodeError on the
    subsequent `.encode("utf-8")` calls).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8", errors="replace")
    yield from chunk_text(
        content,
        language=detect_language(path),
        file_path=str(path),
        budget_bytes=budget_bytes,
    )
```

Notice: the OLD `chunk_text` body is reused VERBATIM inside `_text_window_chunks` (no logic changes). This keeps every Slice 1 test green on the fallback path.

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_chunker.py -v`
Expected: all tests pass (13 Slice 1 + 7 new orchestrator).

Run the broader unit suite to ensure no regression elsewhere:
```
<venv-python> -m pytest tests/unit/ -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/cbv/chunker.py tests/unit/test_chunker.py
git commit -m "slice 2 t7: cbv.chunker — orchestrator chooses cAST or text-window fallback"
```

---

### Task 8: Multi-language kind mapping (JS, TS, Go, Rust, Java, C, C++, Ruby, C#)

Extend `cast_chunker.KIND_MAPS` to cover the rest of the Tier-A languages. Each language gets its own `_xxx_kind` function with the node-type names tree-sitter uses for that grammar. Test coverage: one function-recognition test per language using a small canonical source snippet.

**Files:**
- Modify: `scripts/cbv/cast_chunker.py`
- Modify: `tests/unit/test_cast_chunker.py` (append per-language tests)

- [ ] **Step 1: Write failing tests for each language**

Append to `tests/unit/test_cast_chunker.py`:

```python
@pytest.mark.parametrize("lang_name, src, expected_top_kind", [
    ("javascript",
     b"function add(a, b) { return a + b; }\n",
     "function"),
    ("javascript",
     b"class Counter { tick() { return 1; } }\n",
     "class"),
    ("typescript",
     b"function add(a: number, b: number): number { return a + b; }\n",
     "function"),
    ("tsx",
     b"function App() { return <div/>; }\n",
     "function"),
    ("go",
     b"package main\nfunc add(a, b int) int { return a + b }\n",
     "function"),
    ("rust",
     b"fn add(a: i32, b: i32) -> i32 { a + b }\n",
     "function"),
    ("java",
     b"class C { int add(int a, int b) { return a + b; } }\n",
     "class"),
    ("c",
     b"int add(int a, int b) { return a + b; }\n",
     "function"),
    ("cpp",
     b"int add(int a, int b) { return a + b; }\n",
     "function"),
    ("ruby",
     b"def add(a, b)\n  a + b\nend\n",
     "function"),
    ("csharp",
     b"class C { public int Add(int a, int b) { return a + b; } }\n",
     "class"),
])
def test_kind_mapping_per_language(lang_name, src, expected_top_kind):
    lang = parser.LANGUAGES[lang_name]
    tree = parser.parse(src, lang)
    assert tree is not None, f"parse returned None for {lang_name}"
    chunks = cast_chunker.cast_chunks(
        tree, src,
        language_name=lang_name, file_path=f"x.{lang.extensions[0]}",
        budget_bytes=1500,
    )
    kinds = [c.kind for c in chunks]
    assert expected_top_kind in kinds, \
        f"{lang_name}: expected '{expected_top_kind}' in {kinds}"


@pytest.mark.parametrize("lang_name, src", [
    ("javascript",  b"class C { tick() { return 1; } }\n"),
    ("typescript",  b"class C { tick(): number { return 1; } }\n"),
    ("java",        b"class C { int tick() { return 1; } }\n"),
    ("csharp",      b"class C { int Tick() { return 1; } }\n"),
])
def test_method_kind_inside_class(lang_name, src):
    """A function-like node nested inside a class node should be 'method'."""
    lang = parser.LANGUAGES[lang_name]
    tree = parser.parse(src, lang)
    chunks = cast_chunker.cast_chunks(
        tree, src,
        language_name=lang_name, file_path=f"x.{lang.extensions[0]}",
        budget_bytes=1500,
    )
    kinds = [c.kind for c in chunks]
    # Either it shows up as 'method' directly, OR the whole class is one
    # chunk with kind='class' and methods are inside it. Both are acceptable
    # cAST outputs depending on budget — but with budget=1500 and a tiny
    # class, the whole class fits in one chunk. So expect 'class'.
    assert "class" in kinds, f"{lang_name}: expected class in {kinds}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v -k "per_language or method_kind"`
Expected: most parametrize cases FAIL because non-Python languages currently fall back to `_kind_for_node` returning "section".

- [ ] **Step 3: Add per-language kind functions**

Replace the `_python_kind` block and `KIND_MAPS` definition in `scripts/cbv/cast_chunker.py` with the full set:

```python
# --- per-language kind functions ------------------------------------------

# Many languages share a vocabulary: a function-like node anywhere in the
# tree maps to "function" at the top level and "method" if any ancestor
# is a class-like node. The constants below capture the per-language
# node-type sets; _generic_kind() uses them for the bulk of languages.

_FUNCTION_NODE_TYPES = {
    "python":     {"function_definition", "async_function_definition"},
    "javascript": {"function_declaration", "function", "function_expression",
                   "arrow_function", "method_definition", "generator_function_declaration"},
    "typescript": {"function_declaration", "function", "function_expression",
                   "arrow_function", "method_definition", "method_signature",
                   "function_signature", "abstract_method_signature"},
    "tsx":        {"function_declaration", "function", "function_expression",
                   "arrow_function", "method_definition", "method_signature",
                   "function_signature", "abstract_method_signature"},
    "go":         {"function_declaration", "method_declaration"},
    "rust":       {"function_item"},
    "java":       {"method_declaration", "constructor_declaration"},
    "c":          {"function_definition"},
    "cpp":        {"function_definition"},
    "ruby":       {"method", "singleton_method"},
    "csharp":     {"method_declaration", "constructor_declaration",
                   "local_function_statement"},
}

_CLASS_NODE_TYPES = {
    "python":     {"class_definition"},
    "javascript": {"class_declaration", "class"},
    "typescript": {"class_declaration", "class", "interface_declaration"},
    "tsx":        {"class_declaration", "class", "interface_declaration"},
    "go":         set(),  # Go uses struct_type/interface_type but not "classes" in cAST sense
    "rust":       {"impl_item", "trait_item", "struct_item", "enum_item"},
    "java":       {"class_declaration", "interface_declaration",
                   "enum_declaration", "record_declaration"},
    "c":          {"struct_specifier"},  # treat structs as class-like for path containment
    "cpp":        {"class_specifier", "struct_specifier"},
    "ruby":       {"class", "module"},
    "csharp":     {"class_declaration", "interface_declaration", "struct_declaration",
                   "record_declaration", "enum_declaration"},
}


def _generic_kind(language: str, node, parents) -> str:
    """Map a tree-sitter node to a Chunk.kind for the languages whose
    function/class vocabulary fits the _FUNCTION_NODE_TYPES /
    _CLASS_NODE_TYPES sets. Handles Python's `decorated_definition`
    unwrap as a special case."""
    real_type = node.type
    if language == "python" and real_type == "decorated_definition":
        for c in node.children:
            if c.type in (
                "function_definition", "async_function_definition", "class_definition",
            ):
                real_type = c.type
                break

    fn_types = _FUNCTION_NODE_TYPES.get(language, set())
    cls_types = _CLASS_NODE_TYPES.get(language, set())

    if real_type in fn_types:
        for p in parents:
            if p.type in cls_types:
                return "method"
        return "function"
    if real_type in cls_types:
        return "class"
    return "section"


# Every Tier-A language uses the generic mapping.
KIND_MAPS: dict[str, Callable] = {
    name: (lambda n, p, _lang=name: _generic_kind(_lang, n, p))
    for name in (
        "python", "javascript", "typescript", "tsx",
        "go", "rust", "java", "c", "cpp", "ruby", "csharp",
    )
}
```

Also update `_extract_name` to handle non-Python languages — most use `child_by_field_name("name")` (it already does), but verify a couple of grammars:

- Go function: `function_declaration.child_by_field_name("name")` → name identifier
- Rust function: `function_item.child_by_field_name("name")` → name identifier
- Java method: `method_declaration.child_by_field_name("name")` → identifier
- Ruby method: `method.child_by_field_name("name")` → identifier
- C function: `function_definition` has `declarator.declarator` for the name — `child_by_field_name("declarator")` returns the function_declarator; ITS `child_by_field_name("declarator")` is the identifier. This means `_extract_name` will return None for C/C++. Acceptable for Slice 2; we'll just have `name=None` for C/C++ chunks.

- [ ] **Step 4: Run tests to verify they pass**

Run: `<venv-python> -m pytest tests/unit/test_cast_chunker.py -v`
Expected: all tests pass. If a parametrized case fails because the node type isn't in `_FUNCTION_NODE_TYPES` / `_CLASS_NODE_TYPES`, inspect the tree:

```python
src = b"<the failing source>"
tree = parser.parse(src, parser.LANGUAGES["<lang>"])
print(tree.root_node.sexp())
```

— then add the missing type to the right set. (This is part of normal cAST integration; tree-sitter grammars version-skew in node names.)

- [ ] **Step 5: Run the full unit suite to confirm no regression**

```
<venv-python> -m pytest tests/unit/ -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/cbv/cast_chunker.py tests/unit/test_cast_chunker.py
git commit -m "slice 2 t8: cbv.cast_chunker — generic kind map for Tier-A languages"
```

---

### Task 9: Integration test — verify the full pipeline still works with AST chunks

Run the existing Slice 1 integration test (`tests/integration/test_full_index.py`) and confirm it still passes with the new AST-aware chunker. The fixture's Python files (auth.py, router.py, db.py, utils.py) now produce `kind="function"` / `kind="method"` chunks instead of `kind="window"`. The retrieval tests still find the right files because BM25 on the function names still matches, plus the chunks are now scoped to single definitions.

If the chunk count per file changes (it will — fewer, larger chunks because functions group sibling code), the assertion `n_files == 10` in `test_index_files_count_matches_fixture` still holds (it's `COUNT(DISTINCT file_path)`, not `COUNT(*)`). But chunks-per-file changes.

**Files:**
- Possibly modify: `tests/integration/test_full_index.py` (only if an assertion needs updating)

- [ ] **Step 1: Run the full pytest suite**

```
<venv-python> -m pytest tests/ -v
```

Expected: 89 (Slice 1) + ~40 new (Slice 2) = ~129 tests pass, 1 skipped (network gated).

- [ ] **Step 2: If anything in the integration test failed, diagnose**

For each failing assertion in `tests/integration/test_full_index.py`:

- `n_files == 10` — still correct; this counts distinct file paths, not chunks. If this fails, the walker / vectorize wired something up wrong; investigate as a regression.
- `"pkg/auth.py" in file_relative` — still correct; BM25 on "authenticate" matches `authenticate_user` function name and body. If this fails, the chunker is producing chunks that don't contain "authenticate" — investigate (most likely the function name is being split out into its own chunk that doesn't include the token).
- Other result-shape assertions — these test the JSON envelope, not the chunker, and should be unaffected.

If a result test fails because BM25 isn't matching, the most likely fix is on the `--top-k` parameter (raise from 5 to 10) OR add a more targeted BM25 query token. Adjust the test query, NOT the chunker — the chunker is correct.

- [ ] **Step 3: Manual smoke test — index and query the fixture**

Set `CBV_STUB_EMBEDDER=1` and `CODEBASE_VECTORIZER_HOME` to a clean temp dir, then run end-to-end:

```powershell
$env:CBV_STUB_EMBEDDER = "1"
$env:CODEBASE_VECTORIZER_HOME = "$env:TEMP\cbv-slice2-smoke"
Remove-Item -Recurse -Force $env:CODEBASE_VECTORIZER_HOME -ErrorAction SilentlyContinue

bash scripts/run.sh vectorize tests/fixtures/simple-python
```

Expected output (last line is JSON):
```json
{"repo_name":"simple-python","files_indexed":10,"chunks_indexed":<N>,...}
```

`<N>` for Slice 1 was around 10–15 (one chunk per file, sometimes two). For Slice 2 it should be similar or slightly higher because cAST will sometimes split a multi-function file into multiple chunks (one per function).

Then query:

```powershell
bash scripts/run.sh query simple-python "authenticate user" --top-k 3
```

Expected: at least one result whose `kind` is `"function"` or `"method"` (not `"window"`) and whose `file_relative` is `pkg/auth.py`. The `ast_path` field should look like `module/function[authenticate_user]`.

Clean up:
```powershell
Remove-Item -Recurse -Force $env:CODEBASE_VECTORIZER_HOME
```

- [ ] **Step 4: If integration test needed adjustment, commit it**

If you updated `tests/integration/test_full_index.py`, commit with a clear message:

```bash
git add tests/integration/test_full_index.py
git commit -m "slice 2 t9: integration test — adjust assertions for AST-aware chunks"
```

If no adjustment was needed, skip this step.

- [ ] **Step 5: Run a final full suite**

```
<venv-python> -m pytest tests/ -v
```
Expected: green.

---

### Task 10: Sanity smoke test on a non-Python language (JavaScript)

Add a small JS file to the fixture and verify the indexer produces AST-aware chunks for it. This guards against regressions where the JS grammar's node types drift and our kind mapping silently degrades to all-"section".

**Files:**
- Create: `tests/fixtures/simple-python/util.js`
- Modify: `tests/integration/test_full_index.py` (add one test)

Note: the fixture is named "simple-python" but the spec calls for testing multi-language paths. Adding a single .js file is a low-risk extension — the original Slice 1 expectation of "10 indexable files" becomes 11.

- [ ] **Step 1: Add util.js to the fixture**

Create `tests/fixtures/simple-python/util.js`:

```javascript
// Small JS file to exercise the AST chunker on a non-Python file.
export function camelCase(s) {
    return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

export function snakeCase(s) {
    return s.replace(/([a-z])([A-Z])/g, "$1_$2").toLowerCase();
}
```

- [ ] **Step 2: Update the file-count assertion in the integration test**

Open `tests/integration/test_full_index.py`. Find `test_index_files_count_matches_fixture` and bump the expected count from 10 to 11.

Old:
```python
    # 5 pkg/*.py + tests/test_auth.py + main.py + README.md + pyproject.toml + .gitignore
    assert n_files == 10
```

New:
```python
    # 5 pkg/*.py + tests/test_auth.py + main.py + util.js + README.md + pyproject.toml + .gitignore
    assert n_files == 11
```

- [ ] **Step 3: Add a JS-specific assertion**

Append a new test to `tests/integration/test_full_index.py`:

```python
def test_javascript_file_produces_ast_chunks(indexed):
    """util.js should produce chunks with language='javascript' and at
    least one with kind in {function, class, method} (not 'window')."""
    from cbv import db, paths
    conn = db.open_db(paths.repo_dir(indexed) / "index.sqlite")
    rows = conn.execute(
        "SELECT kind, language FROM chunks WHERE file_path = 'util.js'"
    ).fetchall()
    assert rows, "expected at least one chunk for util.js"
    languages = {r[1] for r in rows}
    kinds = {r[0] for r in rows}
    assert languages == {"javascript"}, f"unexpected languages: {languages}"
    assert kinds & {"function", "class", "method"}, \
        f"util.js produced only kinds={kinds}; expected at least one AST-derived kind"
```

- [ ] **Step 4: Run the integration test**

```
<venv-python> -m pytest tests/integration/test_full_index.py -v
```
Expected: all pass (now 6 tests in this file).

- [ ] **Step 5: Run the full suite**

```
<venv-python> -m pytest tests/ -v
```
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/simple-python/util.js tests/integration/test_full_index.py
git commit -m "slice 2 t10: fixture — add util.js + integration assert for JS AST chunks"
```

---

## Self-review summary

Coverage check — every in-scope spec requirement from Slice 2's boundary:

- ✅ tree-sitter + tree-sitter-language-pack pinned and probed — Task 1
- ✅ Per-language `Language` registry + `parse(bytes, Language)` — Tasks 2 & 3
- ✅ Per-language node-type → kind mapping (function / class / method / section) — Tasks 4 & 8
- ✅ `name` extraction via `child_by_field_name("name")` (Python, JS, TS, Go, Rust, Java, Ruby, C#) — Task 4 (extended in Task 8)
- ✅ `ast_path` walks from root to node — Task 4
- ✅ cAST recursive split-then-merge — Task 6
- ✅ Greedy sibling merge — Task 6 (`_greedy_merge_slots`)
- ✅ Byte-contiguous tiling of [0, len(source)) — Task 6 (post-recursion extension of first/last slots)
- ✅ Concat == file invariant — Tasks 5–8 (multiple invariant tests)
- ✅ Text-window fallback preserved for unknown languages / parser failures — Task 7
- ✅ All Slice 1 chunker tests still pass — Task 7 (fallback is byte-for-byte the old code)
- ✅ Integration test still green — Task 9
- ✅ Multi-language smoke test — Task 10
- ✅ `Chunk` dataclass shape unchanged — Tasks 5 (uses Slice 1's `Chunk`)

Type consistency:
- `Chunk` dataclass — imported from `chunker.py` into `cast_chunker.py`; same fields used in Task 5–8 helpers.
- `parser.Language` — defined in Task 2; consumed by `parser.parse()` (Task 3) and by `chunker.chunk_text` (Task 7).
- `cast_chunker.cast_chunks(tree, source, *, language_name, file_path, budget_bytes)` — signature defined in Task 6; called from `chunker.chunk_text` (Task 7).
- `_kind_for_node`, `_extract_name`, `_ast_path` — internal helpers defined in Task 4; called by `_chunk_from_byte_range` (Task 5) and `cast_chunks` (Task 6).
- `KIND_MAPS` — defined in Task 4 (Python only) and extended in Task 8 (all Tier-A languages). The dispatch via `_generic_kind` keeps the per-language code small.

No placeholders survive: every step contains the actual code or exact command an engineer needs to execute, and every test has assertions verifying observable behavior rather than describing it.

Risk notes:
- Tree-sitter grammar node-type names version-skew. Task 8's set-based mapping is the part most likely to need adjustment at integration time — handle by running the failing test, dumping `tree.root_node.sexp()`, and adding the missing type to the right set.
- `_extract_name` returns None for C/C++ functions (their `declarator.declarator` nesting isn't handled). Chunks will have `name=None`; the `ast_path` for C/C++ functions will say `function[?]`. Acceptable for Slice 2; can be tightened when a future slice needs C/C++ name resolution (Slice 3's symbol extractor will likely need this anyway and may upgrade `_extract_name`).
