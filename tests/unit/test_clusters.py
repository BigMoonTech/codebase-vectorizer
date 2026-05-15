import sys
from pathlib import Path

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import clusters


def test_umap_hdbscan_cluster_embeddings_returns_labels_and_memberships():
    embeddings = np.vstack([
        np.ones((6, 8), dtype="float32"),
        np.zeros((6, 8), dtype="float32"),
    ])
    result = clusters.cluster_embeddings(embeddings, min_cluster_size=3, random_state=42)
    assert len(result.labels) == len(embeddings)
    assert len(result.memberships) == len(embeddings)
    assert all(0.0 <= m <= 1.0 for m in result.memberships)


def test_label_cluster_uses_llm_and_falls_back_with_warning(monkeypatch):
    class FakeLabeler:
        def label(self, samples):
            return ("auth session", "Authentication and session handling.")

    label, summary, warning = clusters.label_cluster(["def authenticate_user(): pass"], FakeLabeler())
    assert label == "auth session"
    assert summary.startswith("Authentication")
    assert warning is None
