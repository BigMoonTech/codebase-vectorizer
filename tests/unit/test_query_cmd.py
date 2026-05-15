"""Tests for cbv.commands.query — BM25 + dense + RRF, plus legacy detector."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import paths  # noqa: E402
from cbv.commands import query as query_cmd, vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def indexed_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "auth.py").write_text(
        "def authenticate_user(username, password):\n"
        "    return check_credentials(username, password)\n"
    )
    (src / "router.py").write_text(
        "def route_request(req):\n"
        "    if req.path.startswith('/api'):\n"
        "        return api_handler(req)\n"
        "    return static_handler(req)\n"
    )
    (src / "db.py").write_text(
        "def query_user(uid):\n"
        "    return fetch('SELECT * FROM users WHERE id = ?', uid)\n"
    )
    ns = argparse.Namespace(source=str(src), output_dir=None, max_file_mb=1.5)
    rc = vec_cmd.run(ns)
    assert rc == 0
    return "upstream"


def test_query_returns_lane_shape_without_explicit_lane(indexed_repo, capsys):
    ns = argparse.Namespace(
        repo=indexed_repo,
        question="how does login authenticate users",
        top_k=3,
    )
    rc = query_cmd.run(ns)
    assert rc == 0
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["repo"] == indexed_repo
    assert blob["query"] == "how does login authenticate users"
    assert blob["pipeline_used"] == "full"
    assert "results" in blob and isinstance(blob["results"], list)
    assert "refined_queries" in blob
    assert isinstance(blob["expansion_size"], int)


def test_query_results_have_required_fields(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="authenticate user", top_k=3)
    query_cmd.run(ns)
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert blob["results"], "expected at least one result"
    r = blob["results"][0]
    for k in ("rank", "file_absolute", "file_relative", "start_line",
              "end_line", "kind", "score", "preview", "why_this_was_returned"):
        assert k in r, f"missing key {k!r}"


def test_query_top_k_caps_result_count(indexed_repo, capsys):
    ns = argparse.Namespace(repo=indexed_repo, question="route request handler", top_k=1)
    query_cmd.run(ns)
    out = capsys.readouterr().out
    blob = json.loads([l for l in out.strip().splitlines() if l.strip()][-1])
    assert len(blob["results"]) <= 1


def test_query_missing_repo_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "empty_home"))
    ns = argparse.Namespace(repo="nonexistent", question="anything", top_k=3)
    rc = query_cmd.run(ns)
    assert rc != 0
    err = capsys.readouterr().err
    assert "No index found" in err
    assert "nonexistent" in err


def test_query_legacy_schema_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    # Create a fake v0.3.0-shaped index: chunks table, no meta.
    legacy_dir = tmp_path / "home" / "repos" / "oldrepo"
    legacy_dir.mkdir(parents=True)
    db_path = legacy_dir / "index.sqlite"
    raw = sqlite3.connect(db_path)
    raw.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
    raw.commit()
    raw.close()

    ns = argparse.Namespace(repo="oldrepo", question="x", top_k=3)
    rc = query_cmd.run(ns)
    assert rc != 0
    err = capsys.readouterr().err
    assert "older codebase-vectorizer index" in err
