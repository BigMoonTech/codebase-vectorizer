"""`list` verb — print every indexed repo (human-readable)."""
from __future__ import annotations

import argparse

from cbv import db, paths


def run(_ns: argparse.Namespace) -> int:
    repos = paths.list_indexed_repos()
    if not repos:
        print("No indexed repos found.")
        print(f"  Searched: {paths.repos_dir()}")
        return 0
    for r in repos:
        version = "?"
        try:
            conn = db.open_db(r / "index.sqlite")
            v = db.read_meta(conn, "schema_version")
            conn.close()
            version = v or "legacy"
        except Exception:
            version = "unreadable"
        print(f"{r.name}\tschema={version}\t{r}")
    return 0
