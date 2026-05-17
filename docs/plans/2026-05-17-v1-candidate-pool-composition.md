# v1 Candidate-Pool Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make implementation source code reliably enter the retrieval candidate pool by classifying every file into a kind and making candidate generation, fusion, graph seeding, and clustering category-aware — so docs, agent/meta files, tests, and vendored code can no longer crowd real code out of the fixed per-lane budget.

**Architecture:** A pure, path-based `classify()` assigns each file one of six categories (`source`, `config`, `test`, `docs`, `meta`, `vendor`). The category rides on `WalkEntry` → `Chunk` → a new `chunks.category` column. The `query` full lane then generates candidates in two tiers — a guaranteed primary pool (`source`+`config`) and a smaller demoted context pool (`test`+`docs`) — excludes `meta`/`vendor` entirely, weights the context tier down in RRF, and seeds graph expansion only from primary chunks. Concept clustering is restricted to `source`+`config`. This is a *composition* fix: it changes what is in the pool, not how code behavior is reasoned about.

**Tech Stack:** Python 3.12, SQLite + FTS5 + `sqlite-vec`, `pytest`. No new dependencies.

**Out of scope (explicitly deferred):** dense-embedding query/passage instructions; runtime-relevance / call-graph centrality scoring; framework-aware config handling; generated-file detection; vendored-code content analysis. These are v2.

**Schema impact:** This plan adds a `chunks.category` column and bumps `SCHEMA_VERSION` to `1.1`. Existing on-disk indexes become legacy and must be re-vectorized (`assert_schema_v1` already surfaces a clear message). The test suite is unaffected — tests build fresh indexes per run.

**Test execution note:** The suite imports `cbv`; run `pytest` with the repo's `scripts/` directory on `PYTHONPATH` (the existing suite already relies on this). All paths below are relative to the repo root.

---

## File Structure

**New files:**
- `scripts/cbv/classify.py` — pure file-kind classifier. One responsibility: map a repo-relative POSIX path to a category string.
- `tests/unit/test_classify.py` — classifier unit tests.

**Modified files:**
- `scripts/cbv/walker.py` — add `category` to `WalkEntry`; set it in `walk()`.
- `scripts/cbv/chunker.py` — add defaulted `category` field to the `Chunk` dataclass.
- `scripts/cbv/db.py` — add `category` column + index to `chunks` DDL; bump `SCHEMA_VERSION`.
- `scripts/cbv/commands/vectorize.py` — flow `category` from `WalkEntry` into `Chunk` and the `chunks` INSERT/SELECT; write `db.SCHEMA_VERSION`; restrict clustering input to `source`+`config`.
- `scripts/cbv/commands/query.py` — category filters on `_bm25`/`_dense`; per-ranking weights in `_rrf`; tiered full-lane generation; source-first graph seeds; `_query_symbol_token` punctuation fix.

**Test files touched:** `tests/unit/test_classify.py` (new), `tests/unit/test_walker.py`, `tests/unit/test_chunker.py`, `tests/unit/test_db.py`, `tests/unit/test_query_cmd.py`, `tests/integration/test_query_lanes.py`, `tests/integration/test_full_index.py`.

---

## Task 1: File-kind classifier

**Files:**
- Create: `scripts/cbv/classify.py`
- Test: `tests/unit/test_classify.py`

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_classify.py`:

```python
import importlib


def _classify():
    return importlib.import_module("cbv.classify").classify


def test_classifies_the_concrete_pollution_examples():
    classify = _classify()
    cases = {
        "scripts/cbv/clusters.py": "source",
        "src/app/main.go": "source",
        "tests/unit/test_clusters.py": "test",
        "tests/fixtures/simple-python/main.py": "test",
        "packages/web/src/Button.spec.tsx": "test",
        "docs/HANDOFF.md": "docs",
        "docs/plans/2026-05-16-intent.md": "docs",
        "README.md": "docs",
        "specs/2026-05-14-design.md": "docs",
        ".claude/skills/foo/SKILL.md": "meta",
        ".cursor/rules.md": "meta",
        "CLAUDE.md": "meta",
        ".github/workflows/ci.yml": "config",
        "package.json": "config",
        "frontend/package.json": "config",
        "Dockerfile": "config",
        "vite.config.ts": "config",
        "pyproject.toml": "config",
        "node_modules/react/index.js": "vendor",
        "vendor/github.com/pkg/errors.go": "vendor",
    }
    for path, expected in cases.items():
        assert classify(path) == expected, f"{path} -> {classify(path)}, want {expected}"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cbv.classify'`.

- [x] **Step 3: Write minimal implementation**

Create `scripts/cbv/classify.py`:

```python
"""Path-based file-kind classification for candidate-pool composition.

Pure and language-agnostic: maps a repo-relative POSIX path to one of six
categories. No file content is read. Heuristic by design; v2 refines it.
"""
from __future__ import annotations

from pathlib import PurePosixPath

CATEGORIES = ("source", "config", "test", "docs", "meta", "vendor")

_VENDOR_SEGMENTS = {
    "node_modules", "vendor", "third_party", "bower_components",
    "site-packages", ".venv", "venv", ".yarn", "pods", ".pnp",
}
_META_SEGMENTS = {
    ".claude", ".claude-plugin", ".codex", ".codex-plugin", ".cursor",
    ".gemini", ".kiro", ".agents", ".codebuddy",
}
# NOTE: .github is deliberately NOT meta -- .github/workflows/*.yml is CI/build
# config and is classified `config` by the _CONFIG_EXTS rule below.
_META_NAMES = {"claude.md", "agents.md", "gemini.md", ".cursorrules"}
_TEST_SEGMENTS = {"test", "tests", "__tests__", "e2e", "fixtures", "testdata"}
_DOC_SEGMENTS = {
    "docs", "doc", "documentation", "examples", "example", "samples", "specs",
}
_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc"}
_CONFIG_NAMES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "tsconfig.json", "jsconfig.json", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "makefile", "cargo.toml", "cargo.lock", "go.mod",
    "go.sum", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "pipfile", "gemfile", "build.gradle", "pom.xml", ".gitignore",
    ".prettierrc", ".prettierignore", ".editorconfig",
}
_CONFIG_EXTS = {".toml", ".ini", ".cfg", ".lock", ".yaml", ".yml", ".json"}


def classify(relpath: str) -> str:
    """Return the file-kind category for a repo-relative POSIX path."""
    p = PurePosixPath(relpath)
    segs = {s.lower() for s in p.parts}
    name = p.name.lower()
    ext = p.suffix.lower()
    stem_no_ext = name[: -len(ext)] if ext else name

    if segs & _VENDOR_SEGMENTS:
        return "vendor"
    if (segs & _META_SEGMENTS) or name in _META_NAMES:
        return "meta"
    if segs & _TEST_SEGMENTS:
        return "test"
    if ".test." in name or ".spec." in name or name.startswith("test_"):
        return "test"
    if segs & _DOC_SEGMENTS:
        return "docs"
    if name in _CONFIG_NAMES or ext in _CONFIG_EXTS:
        return "config"
    if stem_no_ext.endswith(".config"):  # vite.config.ts, eslint.config.mjs
        return "config"
    if ext in _DOC_EXTS:
        return "docs"
    if ".example" in name or ".sample" in name:
        return "docs"
    return "source"
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_classify.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/classify.py tests/unit/test_classify.py
git commit -m "Add path-based file-kind classifier"
```

---

## Task 2: Carry the category on WalkEntry

**Files:**
- Modify: `scripts/cbv/walker.py`
- Test: `tests/unit/test_walker.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_walker.py`:

```python
def test_walk_entries_carry_a_file_category(tmp_path):
    from cbv import walker

    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")

    by_rel = {e.relpath.as_posix(): e for e in walker.walk(tmp_path)}

    assert by_rel["scripts/app.py"].category == "source"
    assert by_rel["docs/guide.md"].category == "docs"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_walker.py::test_walk_entries_carry_a_file_category -v`
Expected: FAIL — `AttributeError: 'WalkEntry' object has no attribute 'category'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/walker.py`, add the import near the top (after `import pathspec`):

```python
from cbv import classify as _classify
```

Add the field to `WalkEntry`:

```python
@dataclass(frozen=True)
class WalkEntry:
    abspath: Path
    relpath: Path
    size_bytes: int
    category: str
```

Update the `yield` at the end of `walk()`:

```python
        yield WalkEntry(
            abspath=p,
            relpath=rel,
            size_bytes=size,
            category=_classify.classify(rel_posix),
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_walker.py -v`
Expected: PASS (new test + all existing walker tests).

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/walker.py tests/unit/test_walker.py
git commit -m "Tag each WalkEntry with its file category"
```

---

## Task 3: Add a category field to the Chunk dataclass

**Files:**
- Modify: `scripts/cbv/chunker.py:56-80`
- Test: `tests/unit/test_chunker.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_chunker.py`:

```python
def test_chunk_has_a_category_field_defaulting_to_source():
    from cbv.chunker import Chunk

    c = Chunk(
        file_path="a.py", language="python", kind="window", name=None,
        ast_path=None, start_line=1, end_line=1, start_byte=0, end_byte=1,
        content="x", content_hash="h", token_count=1,
    )
    assert c.category == "source"

    c2 = Chunk(
        file_path="a.py", language="python", kind="window", name=None,
        ast_path=None, start_line=1, end_line=1, start_byte=0, end_byte=1,
        content="x", content_hash="h", token_count=1, category="docs",
    )
    assert c2.category == "docs"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_chunker.py::test_chunk_has_a_category_field_defaulting_to_source -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'category'`.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/chunker.py`, add `category` as the last field of `Chunk` (a default keeps existing `Chunk(...)` call sites in `chunker.py` and `cast_chunker.py` working — they produce chunks that `vectorize.py` re-wraps with the real category):

```python
    content: str
    content_hash: str
    token_count: int
    category: str = "source"
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_chunker.py tests/unit/test_cast_chunker.py -v`
Expected: PASS (new test + all existing chunker/cast_chunker tests — the default keeps them green).

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/chunker.py tests/unit/test_chunker.py
git commit -m "Add a defaulted category field to Chunk"
```

---

## Task 4: Add the category column to the DB schema

**Files:**
- Modify: `scripts/cbv/db.py:32` (SCHEMA_VERSION), `:37-59` (chunks DDL + indexes)
- Test: `tests/unit/test_db.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_db.py`:

```python
def test_chunks_table_has_a_category_column(tmp_path):
    from cbv import db

    conn = db.open_db(tmp_path / "index.sqlite")
    try:
        db.init_schema(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
        assert "category" in cols
    finally:
        conn.close()


def test_schema_version_is_bumped_to_1_1():
    from cbv import db

    assert db.SCHEMA_VERSION == "1.1"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_db.py::test_chunks_table_has_a_category_column tests/unit/test_db.py::test_schema_version_is_bumped_to_1_1 -v`
Expected: FAIL — `category` not in columns; `SCHEMA_VERSION == "1.0"`.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/db.py`, bump the version constant:

```python
SCHEMA_VERSION = "1.1"
```

Add the column to `DDL_CHUNKS` (last column, before the closing paren):

```python
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
    token_count INTEGER NOT NULL,
    category TEXT NOT NULL DEFAULT 'source'
);
"""
```

Add a category index to `DDL_CHUNKS_IDX`:

```python
DDL_CHUNKS_IDX = """
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_kind ON chunks(kind);
CREATE INDEX IF NOT EXISTS idx_chunks_category ON chunks(category);
"""
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_db.py -v`
Expected: PASS. If any existing test hardcodes the literal `"1.0"` schema version, change that literal to `db.SCHEMA_VERSION` and re-run — the version is now sourced from the constant, not duplicated.

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/db.py tests/unit/test_db.py
git commit -m "Add chunks.category column; bump schema to 1.1"
```

---

## Task 5: Persist the category through the vectorize pipeline

**Files:**
- Modify: `scripts/cbv/commands/vectorize.py` — `_chunk_selected_entries` (~491-525), the `chunks` INSERT (~329-336), `_load_chunks` (~636-660), `_write_meta` (~1062-1085)
- Test: `tests/integration/test_full_index.py`

- [x] **Step 1: Write the failing test**

Add to `tests/integration/test_full_index.py` (a fixture-backed index already exists in this file; this test asserts categories were persisted):

```python
def test_indexed_chunks_carry_their_file_category(tmp_path, monkeypatch):
    """Chunks from a docs file are stored with category='docs', code with 'source'."""
    import sqlite3
    from cbv.commands import vectorize as vec
    from cbv import cli

    src = tmp_path / "repo"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg" / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (src / "README.md").write_text("# project\n\nsome prose here\n", encoding="utf-8")

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    out = tmp_path / "index"
    ns = cli.build_parser().parse_args(
        ["vectorize", str(src), "--output-dir", str(out)]
    )
    vec.run(ns)

    conn = sqlite3.connect(out / "index.sqlite")
    try:
        cats = dict(conn.execute(
            "SELECT file_path, category FROM chunks GROUP BY file_path"
        ).fetchall())
    finally:
        conn.close()
    assert cats["pkg/app.py"] == "source"
    assert cats["README.md"] == "docs"
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_full_index.py::test_indexed_chunks_carry_their_file_category -v`
Expected: FAIL — `sqlite3.OperationalError: no such column: category` (the INSERT does not yet write it), or `KeyError`.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/commands/vectorize.py`:

**(a)** In `_chunk_selected_entries`, the chunk re-wrap loop — pass the entry's category:

```python
        for c in file_chunks:
            chunks_buf.append(
                chunker.Chunk(
                    file_path=rel_file_path,
                    language=c.language,
                    kind=c.kind,
                    name=c.name,
                    ast_path=c.ast_path,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    start_byte=c.start_byte,
                    end_byte=c.end_byte,
                    content=c.content,
                    content_hash=c.content_hash,
                    token_count=c.token_count,
                    category=entry.category,
                )
            )
```

**(b)** The `INSERT INTO chunks` statement — add `category` to the column list, one more `?`, and `c.category` to the values tuple:

```python
                cur = conn.execute(
                    "INSERT INTO chunks (file_path, language, kind, name, ast_path, "
                    "start_line, end_line, start_byte, end_byte, content, "
                    "content_hash, token_count, category) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (c.file_path, c.language, c.kind, c.name, c.ast_path,
                     c.start_line, c.end_line, c.start_byte, c.end_byte,
                     c.content, c.content_hash, c.token_count, c.category),
                )
```

**(c)** `_load_chunks` — add `category` to the SELECT and the `Chunk(...)` construction so reloaded chunks (incremental mode) keep their category:

```python
def _load_chunks(conn) -> tuple[list[int], list[chunker.Chunk]]:
    rows = conn.execute(
        "SELECT id, file_path, language, kind, name, ast_path, "
        "start_line, end_line, start_byte, end_byte, content, "
        "content_hash, token_count, category FROM chunks ORDER BY id"
    ).fetchall()
    chunk_ids = [int(row[0]) for row in rows]
    chunks = [
        chunker.Chunk(
            file_path=row[1], language=row[2], kind=row[3], name=row[4],
            ast_path=row[5], start_line=row[6], end_line=row[7],
            start_byte=row[8], end_byte=row[9], content=row[10],
            content_hash=row[11], token_count=row[12], category=row[13],
        )
        for row in rows
    ]
    return chunk_ids, chunks
```

**(d)** In `_write_meta`, source the schema version from the constant instead of the literal `"1.0"`:

```python
        ("schema_version", db.SCHEMA_VERSION),
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_full_index.py tests/unit/test_vectorize_cmd.py tests/integration/test_incremental.py -v`
Expected: PASS (new test + existing full-index, vectorize, and incremental tests).

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/commands/vectorize.py tests/integration/test_full_index.py
git commit -m "Persist chunk file category through the vectorize pipeline"
```

---

## Task 6: Fix the symbol-token punctuation bug

**Files:**
- Modify: `scripts/cbv/commands/query.py:272-274` (`_query_symbol_token`)
- Test: `tests/unit/test_query_cmd.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_query_cmd.py`:

```python
def test_query_symbol_token_strips_trailing_punctuation():
    from cbv.commands.query import _query_symbol_token

    assert _query_symbol_token("how does the codebase call UMAP?") == "UMAP"
    assert _query_symbol_token("where is cluster_embeddings,") == "cluster_embeddings"
    assert _query_symbol_token("find Foo") == "Foo"
    assert _query_symbol_token("") == ""
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_query_cmd.py::test_query_symbol_token_strips_trailing_punctuation -v`
Expected: FAIL — returns `"UMAP?"` (with the `?`).

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/commands/query.py`, replace `_query_symbol_token`:

```python
def _query_symbol_token(query: str) -> str:
    parts = query.strip().split()
    if not parts:
        return ""
    return parts[-1].strip(".,:;()[]{}<>!?\"'`")
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_query_cmd.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/commands/query.py tests/unit/test_query_cmd.py
git commit -m "Strip trailing punctuation from the query symbol token"
```

---

## Task 7: Add category filters to the BM25 and dense lanes

**Files:**
- Modify: `scripts/cbv/commands/query.py` — `_bm25` (~171-178), `_dense` (~191-207)
- Test: `tests/integration/test_query_lanes.py`

- [x] **Step 1: Write the failing test**

Add to `tests/integration/test_query_lanes.py` (build a tiny stub-embedded index with one source file and one docs file, then assert the filter):

```python
def test_bm25_and_dense_accept_a_category_filter(tmp_path, monkeypatch):
    import numpy as np
    from cbv import db, embedder, quantize
    from cbv.commands import query as Q

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    conn = db.open_db(tmp_path / "index.sqlite")
    try:
        db.init_schema(conn)
        # one 'source' chunk and one 'docs' chunk, both containing "alpha"
        for cid, (fp, cat) in enumerate(
            [("a.py", "source"), ("b.md", "docs")], start=1
        ):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python", "window", None, None, 1, 1, 0, 5,
                 "alpha", f"h{cid}", 1, cat),
            )
            emb = embedder.make_embedder()
            q8 = quantize.quantize_int8(emb.embed(["alpha"])[0].reshape(1, -1))[0]
            db.insert_embedding(conn, cid, q8)
        conn.commit()

        bm25_all = Q._bm25(conn, "alpha", limit=50)
        bm25_src = Q._bm25(conn, "alpha", limit=50, categories={"source"})
        assert set(bm25_all) == {1, 2}
        assert set(bm25_src) == {1}

        emb = embedder.make_embedder()
        q8 = quantize.quantize_int8(emb.embed(["alpha"])[0].reshape(1, -1))[0]
        dense_src = Q._dense(conn, q8, limit=50, categories={"source"})
        assert set(dense_src) == {1}
    finally:
        conn.close()
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_query_lanes.py::test_bm25_and_dense_accept_a_category_filter -v`
Expected: FAIL — `_bm25()`/`_dense()` got an unexpected keyword argument `categories`.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/commands/query.py`, add a module constant near `RRF_K`:

```python
_DENSE_OVERFETCH = 6  # KNN over-fetch factor so category filtering still fills the limit
```

Replace `_bm25`:

```python
def _bm25(conn, query: str, *, limit: int, categories: set[str] | None = None) -> Dict[int, float]:
    """Return {chunk_id: bm25 rank-score} for top BM25 hits, optionally
    restricted to the given file categories."""
    if categories:
        placeholders = ",".join("?" for _ in categories)
        rows = conn.execute(
            "SELECT chunks_fts.rowid, bm25(chunks_fts) FROM chunks_fts "
            "JOIN chunks ON chunks.id = chunks_fts.rowid "
            f"WHERE chunks_fts MATCH ? AND chunks.category IN ({placeholders}) "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (_fts_escape(query), *sorted(categories), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT rowid, bm25(chunks_fts) FROM chunks_fts "
            "WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
            (_fts_escape(query), limit),
        ).fetchall()
    return {int(r[0]): float(r[1]) for r in rows}
```

Replace `_dense`:

```python
def _dense(conn, q_int8: np.ndarray, *, limit: int, categories: set[str] | None = None) -> Dict[int, float]:
    """Return {chunk_id: -distance} for top sqlite-vec KNN hits, optionally
    restricted to the given file categories.

    sqlite-vec 0.1.x KNN cannot filter on a joined column, so when a category
    filter is set we over-fetch k = limit * _DENSE_OVERFETCH nearest, then
    filter and truncate in Python.
    """
    qparam = db.vec_int8_param(q_int8)
    if categories:
        rows = conn.execute(
            "SELECT v.chunk_id, v.distance FROM vec_chunks v "
            "JOIN chunks c ON c.id = v.chunk_id "
            "WHERE v.embedding MATCH vec_int8(?) AND v.k = ? "
            "ORDER BY v.distance",
            (qparam, limit * _DENSE_OVERFETCH),
        ).fetchall()
        allowed = {
            int(r[0])
            for r in conn.execute(
                "SELECT id FROM chunks WHERE category IN ("
                + ",".join("?" for _ in categories)
                + ")",
                tuple(sorted(categories)),
            )
        }
        out: Dict[int, float] = {}
        for chunk_id, distance in rows:
            cid = int(chunk_id)
            if cid in allowed:
                out[cid] = -float(distance)
            if len(out) >= limit:
                break
        return out
    rows = conn.execute(
        "SELECT chunk_id, distance FROM vec_chunks "
        "WHERE embedding MATCH vec_int8(?) AND k = ? ORDER BY distance",
        (qparam, limit),
    ).fetchall()
    return {int(r[0]): -float(r[1]) for r in rows}
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_query_lanes.py -v`
Expected: PASS (new test + existing query-lane tests — the default `categories=None` preserves current behavior).

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/commands/query.py tests/integration/test_query_lanes.py
git commit -m "Add optional category filters to the BM25 and dense lanes"
```

---

## Task 8: Per-ranking weights in RRF fusion

**Files:**
- Modify: `scripts/cbv/commands/query.py` — `_rrf` (~277-303)
- Test: `tests/unit/test_query_cmd.py`

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_query_cmd.py`:

```python
def test_rrf_applies_per_ranking_weights():
    from cbv.commands.query import _rrf

    # Two rankings, each with one unique chunk at rank 1. Equal weights -> tie.
    equal = _rrf([{1: 9.0}, {2: 9.0}], k=60, source_names=["a", "b"])
    assert {cid for cid, _, _ in equal} == {1, 2}
    assert equal[0][1] == equal[1][1]

    # Down-weighting the second ranking puts chunk 1 strictly ahead.
    weighted = _rrf(
        [{1: 9.0}, {2: 9.0}], k=60, source_names=["a", "b"], weights=[1.0, 0.1]
    )
    assert weighted[0][0] == 1
    assert weighted[0][1] > weighted[1][1]
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_query_cmd.py::test_rrf_applies_per_ranking_weights -v`
Expected: FAIL — `_rrf()` got an unexpected keyword argument `weights`.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/commands/query.py`, replace `_rrf`:

```python
def _rrf(
    rankings: List[Dict[int, float]],
    *,
    k: int,
    source_names: list[str] | None = None,
    weights: list[float] | None = None,
) -> List[tuple]:
    """Reciprocal Rank Fusion with optional per-ranking weights.

    `weights[i]` multiplies every RRF contribution from `rankings[i]`; it
    defaults to 1.0 for every ranking (classic RRF). `sources` is a tag list
    per chunk for debug output.
    """
    if source_names is None:
        source_names = [f"source_{idx}" for idx in range(len(rankings))]
    if len(source_names) != len(rankings):
        raise ValueError("source_names length must match rankings length")
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights length must match rankings length")

    aggregate: Dict[int, float] = {}
    sources: Dict[int, list] = {}
    for tag, ranking, weight in zip(source_names, rankings, weights):
        if tag == "bm25":
            sorted_ids = [cid for cid, _ in sorted(ranking.items(), key=lambda kv: kv[1])]
        else:
            sorted_ids = [cid for cid, _ in sorted(ranking.items(), key=lambda kv: -kv[1])]
        for rank, cid in enumerate(sorted_ids, start=1):
            aggregate[cid] = aggregate.get(cid, 0.0) + weight * (1.0 / (k + rank))
            sources.setdefault(cid, []).append(tag)
    fused = sorted(
        ((cid, score, sources[cid]) for cid, score in aggregate.items()),
        key=lambda t: -t[1],
    )
    return fused
```

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_query_cmd.py -v`
Expected: PASS (new test + existing — omitting `weights` is unchanged behavior).

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/commands/query.py tests/unit/test_query_cmd.py
git commit -m "Support per-ranking weights in RRF fusion"
```

---

## Task 9: Tiered, source-first full-lane candidate generation

**Files:**
- Modify: `scripts/cbv/commands/query.py` — `run()` full-lane branch (~72-102)
- Test: `tests/integration/test_query_lanes.py`

This task wires the category infrastructure into the full lane: a guaranteed primary pool (`source`+`config`), a smaller demoted context pool (`test`+`docs`), `meta`/`vendor` excluded entirely, context contributions down-weighted in RRF, and graph-expansion seeds drawn only from primary chunks.

- [x] **Step 1: Write the failing test**

Add to `tests/integration/test_query_lanes.py`:

```python
def test_full_lane_keeps_a_source_chunk_above_a_swarm_of_docs(tmp_path, monkeypatch):
    """A lone source chunk must survive a candidate pool flooded with docs."""
    import argparse
    import io
    import json
    import sys
    from cbv import db, embedder, quantize
    from cbv.commands import query as Q
    from cbv import paths

    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    monkeypatch.setenv("CBV_STUB_RERANKER", "1")
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repo_dir = paths.repo_dir("polltest")
    repo_dir.mkdir(parents=True, exist_ok=True)
    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        db.init_schema(conn)
        emb = embedder.make_embedder()
        rows = [("src/clusters.py", "source", "call umap reduce dimensionality")]
        rows += [
            (f"docs/plan_{i}.md", "docs", "how does the codebase call things")
            for i in range(60)
        ]
        for cid, (fp, cat, content) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO chunks (id, file_path, language, kind, name, "
                "ast_path, start_line, end_line, start_byte, end_byte, content, "
                "content_hash, token_count, category) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, fp, "python" if cat == "source" else "markdown", "window",
                 None, None, 1, 1, 0, len(content), content, f"h{cid}",
                 len(content.split()), cat),
            )
            q8 = quantize.quantize_int8(emb.embed([content])[0].reshape(1, -1))[0]
            db.insert_embedding(conn, cid, q8)
        db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
        conn.commit()
    finally:
        conn.close()

    ns = argparse.Namespace(
        repo="polltest", question="how does the codebase call umap",
        lane="full", top_k=10,
    )
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = Q.run(ns)
    finally:
        sys.stdout = old
    assert rc == 0
    result = json.loads(buf.getvalue().strip().splitlines()[-1])
    files = [r["file_relative"] for r in result["results"]]
    assert "src/clusters.py" in files
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_query_lanes.py::test_full_lane_keeps_a_source_chunk_above_a_swarm_of_docs -v`
Expected: FAIL — `src/clusters.py` absent from `results` (the lone source chunk is crowded out by 60 docs chunks under the category-blind top-50 budget).

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/commands/query.py`, add module constants near `RRF_K`:

```python
PRIMARY_CATEGORIES = {"source", "config"}
CONTEXT_CATEGORIES = {"test", "docs"}
CONTEXT_RRF_WEIGHT = 0.3  # context-tier RRF contributions are demoted vs primary
```

Replace the `else:` (full-lane) branch inside `run()` — the block currently spanning the `bm25_hits = _bm25(...)` line through the `fused = _rrf([...])` assignment — with:

```python
        else:
            # Primary tier: guaranteed pool of implementation code.
            bm25_primary = _bm25(conn, ns.question, limit=50, categories=PRIMARY_CATEGORIES)
            emb = embedder.make_embedder()
            qv = emb.embed([ns.question])[0]
            q_int8 = quantize.quantize_int8(qv.reshape(1, -1))[0]
            dense_primary = _dense(conn, q_int8, limit=50, categories=PRIMARY_CATEGORIES)
            sym_hits = _symbol_exact(conn, ns.question, limit=50)

            # Context tier: tests + docs, smaller budget, demoted in fusion.
            # meta/ and vendor/ chunks are generated by no lane -> excluded.
            bm25_context = _bm25(conn, ns.question, limit=20, categories=CONTEXT_CATEGORIES)
            dense_context = _dense(conn, q_int8, limit=20, categories=CONTEXT_CATEGORIES)

            # Seeds for graph expansion + PPR come only from the primary tier.
            primary_seed = _rrf(
                [bm25_primary, dense_primary, sym_hits],
                k=RRF_K,
                source_names=["bm25", "dense", "symbol"],
            )
            seed_ids = [cid for cid, _, _ in primary_seed[:20]]
            expansion = _graph_expand(conn, seed_ids)
            expansion_ids = list(expansion)
            ppr_candidate_ids = list(dict.fromkeys([*seed_ids, *expansion_ids]))
            ppr_hits = graph.personalized_pagerank(
                conn,
                seed_ids,
                expansion_chunk_ids=expansion_ids,
                candidate_chunk_ids=ppr_candidate_ids,
                iterations=10,
            )
            fused = _rrf(
                [bm25_primary, dense_primary, sym_hits, expansion, ppr_hits,
                 bm25_context, dense_context],
                k=RRF_K,
                source_names=["bm25", "dense", "symbol", "graph", "ppr",
                              "bm25", "dense"],
                weights=[1.0, 1.0, 1.0, 1.0, 1.0,
                         CONTEXT_RRF_WEIGHT, CONTEXT_RRF_WEIGHT],
            )
```

Note: `_symbol_exact` is left unfiltered — its rows come from `nodes`, which are built only from source files, so it is already source-scoped. The `bm25_hits`/`dense_hits` names used later in `run()` are replaced by the tiered names above; no code after the `fused = _rrf(...)` line references the old names (the candidate loop consumes `fused` only) — verify this during Step 4.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_query_lanes.py tests/unit/test_query_cmd.py tests/integration/test_relate_cmd.py -v`
Expected: PASS. If a `NameError` for `bm25_hits`/`dense_hits` appears, a later line in `run()` still references the pre-tier names — update it to read from `fused`.

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/commands/query.py tests/integration/test_query_lanes.py
git commit -m "Generate full-lane candidates source-first with a demoted context tier"
```

---

## Task 10: Restrict concept clustering to source and config chunks

**Files:**
- Modify: `scripts/cbv/commands/vectorize.py` — `_build_concept_cluster_plan` (~888-935)
- Test: `tests/unit/test_clusters.py` or `tests/unit/test_vectorize_cmd.py`

Concept clustering must run over implementation code only, so UMAP/HDBSCAN form code concepts, not "planning doc" clusters. Chunks outside `source`/`config` are assigned no cluster (cluster label `-1`, membership `0.0`).

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_vectorize_cmd.py`:

```python
def test_concept_cluster_plan_ignores_non_code_chunks(monkeypatch):
    import numpy as np
    from cbv import chunker
    from cbv.commands import vectorize as vec

    def mk(cat):
        return chunker.Chunk(
            file_path=f"{cat}.x", language="python", kind="window", name=None,
            ast_path=None, start_line=1, end_line=1, start_byte=0, end_byte=1,
            content=cat, content_hash=cat, token_count=1, category=cat,
        )

    chunks = [mk("source")] * 6 + [mk("docs")] * 6
    embeddings = np.vstack([
        np.ones((6, 8), dtype="float32"),
        np.zeros((6, 8), dtype="float32"),
    ])
    warnings: list[str] = []
    plan = vec._build_concept_cluster_plan(chunks, embeddings, warnings)
    assert plan is not None
    cluster_rows, member_rows = plan
    # Only the 6 source-chunk positions (0..5) may appear as cluster members.
    member_positions = {pos for pos, _, _ in member_rows}
    assert member_positions <= set(range(6))
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_vectorize_cmd.py::test_concept_cluster_plan_ignores_non_code_chunks -v`
Expected: FAIL — docs-chunk positions (6..11) appear as cluster members.

- [x] **Step 3: Write minimal implementation**

In `scripts/cbv/commands/vectorize.py`, add a module constant near the top (after `FLOW_EDGE_WEIGHTS`):

```python
CLUSTER_CATEGORIES = {"source", "config"}
```

In `_build_concept_cluster_plan`, immediately after the `if not chunks_buf: return [], []` guard, mask out non-code positions before clustering:

```python
    embeddings = embeddings.astype("float32", copy=False)
    if len(embeddings) != len(chunks_buf):
        warnings.append(
            "concept clustering failed: embedding count did not match planned chunks"
        )
        return None

    code_positions = [
        i for i, c in enumerate(chunks_buf) if c.category in CLUSTER_CATEGORIES
    ]
    if not code_positions:
        return [], []
```

Then cluster only `embeddings[code_positions]`, and translate the clusterer's local indices back to global chunk positions when building `grouped`. Replace the `result = clusters.cluster_embeddings(embeddings)` line and the loop that builds `grouped` with:

```python
    try:
        result = clusters.cluster_embeddings(embeddings[code_positions])
    except Exception as e:
        warnings.append(f"concept clustering failed: {e}")
        return None
    grouped: dict[int, list[int]] = {}
    for local_idx, label in enumerate(result.labels):
        membership = result.memberships[local_idx]
        if label < 0 or membership <= 0.1:
            continue
        global_idx = code_positions[local_idx]
        grouped.setdefault(label, []).append(global_idx)
```

Leave the rest of the function unchanged: it already indexes `chunks_buf[idx]` and `embeddings[positions]` by the (now global) positions stored in `grouped`.

- [x] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_vectorize_cmd.py tests/unit/test_clusters.py tests/integration/test_full_index.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add scripts/cbv/commands/vectorize.py tests/unit/test_vectorize_cmd.py
git commit -m "Cluster concepts over source/config chunks only"
```

---

## Task 11: Full-suite regression + end-to-end recall verification

**Files:**
- No production code. Verification only.

- [x] **Step 1: Run the full unit + integration suite**

Run: `pytest tests/unit tests/integration -q`
Expected: All pass (one pre-existing skip is acceptable). Fix any regression before continuing — do not proceed with a red suite.

- [x] **Step 2: Re-vectorize a real repo against the new schema**

The schema bumped to `1.1`, so existing on-disk indexes are now legacy. Re-index this repo itself:

Run (Windows): `& scripts\run.ps1 vectorize "https://github.com/BigMoonTech/codebase-vectorizer"`
Expected: JSON summary on the last stdout line with nonzero `files_indexed`/`chunks_indexed`.

- [x] **Step 3: Confirm the recall bug is fixed**

Run: `& scripts\run.ps1 query "codebase-vectorizer" "how does the codebase call UMAP?" --lane full`
Expected: the JSON `results` array contains an entry whose `file_relative` is `scripts/cbv/clusters.py` (the chunk holding `umap.UMAP(...)`) — it was absent before this plan. The top results should be implementation code, not `SKILL.md`/`README.md`/`docs/plans/*`.

- [x] **Step 4: Confirm no ranking regression on the symbol query**

Run: `& scripts\run.ps1 query "codebase-vectorizer" "what does the cluster_embeddings function do" --lane full`
Expected: `scripts/cbv/clusters.py :: cluster_embeddings` remains at or near rank 1 (this query already worked after the reranker fix; it must not regress).

- [x] **Step 5: Commit the plan-completion marker**

```bash
git add docs/plans/2026-05-17-v1-candidate-pool-composition.md
git commit -m "Record v1 candidate-pool-composition plan"
```

---

## Notes for the executing engineer

- **TDD is mandatory.** Every production change above is preceded by a test that you must watch fail first. If a test passes before you write the code, the test is wrong.
- **Categories are heuristic.** `classify.py` is intentionally simple and path-based. Misclassifications are expected at the margins; the default (`source`) is the recall-safe direction. Refining the ruleset is fine, but keep `tests/unit/test_classify.py` green and add a case for any path you re-classify.
- **`meta`/`vendor` are excluded from the full lane entirely in v1.** This means questions like "what's in CLAUDE.md" are not served by the full lane. That is an accepted v1 limitation — a queryable context lane for those categories is future work.
- **Do not** attempt the deferred v2 items (dense-embedding instructions, runtime-relevance scoring, generated-file detection, framework-aware config handling). They are out of scope for this plan.

---

## Post-final-review fixes

After all 11 tasks landed, a final whole-implementation review of the branch surfaced follow-ups. All are resolved:

- [x] **#1 — stray worktree state.** An uncommitted revert of Task 10 was sitting in the worktree (a reviewer's unrestored `git checkout`). Discarded with `git restore` — not a code defect; the committed tip always had Task 10.
- [x] **#2 — manifest schema version.** `_build_manifest` hard-coded `schema_version "1.0"` while the DB writes `1.1`. Fixed to use `db.SCHEMA_VERSION` (commit `78dcd76`), with a test.
- [x] **#3 — symbol/graph lanes leaked meta/vendor.** `_symbol_exact` and `_graph_expand` were not category-filtered, so meta/vendor code could enter the full-lane pool via an exact symbol match. Added `RETRIEVABLE_CATEGORIES` and filtered both lanes; `_symbol_exact` takes an optional `categories` arg so only the full lane filters (the fast lane is unchanged). Commits `2db4c99` + `d176c20`. This makes the v1 "meta/vendor excluded from the full lane entirely" note above genuinely true across all four lanes.

Deferred as Minor (not fixed): #4 — the `_rrf` debug `sources` list can show `bm25`/`dense` twice; #5 — runnable code under `examples/` is classified `docs`. Both are cosmetic or documented v2-refinable heuristics.

Final state: whole suite green at branch tip `d176c20` — 496 passed, 1 skipped.
