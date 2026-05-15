from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

from cbv import bench, db, paths
from cbv.commands import query as query_cmd


METRIC_KEYS = ("mrr_at_10", "ndcg_at_10", "recall_at_5", "recall_at_10")


def run(ns: argparse.Namespace) -> int:
    rc, summary, error = run_bench(ns.repo, emit=False)
    if error is not None:
        print(error, file=sys.stderr)
        return rc
    print(json.dumps(summary), flush=True)
    return rc


def run_bench(repo: str, *, emit: bool = False) -> tuple[int, dict[str, Any], str | None]:
    repo_dir = paths.find_repo(repo)
    if repo_dir is None:
        return (
            2,
            _zero_summary(repo),
            f"No index found for repo {repo!r}.",
        )

    conn = db.open_db(repo_dir / "index.sqlite")
    try:
        try:
            db.assert_schema_v1(conn)
        except db.LegacySchemaError as e:
            return 2, _zero_summary(repo), str(e)
    finally:
        conn.close()

    try:
        rows = _read_queries(repo_dir)
    except ValueError as e:
        return 2, _zero_summary(repo), str(e)

    if not rows:
        summary = _zero_summary(repo)
        _write_results(repo_dir, summary, [])
        if emit:
            print(json.dumps(summary), flush=True)
        return 0, summary, None

    per_query = []
    totals = {key: 0.0 for key in METRIC_KEYS}
    for row in rows:
        rc, actual, error = _query_files(repo, row["query"])
        if rc != 0:
            return 2, _zero_summary(repo), error or f"bench query failed for {row['query']!r}"
        metrics = bench.metrics_for_query(set(row["expected_files"]), actual)
        for key in METRIC_KEYS:
            totals[key] += metrics[key]
        per_query.append(
            {
                "query": row["query"],
                "expected_files": row["expected_files"],
                "actual_files": actual,
                "metrics": metrics,
            }
        )

    count = len(rows)
    summary = {"repo": repo}
    summary.update({key: totals[key] / count for key in METRIC_KEYS})
    summary["queries"] = count
    _write_results(repo_dir, summary, per_query)
    if emit:
        print(json.dumps(summary), flush=True)
    return 0, summary, None


def _zero_summary(repo: str) -> dict[str, Any]:
    return {
        "repo": repo,
        "mrr_at_10": 0.0,
        "ndcg_at_10": 0.0,
        "recall_at_5": 0.0,
        "recall_at_10": 0.0,
        "queries": 0,
    }


def _read_queries(repo_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _query_paths(repo_dir):
        if not path.exists():
            continue
        rows.extend(_read_jsonl(path))
    return rows


def _query_paths(repo_dir: Path) -> list[Path]:
    workspace_bench = Path.cwd() / "bench"
    return [
        workspace_bench / "coir_subset.jsonl",
        workspace_bench / "repoeval_mini.jsonl",
        repo_dir / "source" / "bench" / "queries.jsonl",
        repo_dir / "bench" / "queries.jsonl",
    ]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSONL row in {path}:{line_no}: {e.msg}") from e
        if not isinstance(row, dict):
            raise ValueError(f"invalid JSONL row in {path}:{line_no}: row must be an object")
        query = row.get("query")
        expected_files = row.get("expected_files")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"invalid JSONL row in {path}:{line_no}: query must be a non-empty string")
        if (
            not isinstance(expected_files, list)
            or any(not isinstance(item, str) for item in expected_files)
        ):
            raise ValueError(f"invalid JSONL row in {path}:{line_no}: expected_files must be a string list")
        rows.append(
            {
                "query": query,
                "expected_files": expected_files,
            }
        )
    return rows


def _query_files(repo: str, question: str) -> tuple[int, list[str], str | None]:
    out = io.StringIO()
    err = io.StringIO()
    ns = argparse.Namespace(repo=repo, question=question, top_k=10, lane="full")
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = query_cmd.run(ns)
    if rc != 0:
        return rc, [], err.getvalue().strip()
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    if not lines:
        return 2, [], f"query produced no JSON output for {question!r}"
    try:
        blob = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        return 2, [], f"query produced invalid JSON for {question!r}: {e.msg}"
    results = blob.get("results")
    if not isinstance(results, list):
        return 2, [], f"query output missing results for {question!r}"
    actual = [
        row["file_relative"]
        for row in results
        if isinstance(row, dict) and isinstance(row.get("file_relative"), str)
    ]
    return 0, actual, None


def _write_results(repo_dir: Path, summary: dict[str, Any], queries: list[dict[str, Any]]) -> None:
    out_dir = repo_dir / "bench"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "queries": queries}, indent=2),
        encoding="utf-8",
    )
