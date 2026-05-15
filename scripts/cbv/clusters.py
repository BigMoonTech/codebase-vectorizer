from __future__ import annotations

import json
import os
import subprocess
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


class ClusterBackendError(RuntimeError):
    """Raised when UMAP/HDBSCAN fails unexpectedly."""


class LocalLLMClusterLabeler(ClusterLabeler):
    def label(self, samples: list[str]) -> tuple[str, str]:
        command = os.environ.get("CBV_CLUSTER_LABEL_COMMAND")
        if not command:
            raise RuntimeError("local LLM labeler is not configured")
        timeout = float(os.environ.get("CBV_CLUSTER_LABEL_TIMEOUT_SECONDS", "30"))
        payload = json.dumps({"samples": samples[:5]})
        result = subprocess.run(
            command,
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout,
            shell=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"cluster label command failed: {detail}")
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"cluster label command returned invalid JSON: {e}") from e
        label = parsed.get("label") if isinstance(parsed, dict) else None
        summary = parsed.get("summary") if isinstance(parsed, dict) else None
        if not isinstance(label, str) or not label.strip():
            raise RuntimeError("cluster label command returned no label")
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError("cluster label command returned no summary")
        return label.strip(), summary.strip()


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
    except Exception as e:
        raise ClusterBackendError(str(e)) from e


def label_cluster(samples: list[str], labeler: ClusterLabeler) -> tuple[str, str, str | None]:
    try:
        label, summary = labeler.label(samples[:5])
        return label, summary, None
    except Exception as e:
        label, summary = deterministic_label_for_texts(samples)
        return label, summary, f"LLM cluster labeling failed; used deterministic label: {e}"
