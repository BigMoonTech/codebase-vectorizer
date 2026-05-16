"""Tests for cbv.fsutil — filesystem helpers.

The motivating bug: git stores pack files (*.idx, *.pack) read-only.
On Windows, os.unlink refuses to delete a read-only file, so a plain
shutil.rmtree over a tree containing a .git dir raises PermissionError.
force_rmtree must survive that. On POSIX, file mode does not gate
unlink, so these tests verify the same end state without the helper's
read-only handler necessarily firing.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import fsutil  # noqa: E402


def test_force_rmtree_removes_plain_tree(tmp_path):
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "f.txt").write_text("hi\n")
    fsutil.force_rmtree(d)
    assert not d.exists()


def test_force_rmtree_missing_path_is_noop(tmp_path):
    # Must not raise on a path that does not exist.
    fsutil.force_rmtree(tmp_path / "does-not-exist")
    fsutil.force_rmtree(tmp_path / "missing", ignore_errors=True)


def test_force_rmtree_removes_git_like_readonly_tree(tmp_path):
    """Reproduce the real failure: a leftover source/.git with read-only
    pack files. A plain shutil.rmtree raises PermissionError on Windows."""
    root = tmp_path / "source"
    pack = root / ".git" / "objects" / "pack"
    pack.mkdir(parents=True)
    idx = pack / "pack-deadbeefcafe.idx"
    idx.write_bytes(b"\x00" * 64)
    (root / "a.py").write_text("x = 1\n")

    # git marks pack files read-only; reproduce that bit exactly.
    os.chmod(idx, stat.S_IREAD)

    fsutil.force_rmtree(root)
    assert not root.exists()


def test_force_rmtree_removes_single_readonly_file(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    f = d / "readonly.bin"
    f.write_bytes(b"data")
    os.chmod(f, stat.S_IREAD)
    fsutil.force_rmtree(d)
    assert not d.exists()
