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


def test_label_cluster_falls_back_with_warning_after_labeler_failure():
    class FailingLabeler:
        def label(self, samples):
            raise RuntimeError("offline")

    label, summary, warning = clusters.label_cluster(["def authenticate_user(): pass"], FailingLabeler())

    assert label == "authenticate user pass"
    assert summary == "Code related to authenticate user pass."
    assert warning is not None
    assert "LLM cluster labeling failed" in warning
    assert "offline" in warning


def test_local_llm_cluster_labeler_uses_configured_command(monkeypatch, tmp_path):
    script = tmp_path / "labeler.py"
    script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "assert payload['samples'] == ['def authenticate_user(): pass']\n"
        "print(json.dumps({'label': 'auth session', 'summary': 'Authentication flows.'}))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CBV_CLUSTER_LABEL_COMMAND", f'"{sys.executable}" "{script}"')

    label, summary = clusters.LocalLLMClusterLabeler().label(["def authenticate_user(): pass"])

    assert label == "auth session"
    assert summary == "Authentication flows."
