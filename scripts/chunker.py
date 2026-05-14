"""Language-aware code chunker.

Splits source files into logical units (functions, classes, sections) using
lightweight regex heuristics. Falls back to line-window chunking for unknown
file types. The goal is to produce chunks that are big enough to be semantically
meaningful but small enough to embed cleanly and read cheaply.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    file_path: str          # repo-relative path
    language: str
    kind: str               # "function", "class", "section", "window", etc.
    name: str               # extracted symbol or heading; "" if none
    start_line: int         # 1-indexed, inclusive
    end_line: int           # 1-indexed, inclusive
    content: str

    def to_row(self) -> dict:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "kind": self.kind,
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "content": self.content,
        }


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_EXT_TO_LANG = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".scala": "scala",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objcpp",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".lua": "lua",
    ".sql": "sql",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "css",
    ".sass": "css",
    ".less": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".vue": "vue",
    ".svelte": "svelte",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".clj": "clojure",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".zig": "zig",
    ".r": "r",
    ".jl": "julia",
}


def detect_language(file_path: str) -> str:
    """Return language id for a file, or 'text' if unknown."""
    base = os.path.basename(file_path).lower()
    if base in ("dockerfile", "makefile", "rakefile"):
        return base
    _, ext = os.path.splitext(base)
    return _EXT_TO_LANG.get(ext, "text")


# ---------------------------------------------------------------------------
# Language-specific regex patterns
# ---------------------------------------------------------------------------

_PATTERNS = {
    "python": re.compile(
        r"^(?P<indent>\s*)(?P<kind>async\s+def|def|class)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "javascript": re.compile(
        r"^\s*(?:export\s+(?:default\s+)?)?"
        r"(?:async\s+)?"
        r"(?P<kind>function\*?|class|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"
        r"(?=\s*[=({<])"
    ),
    "typescript": re.compile(
        r"^\s*(?:export\s+(?:default\s+)?)?"
        r"(?:async\s+)?"
        r"(?P<kind>function\*?|class|interface|type|enum|const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)"
    ),
    "go": re.compile(
        r"^(?P<kind>func|type)\s+(?:\([^)]*\)\s+)?(?P<name>[A-Za-z_][\w]*)"
    ),
    "rust": re.compile(
        r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?P<kind>fn|struct|enum|trait|impl|mod)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "java": re.compile(
        r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*"
        r"(?P<kind>class|interface|enum|record)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "csharp": re.compile(
        r"^\s*(?:public|private|protected|internal|static|abstract|sealed|partial|\s)*"
        r"(?P<kind>class|interface|struct|enum|record)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "ruby": re.compile(
        r"^\s*(?P<kind>def|class|module)\s+(?P<name>[A-Za-z_][\w:]*)"
    ),
    "php": re.compile(
        r"^\s*(?:public|private|protected|static|abstract|final|\s)*"
        r"(?P<kind>function|class|interface|trait)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "cpp": re.compile(
        r"^\s*(?:template\s*<[^>]*>\s*)?"
        r"(?P<kind>class|struct|namespace)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "swift": re.compile(
        r"^\s*(?:public|private|internal|fileprivate|open|\s)*"
        r"(?P<kind>func|class|struct|enum|protocol|extension)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "kotlin": re.compile(
        r"^\s*(?:public|private|protected|internal|open|abstract|\s)*"
        r"(?P<kind>fun|class|object|interface)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "scala": re.compile(
        r"^\s*(?:def|class|object|trait|case\s+class)\s+(?P<name>[A-Za-z_][\w]*)"
    ),
    "elixir": re.compile(
        r"^\s*(?P<kind>defmodule|def|defp|defmacro)\s+(?P<name>[A-Za-z_][\w.]*)"
    ),
    "haskell": re.compile(
        r"^(?P<name>[a-z][\w']*)\s*::"
    ),
}

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(?P<name>.+)$")


MAX_CHUNK_LINES = 200
WINDOW_LINES = 150
WINDOW_OVERLAP = 25
MIN_CHUNK_LINES = 3


# ---------------------------------------------------------------------------
# Core chunker
# ---------------------------------------------------------------------------

def chunk_file(file_path: str, content: str, language: Optional[str] = None) -> List[Chunk]:
    if language is None:
        language = detect_language(file_path)

    lines = content.splitlines()
    if not lines:
        return []

    if language == "markdown":
        chunks = _chunk_by_headings(file_path, language, lines)
    elif language in _PATTERNS:
        chunks = _chunk_by_pattern(file_path, language, lines, _PATTERNS[language])
    else:
        chunks = _chunk_by_window(file_path, language, lines)

    final: List[Chunk] = []
    for c in chunks:
        if (c.end_line - c.start_line + 1) > MAX_CHUNK_LINES:
            final.extend(_split_oversized(c))
        else:
            final.append(c)

    return final


def _chunk_by_pattern(file_path: str, language: str, lines: List[str], pattern: re.Pattern) -> List[Chunk]:
    boundaries: List[tuple[int, str, str]] = []
    for i, line in enumerate(lines, start=1):
        m = pattern.match(line)
        if m:
            kind = (m.groupdict().get("kind") or "definition").strip().split()[-1]
            name = m.groupdict().get("name", "")
            boundaries.append((i, kind, name))

    if not boundaries:
        return _chunk_by_window(file_path, language, lines)

    chunks: List[Chunk] = []
    first_boundary = boundaries[0][0]
    if first_boundary > 1:
        preamble_text = "\n".join(lines[: first_boundary - 1])
        if preamble_text.strip():
            chunks.append(Chunk(
                file_path=file_path,
                language=language,
                kind="preamble",
                name="",
                start_line=1,
                end_line=first_boundary - 1,
                content=preamble_text,
            ))

    for idx, (start, kind, name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else len(lines)
        if end < start:
            end = start
        text = "\n".join(lines[start - 1: end])
        chunks.append(Chunk(
            file_path=file_path,
            language=language,
            kind=kind,
            name=name,
            start_line=start,
            end_line=end,
            content=text,
        ))

    return _merge_tiny(chunks)


def _chunk_by_headings(file_path: str, language: str, lines: List[str]) -> List[Chunk]:
    boundaries: List[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        m = _MARKDOWN_HEADING.match(line)
        if m:
            boundaries.append((i, m.group("name").strip()))

    if not boundaries:
        return _chunk_by_window(file_path, language, lines)

    chunks: List[Chunk] = []
    first = boundaries[0][0]
    if first > 1:
        pre = "\n".join(lines[: first - 1])
        if pre.strip():
            chunks.append(Chunk(file_path, language, "preamble", "", 1, first - 1, pre))

    for idx, (start, name) in enumerate(boundaries):
        end = boundaries[idx + 1][0] - 1 if idx + 1 < len(boundaries) else len(lines)
        if end < start:
            end = start
        text = "\n".join(lines[start - 1: end])
        chunks.append(Chunk(file_path, language, "section", name, start, end, text))

    return _merge_tiny(chunks)


def _chunk_by_window(file_path: str, language: str, lines: List[str]) -> List[Chunk]:
    n = len(lines)
    chunks: List[Chunk] = []
    if n <= WINDOW_LINES:
        text = "\n".join(lines)
        if text.strip():
            chunks.append(Chunk(file_path, language, "window", "", 1, n, text))
        return chunks

    start = 1
    step = WINDOW_LINES - WINDOW_OVERLAP
    while start <= n:
        end = min(start + WINDOW_LINES - 1, n)
        text = "\n".join(lines[start - 1: end])
        chunks.append(Chunk(file_path, language, "window", "", start, end, text))
        if end >= n:
            break
        start += step
    return chunks


def _split_oversized(chunk: Chunk) -> List[Chunk]:
    lines = chunk.content.splitlines()
    n = len(lines)
    out: List[Chunk] = []
    start = 0
    step = WINDOW_LINES - WINDOW_OVERLAP
    while start < n:
        end = min(start + WINDOW_LINES, n)
        text = "\n".join(lines[start: end])
        out.append(Chunk(
            file_path=chunk.file_path,
            language=chunk.language,
            kind=chunk.kind,
            name=f"{chunk.name} (part {len(out)+1})" if chunk.name else f"part {len(out)+1}",
            start_line=chunk.start_line + start,
            end_line=chunk.start_line + end - 1,
            content=text,
        ))
        if end >= n:
            break
        start += step
    return out


def _merge_tiny(chunks: List[Chunk]) -> List[Chunk]:
    if len(chunks) <= 1:
        return chunks
    merged: List[Chunk] = [chunks[0]]
    for c in chunks[1:]:
        prev = merged[-1]
        prev_len = prev.end_line - prev.start_line + 1
        cur_len = c.end_line - c.start_line + 1
        if cur_len < MIN_CHUNK_LINES and prev_len + cur_len <= MAX_CHUNK_LINES:
            merged[-1] = Chunk(
                file_path=prev.file_path,
                language=prev.language,
                kind=prev.kind,
                name=prev.name,
                start_line=prev.start_line,
                end_line=c.end_line,
                content=prev.content + "\n" + c.content,
            )
        else:
            merged.append(c)
    return merged
