from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path


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
    prior = {
        row[0]: row[1]
        for row in conn.execute("SELECT file_path, blob_sha FROM merkle_files")
    }
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
        "INSERT INTO merkle_files "
        "(file_path, blob_sha, size_bytes, last_indexed_at) "
        "VALUES (?, ?, ?, ?)",
        [(rel, sha, size, now) for rel, (sha, size) in sorted(files.items())],
    )
