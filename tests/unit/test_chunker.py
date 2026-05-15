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
    chunks = list(chunker.chunk_text("x=1\n", language="text",
                                      file_path="x.txt", budget_bytes=1500))
    assert all(c.kind == "window" for c in chunks)
    assert all(c.ast_path is None for c in chunks)
    assert all(c.name is None for c in chunks)


def test_language_detection_from_extension():
    assert chunker.detect_language(Path("foo.py")) == "python"
    assert chunker.detect_language(Path("foo.js")) == "javascript"
    assert chunker.detect_language(Path("foo.jsx")) == "javascript"
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


def test_byte_ranges_are_utf8_byte_offsets():
    """start_byte/end_byte are UTF-8 byte offsets, not character indices.
    For non-ASCII content the chunk's `content` reproduces what those bytes
    decode to via UTF-8; the character-indexed slice will NOT match."""
    content = "ééé\n" * 3  # each line: 6 bytes of "é"*3 + 1 byte newline = 7 bytes
    chunks = list(chunker.chunk_text(content, language="text",
                                      file_path="x.txt", budget_bytes=8))
    assert len(chunks) >= 2
    encoded = content.encode("utf-8")
    for c in chunks:
        # UTF-8 byte slice into the source recovers the chunk's content exactly.
        assert encoded[c.start_byte:c.end_byte].decode("utf-8") == c.content


def test_chunk_file_handles_non_utf8_bytes(tmp_path):
    """Files with bytes that don't decode as UTF-8 must not crash.
    Undecodable bytes become U+FFFD via errors='replace'."""
    p = tmp_path / "bad.txt"
    # 0xFF and 0xFE are invalid UTF-8 lead bytes
    p.write_bytes(b"hello\n\xff\xfe\nworld\n")
    chunks = list(chunker.chunk_file(p, budget_bytes=1500))
    assert len(chunks) == 1
    # Sentinel content from the surrounding valid bytes survives.
    assert "hello" in chunks[0].content
    assert "world" in chunks[0].content
    # content_hash must compute without raising.
    assert len(chunks[0].content_hash) == 64


def test_orchestrator_uses_ast_for_python():
    content = "def add(a, b):\n    return a + b\n"
    chunks = list(chunker.chunk_text(
        content, language="python", file_path="x.py", budget_bytes=1500,
    ))
    assert len(chunks) == 1
    assert chunks[0].kind == "function"
    assert chunks[0].name == "add"
    assert chunks[0].ast_path == "module/function[add]"


def test_orchestrator_uses_ast_for_javascript():
    content = "function add(a, b) {\n  return a + b;\n}\n"
    chunks = list(chunker.chunk_text(
        content, language="javascript", file_path="x.js", budget_bytes=1500,
    ))
    assert chunks
    assert all(c.kind != "window" for c in chunks)
    assert all(c.ast_path is not None for c in chunks)


def test_orchestrator_falls_back_to_text_window_for_unknown_language():
    content = "a\nb\nc\n"
    chunks = list(chunker.chunk_text(
        content, language="not-a-language", file_path="x.unknown", budget_bytes=4,
    ))
    assert "".join(c.content for c in chunks) == content
    assert all(c.kind == "window" for c in chunks)
    assert all(c.ast_path is None for c in chunks)
    assert all(c.name is None for c in chunks)


def test_orchestrator_falls_back_for_markdown():
    content = "# Title\n\nBody text.\n"
    chunks = list(chunker.chunk_text(
        content, language="markdown", file_path="README.md", budget_bytes=1500,
    ))
    assert len(chunks) == 1
    assert chunks[0].kind == "window"
    assert chunks[0].ast_path is None
    assert chunks[0].name is None


def test_orchestrator_falls_back_when_parser_returns_none(monkeypatch):
    from cbv import parser

    content = "def add(a, b):\n    return a + b\n"
    monkeypatch.setattr(parser, "parse", lambda source, language: None)
    chunks = list(chunker.chunk_text(
        content, language="python", file_path="x.py", budget_bytes=20,
    ))
    assert "".join(c.content for c in chunks) == content
    assert all(c.kind == "window" for c in chunks)
    assert all(c.ast_path is None for c in chunks)
    assert all(c.name is None for c in chunks)


def test_orchestrator_concat_invariant_python():
    content = (
        "import os\n"
        "\n"
        "def a():\n    return os.name\n"
        "\n"
        "def b():\n    return 2\n"
    )
    chunks = list(chunker.chunk_text(
        content, language="python", file_path="x.py", budget_bytes=24,
    ))
    assert "".join(c.content for c in chunks) == content
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(content.encode("utf-8"))
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.start_byte == prev.end_byte


def test_chunk_file_python(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    chunks = list(chunker.chunk_file(p, budget_bytes=1500))
    assert len(chunks) == 1
    assert chunks[0].file_path == str(p)
    assert chunks[0].language == "python"
    assert chunks[0].kind == "function"
    assert chunks[0].name == "add"
    assert chunks[0].ast_path == "module/function[add]"


def test_chunk_file_jsx_uses_javascript_ast(tmp_path):
    p = tmp_path / "x.jsx"
    p.write_text(
        "function App() {\n"
        "  return <main>Hello</main>;\n"
        "}\n",
        encoding="utf-8",
    )
    chunks = list(chunker.chunk_file(p, budget_bytes=1500))
    assert chunks
    assert chunks[0].language == "javascript"
    assert any(c.ast_path is not None for c in chunks)
    assert not all(c.kind == "window" for c in chunks)


def test_chunk_file_unknown_extension_falls_back(tmp_path):
    p = tmp_path / "x.unknown"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    chunks = list(chunker.chunk_file(p, budget_bytes=4))
    assert "".join(c.content for c in chunks) == "a\nb\nc\n"
    assert all(c.language == "text" for c in chunks)
    assert all(c.kind == "window" for c in chunks)
    assert all(c.ast_path is None for c in chunks)
    assert all(c.name is None for c in chunks)
