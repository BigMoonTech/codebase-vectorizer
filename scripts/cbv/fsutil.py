"""Filesystem helpers.

`force_rmtree` is a `shutil.rmtree` that survives read-only files.

Git stores pack files (`*.idx`, `*.pack`) read-only. On Windows,
`os.unlink` refuses to delete a read-only file, so a plain
`shutil.rmtree` of a tree that contains a `.git` directory raises
`PermissionError`. This bites the indexer twice: once when it tries to
strip `.git` after a clone, and again when it cleans up a leftover
`source/` directory on the next run.

The fix is the canonical recipe: on a deletion error, clear the
read-only bit and retry. On POSIX, file mode does not gate `unlink`
(deletion is governed by the parent directory), so the handler simply
never fires there — `force_rmtree` is a safe drop-in on every platform.
"""
from __future__ import annotations

import os
import shutil
import stat
import sys


def force_rmtree(path: "os.PathLike[str] | str", *, ignore_errors: bool = False) -> None:
    """Recursively delete `path`, tolerating read-only files (Windows `.git`).

    A missing `path` is silently ignored. When `ignore_errors` is True, an
    error that survives the read-only retry is swallowed; otherwise it
    propagates so the caller can react.
    """
    target = os.fspath(path)
    if not os.path.lexists(target):
        return

    def handle(func, failed_path, _exc):
        # Drop the read-only bit and retry the failed operation (unlink/rmdir).
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            func(failed_path)
        except OSError:
            if not ignore_errors:
                raise

    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=handle)
    else:  # pragma: no cover - Python <= 3.11 uses the legacy onerror signature
        shutil.rmtree(
            target,
            onerror=lambda func, p, exc_info: handle(func, p, exc_info[1]),
        )
