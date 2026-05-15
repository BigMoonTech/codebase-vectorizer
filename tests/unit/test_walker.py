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
