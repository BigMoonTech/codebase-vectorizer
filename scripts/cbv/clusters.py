from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ClusterResult:
    labels: list[int]
    memberships: list[float]
    reduced: np.ndarray


class ClusterLabeler:
    def label(self, samples: list[str]) -> tuple[str, str]:
        raise NotImplementedError


class LocalLLMClusterLabeler(ClusterLabeler):
    def label(self, samples: list[str]) -> tuple[str, str]:
        raise RuntimeError("local LLM labeler is not configured")


def deterministic_label_for_texts(texts: list[str]) -> tuple[str, str]:
    words = Counter()
    for text in texts:
        for word in text.replace("_", " ").split():
            clean = word.strip(".,:;()[]{}<>!?\"'").lower()
            if len(clean) >= 4:
                words[clean] += 1
    common = [w for w, _ in words.most_common(3)] or ["code"]
    label = " ".join(common)
    return label, f"Code related to {label}."


def cluster_embeddings(
    embeddings: np.ndarray,
    *,
    min_cluster_size: int = 10,
    min_samples: int = 5,
    random_state: int = 42,
) -> ClusterResult:
    if len(embeddings) < min_cluster_size:
        return ClusterResult(
            [-1 for _ in range(len(embeddings))],
            [0.0 for _ in range(len(embeddings))],
            embeddings,
        )
    try:
        import hdbscan
        import umap

        reduced = umap.UMAP(
            n_components=min(8, embeddings.shape[1]),
            n_neighbors=min(15, max(2, len(embeddings) - 1)),
            min_dist=0.0,
            n_jobs=1,
            random_state=random_state,
        ).fit_transform(embeddings.astype("float32"))
        model = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            prediction_data=True,
        )
        labels = model.fit_predict(reduced)
        memberships = getattr(model, "probabilities_", np.ones(len(labels), dtype="float32"))
        return ClusterResult([int(x) for x in labels], [float(x) for x in memberships], reduced)
    except Exception:
        return ClusterResult(
            [-1 for _ in range(len(embeddings))],
            [0.0 for _ in range(len(embeddings))],
            embeddings,
        )


def label_cluster(samples: list[str], labeler: ClusterLabeler) -> tuple[str, str, str | None]:
    try:
        label, summary = labeler.label(samples[:5])
        return label, summary, None
    except Exception as e:
        label, summary = deterministic_label_for_texts(samples)
        return label, summary, f"LLM cluster labeling failed; used deterministic label: {e}"
