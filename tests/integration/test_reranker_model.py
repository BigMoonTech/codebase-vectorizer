"""Integration test that exercises the real reranker model.

`tests/unit/test_reranker.py` mocks `CrossEncoder`, so it can only verify
wrapper plumbing -- it cannot catch a model that loads fine but fails to
rank. This test loads the actual configured reranker and checks it produces
a usable ranking signal.
"""
from __future__ import annotations

import importlib


# Every passage below is genuinely on-topic for the query -- all about
# reducing embedding dimensionality. A reranker that *ranks* must spread
# them out and pick a single best. A reranker that saturates -- collapsing
# every on-topic passage to one identical ceiling score -- cannot, and fails
# here. That saturation is exactly the mxbai-rerank-v2-through-CrossEncoder
# defect this test guards against.
_QUERY = "how does the code reduce embedding dimensionality"
_PASSAGES = [
    "reduced = umap.UMAP(n_components=8, min_dist=0.0).fit_transform(embeddings)",
    "import umap  # UMAP performs nonlinear dimensionality reduction",
    "UMAP then HDBSCAN turn high-dimensional vectors into labelled clusters",
    "the routine lowers an (N, 1536) embedding matrix down to (N, 8)",
]


def test_real_reranker_picks_a_single_top_passage():
    reranker = importlib.import_module("cbv.reranker")
    rr = reranker.make_reranker()

    scores = rr.score(_QUERY, _PASSAGES)

    assert len(scores) == len(_PASSAGES)
    top = max(scores)
    assert scores.count(top) == 1, (
        f"reranker saturated -- {scores.count(top)} passages tied at the top "
        f"score {top}, so it cannot rank them: {scores}"
    )
