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
    return pathspec.PathSpec.from_lines("gitignore", gi.read_text(encoding="utf-8", errors="replace").splitlines())


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
