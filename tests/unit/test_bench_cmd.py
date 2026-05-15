from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import paths  # noqa: E402
from cbv.commands import bench_cmd, vectorize as vec_cmd  # noqa: E402


@pytest.fixture
def tmp_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _index_repo(source_repo: Path) -> str:
    rc = vec_cmd.run(
        argparse.Namespace(
            source=str(source_repo),
            output_dir=None,
            max_file_mb=1.5,
        )
    )
    assert rc == 0
    return source_repo.name


def test_bench_command_prints_zero_summary_when_no_queries(tmp_home, capsys):
    source_repo = tmp_home / "demo"
    source_repo.mkdir()
    (source_repo / "main.py").write_text("def main():\n    return 1\n")
    repo = _index_repo(source_repo)
    capsys.readouterr()

    rc = bench_cmd.run(argparse.Namespace(repo=repo))

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "repo": "demo",
        "mrr_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "recall_at_5": 0.0,
        "recall_at_10": 0.0,
        "queries": 0,
    }
    assert (paths.repo_dir("demo") / "bench" / "results.json").exists()


def test_bench_command_reads_repo_local_queries(tmp_home, capsys, monkeypatch):
    source_repo = tmp_home / "demo"
    (source_repo / "bench").mkdir(parents=True)
    (source_repo / "main.py").write_text("def main():\n    return 1\n")
    (source_repo / "bench" / "queries.jsonl").write_text(
        json.dumps({"query": "main entry", "expected_files": ["main.py"]}) + "\n"
    )
    repo = _index_repo(source_repo)
    capsys.readouterr()
    monkeypatch.setattr(
        bench_cmd,
        "_query_files",
        lambda repo, question: (0, ["main.py", "bench/queries.jsonl"], None),
    )

    rc = bench_cmd.run(argparse.Namespace(repo=repo))

    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["queries"] == 1
    assert summary["mrr_at_10"] == 1.0
    assert summary["ndcg_at_10"] == 1.0
    assert summary["recall_at_5"] == 1.0
    assert summary["recall_at_10"] == 1.0


def test_bench_command_rejects_invalid_jsonl_rows(tmp_home, capsys):
    source_repo = tmp_home / "demo"
    (source_repo / "bench").mkdir(parents=True)
    (source_repo / "main.py").write_text("def main():\n    return 1\n")
    (source_repo / "bench" / "queries.jsonl").write_text(
        json.dumps({"query": "main entry", "expected_files": "main.py"}) + "\n"
    )
    repo = _index_repo(source_repo)
    capsys.readouterr()

    rc = bench_cmd.run(argparse.Namespace(repo=repo))

    assert rc == 2
    err = capsys.readouterr().err
    assert "invalid JSONL row" in err
    assert "expected_files must be a string list" in err


def test_query_files_collapses_duplicate_chunk_rows(monkeypatch):
    def fake_query_run(ns):
        print(
            json.dumps(
                {
                    "results": [
                        {"file_relative": "pkg/a.py"},
                        {"file_relative": "pkg/a.py"},
                        {"file_relative": "pkg/b.py"},
                    ]
                }
            )
        )
        return 0

    monkeypatch.setattr(bench_cmd.query_cmd, "run", fake_query_run)

    rc, files, error = bench_cmd._query_files("demo", "find auth")

    assert rc == 0
    assert error is None
    assert files == ["pkg/a.py", "pkg/b.py"]


def test_query_paths_include_stable_project_bench_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_bench = Path(bench_cmd.__file__).resolve().parents[3] / "bench"

    paths_to_check = bench_cmd._query_paths(tmp_path / "repo")

    assert project_bench / "coir_subset.jsonl" in paths_to_check
    assert project_bench / "repoeval_mini.jsonl" in paths_to_check
