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
    ".jsx": "javascript",
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
    """A single indexed chunk.

    start_byte / end_byte are UTF-8 BYTE offsets into the source file,
    NOT Unicode character indices. For non-ASCII content they will NOT
    match `content[start_byte:end_byte]` (which uses character indices).
    To recover the bytes from the source text use:
        source.encode("utf-8")[start_byte:end_byte]
    Tree-sitter chunking in Slice 2 keeps the same byte-offset semantics.

    token_count is a whitespace-split estimate, not a real BPE token count.
    """
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
    """Yield chunks using cAST when supported, text windows otherwise."""
    if not content:
        return

    try:
        from cbv import cast_chunker, parser
    except ImportError:
        pass
    else:
        language_meta = parser.language_for_name(language)
        if language_meta is not None:
            source = content.encode("utf-8")
            try:
                tree = parser.parse(source, language_meta)
            except Exception:
                tree = None
            if tree is not None:
                yield from cast_chunker.cast_chunks(
                    tree,
                    source,
                    language_name=language,
                    file_path=file_path,
                    budget_bytes=budget_bytes,
                )
                return

    yield from _text_window_chunks(
        content,
        language=language,
        file_path=file_path,
        budget_bytes=budget_bytes,
    )


def _text_window_chunks(
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
