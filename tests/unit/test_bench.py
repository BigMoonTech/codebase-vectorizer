from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import bench  # noqa: E402


def test_metrics_for_query_scores_first_relevant_rank():
    metrics = bench.metrics_for_query(
        {"pkg/router.py"},
        ["pkg/auth.py", "pkg/router.py", "pkg/db.py"],
    )

    assert metrics["mrr_at_10"] == 0.5
    assert metrics["recall_at_5"] == 1.0
    assert "ndcg_at_10" in metrics
    assert "recall_at_10" in metrics


def test_empty_expected_is_perfect_for_recall_and_ndcg():
    metrics = bench.metrics_for_query(set(), ["pkg/auth.py"])

    assert metrics["mrr_at_10"] == 0.0
    assert metrics["ndcg_at_10"] == 1.0
    assert metrics["recall_at_5"] == 1.0
    assert metrics["recall_at_10"] == 1.0
