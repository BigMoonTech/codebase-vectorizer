"""`cbv apply-llm-artifacts <repo> <result.json>` — persist agent-generated
cluster labels and ARCHITECTURE.md.

Path B of the layered LLM-wiring fix. The vectorize-repo skill generates the
artifacts in-session (after `cbv llm-payload`) and calls this to write them:

  result.json shape:
    {
      "clusters": [{"id": <int>, "label": "...", "summary": "..."}, ...],
      "architecture_markdown": "<full markdown document>"
    }

Both keys are optional; whichever is present is applied.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cbv import db, paths


def run(ns: argparse.Namespace) -> int:
    repo_dir = paths.find_repo(ns.repo)
    if repo_dir is None:
        print(f"No index found for repo {ns.repo!r}.", file=sys.stderr)
        return 2

    result_path = Path(ns.result_path)
    if not result_path.is_file():
        print(f"Result file not found: {result_path}", file=sys.stderr)
        return 2
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"Result file is not valid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(result, dict):
        print("Result file must contain a JSON object.", file=sys.stderr)
        return 2

    conn = db.open_db(repo_dir / "index.sqlite")
    clusters_updated = 0
    try:
        try:
            db.assert_schema_v1(conn)
        except db.LegacySchemaError as e:
            print(str(e), file=sys.stderr)
            return 2
        clusters_updated = _apply_cluster_labels(conn, result.get("clusters"))
    finally:
        conn.close()

    architecture_written = _apply_architecture(
        repo_dir / "ARCHITECTURE.md", result.get("architecture_markdown")
    )

    print(
        json.dumps(
            {
                "repo": ns.repo,
                "clusters_updated": clusters_updated,
                "architecture_written": architecture_written,
            }
        ),
        flush=True,
    )
    return 0


def _apply_cluster_labels(conn, cluster_results) -> int:
    if not isinstance(cluster_results, list):
        return 0
    updated = 0
    with conn:
        for item in cluster_results:
            if not isinstance(item, dict):
                continue
            cluster_id = item.get("id")
            label = item.get("label")
            summary = item.get("summary")
            if not isinstance(label, str) or not label.strip():
                continue
            if not isinstance(summary, str) or not summary.strip():
                continue
            try:
                cluster_id = int(cluster_id)
            except (TypeError, ValueError):
                continue
            cur = conn.execute(
                "UPDATE clusters SET label = ?, summary = ? WHERE id = ?",
                (label.strip(), summary.strip(), cluster_id),
            )
            updated += cur.rowcount
    return updated


def _apply_architecture(arch_path: Path, markdown) -> bool:
    if not isinstance(markdown, str) or not markdown.strip():
        return False
    arch_path.write_text(markdown.strip() + "\n", encoding="utf-8")
    return True
