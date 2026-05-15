from __future__ import annotations

import hashlib
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import cli, db  # noqa: E402
from cbv.incremental import file_sha, merkle_root, plan_delta, write_merkle  # noqa: E402


def test_file_sha_streams_sha256(tmp_path):
    path = tmp_path / "sample.txt"
    path.write_bytes(b"abc" + (b"x" * (1024 * 1024 + 7)))

    assert file_sha(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_merkle_root_is_sorted_and_deterministic():
    left = merkle_root({"b.py": "b" * 64, "a.py": "a" * 64})
    right = merkle_root({"a.py": "a" * 64, "b.py": "b" * 64})

    assert left == right
    assert left != merkle_root({"a.py": "a" * 64, "b.py": "c" * 64})
    assert len(left) == 64


def test_plan_delta_classifies_added_modified_removed_and_unchanged(tmp_path):
    conn = db.open_db(tmp_path / "index.sqlite")
    db.init_schema(conn)
    write_merkle(
        conn,
        {
            "modified.py": ("old", 3),
            "removed.py": ("gone", 4),
            "same.py": ("same", 5),
        },
    )

    delta = plan_delta(
        conn,
        {
            "added.py": "new",
            "modified.py": "new",
            "same.py": "same",
        },
    )

    assert delta.added == {"added.py"}
    assert delta.modified == {"modified.py"}
    assert delta.removed == {"removed.py"}
    assert delta.unchanged == {"same.py"}


def test_write_merkle_replaces_rows_in_sorted_order(tmp_path):
    conn = db.open_db(tmp_path / "index.sqlite")
    db.init_schema(conn)
    write_merkle(conn, {"old.py": ("old", 1)})

    write_merkle(conn, {"b.py": ("b", 2), "a.py": ("a", 1)})

    rows = conn.execute(
        "SELECT file_path, blob_sha, size_bytes, last_indexed_at "
        "FROM merkle_files ORDER BY file_path"
    ).fetchall()
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("a.py", "a", 1),
        ("b.py", "b", 2),
    ]
    assert all(isinstance(row[3], int) and row[3] > 0 for row in rows)


def test_cli_parses_vectorize_update_flag():
    parser = cli.build_parser()
    ns = parser.parse_args(["vectorize", "https://github.com/x/y", "--update"])

    assert ns.verb == "vectorize"
    assert ns.source == "https://github.com/x/y"
    assert ns.update is True
