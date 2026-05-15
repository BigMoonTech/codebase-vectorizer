from __future__ import annotations

import math


def recall_at_k(expected: set[str], actual: list[str], k: int) -> float:
    if not expected:
        return 1.0
    hits = expected & set(actual[:k])
    return len(hits) / len(expected)


def mrr_at_k(expected: set[str], actual: list[str], k: int) -> float:
    if not expected:
        return 0.0
    for rank, file_path in enumerate(actual[:k], start=1):
        if file_path in expected:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(expected: set[str], actual: list[str], k: int) -> float:
    if not expected:
        return 1.0
    seen: set[str] = set()
    dcg = 0.0
    for rank, file_path in enumerate(actual[:k], start=1):
        if file_path in expected and file_path not in seen:
            dcg += 1.0 / math.log2(rank + 1)
            seen.add(file_path)
    ideal_hits = min(len(expected), k)
    if ideal_hits == 0:
        return 1.0
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def metrics_for_query(expected: set[str], actual: list[str]) -> dict[str, float]:
    return {
        "mrr_at_10": mrr_at_k(expected, actual, 10),
        "ndcg_at_10": ndcg_at_k(expected, actual, 10),
        "recall_at_5": recall_at_k(expected, actual, 5),
        "recall_at_10": recall_at_k(expected, actual, 10),
    }
