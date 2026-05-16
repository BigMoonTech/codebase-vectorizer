from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest  # noqa: E402

from cbv import db, paths  # noqa: E402
from cbv.commands import apply_llm  # noqa: E402


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    return tmp_path


def _seed_repo(name: str):
    repo_dir = paths.repo_dir(name)
    conn = db.open_db(repo_dir / "index.sqlite")
    db.init_schema(conn)
    db.write_meta(conn, "schema_version", db.SCHEMA_VERSION)
    with conn:
        conn.execute(
            "INSERT INTO clusters (id, label, summary, centroid, size) "
            "VALUES (3, 'cluster 3', 'Code related to cluster 3.', X'00', 2)"
        )
    conn.close()
    return repo_dir


def _write_result(tmp_path, payload) -> Path:
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    return result_path


def test_apply_missing_repo_returns_code_2(tmp_home, tmp_path, capsys):
    result = _write_result(tmp_path, {"clusters": []})
    rc = apply_llm.run(argparse.Namespace(repo="missing", result_path=str(result)))
    assert rc == 2
    assert "No index found for repo 'missing'." in capsys.readouterr().err


def test_apply_missing_result_file_returns_code_2(tmp_home, capsys):
    _seed_repo("sample")
    rc = apply_llm.run(
        argparse.Namespace(repo="sample", result_path="C:/no/such/file.json")
    )
    assert rc == 2
    assert "Result file not found" in capsys.readouterr().err


def test_apply_writes_cluster_labels_and_architecture(tmp_home, tmp_path, capsys):
    repo_dir = _seed_repo("sample")
    result = _write_result(
        tmp_path,
        {
            "clusters": [
                {"id": 3, "label": "auth & session", "summary": "Login handling."}
            ],
            "architecture_markdown": "# sample Architecture\n\n## Overview\n\nReal prose.",
        },
    )

    rc = apply_llm.run(argparse.Namespace(repo="sample", result_path=str(result)))
    assert rc == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["clusters_updated"] == 1
    assert blob["architecture_written"] is True

    conn = db.open_db(repo_dir / "index.sqlite")
    label, summary = conn.execute(
        "SELECT label, summary FROM clusters WHERE id = 3"
    ).fetchone()
    conn.close()
    assert label == "auth & session"
    assert summary == "Login handling."

    arch_text = (repo_dir / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert arch_text.startswith("# sample Architecture")
    assert arch_text.endswith("\n")


def test_apply_skips_invalid_cluster_entries(tmp_home, tmp_path, capsys):
    _seed_repo("sample")
    result = _write_result(
        tmp_path,
        {
            "clusters": [
                {"id": 3, "label": "  ", "summary": "blank label is skipped"},
                {"id": 999, "label": "no such cluster", "summary": "no row to update"},
            ]
        },
    )
    rc = apply_llm.run(argparse.Namespace(repo="sample", result_path=str(result)))
    assert rc == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["clusters_updated"] == 0
    assert blob["architecture_written"] is False


def test_apply_rejects_non_json_result(tmp_home, tmp_path, capsys):
    _seed_repo("sample")
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    rc = apply_llm.run(argparse.Namespace(repo="sample", result_path=str(bad)))
    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err
