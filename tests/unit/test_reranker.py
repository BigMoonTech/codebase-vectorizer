from __future__ import annotations

import importlib
import importlib.util
import sys


def _reranker_module():
    spec = importlib.util.find_spec("cbv.reranker")
    assert spec is not None, "cbv.reranker module should exist"
    return importlib.import_module("cbv.reranker")


def test_stub_reranker_scores_lexical_overlap_case_insensitively():
    reranker = _reranker_module()
    rr = reranker.StubReranker()

    scores = rr.score(
        "Database, Fetch",
        [
            "fetch rows from the database",
            "render the page",
            "DATABASE,",
        ],
    )

    assert scores == [2.0, 0.0, 1.0]
    assert rr.model_id == "stub://lexical-overlap-reranker"


def test_make_reranker_uses_stub_when_requested(monkeypatch):
    reranker = _reranker_module()
    monkeypatch.setenv("CBV_STUB_RERANKER", "1")
    monkeypatch.delenv("CBV_STUB_EMBEDDER", raising=False)

    rr = reranker.make_reranker()

    assert isinstance(rr, reranker.StubReranker)


def test_make_reranker_uses_sentence_transformer_when_not_stubbed(monkeypatch):
    reranker = _reranker_module()
    created = []

    class FakeCrossEncoder:
        def __init__(self, model_id: str) -> None:
            created.append(model_id)

        def predict(self, pairs):
            return [0.25 for _ in pairs]

    monkeypatch.delenv("CBV_STUB_RERANKER", raising=False)
    monkeypatch.delenv("CBV_STUB_EMBEDDER", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        type("FakeSentenceTransformers", (), {"CrossEncoder": FakeCrossEncoder}),
    )

    rr = reranker.make_reranker()

    assert isinstance(rr, reranker.SentenceTransformerReranker)
    assert rr.model_id == reranker.DEFAULT_RERANKER
    assert created == [reranker.DEFAULT_RERANKER]
    assert rr.score("query", ["passage"]) == [0.25]


def test_sentence_transformer_reranker_scores_empty_passages_without_loading_model(monkeypatch):
    reranker = _reranker_module()

    class ExplodingCrossEncoder:
        def __init__(self, model_id: str) -> None:
            raise AssertionError("model should not be loaded for empty passages")

    monkeypatch.setitem(
        importlib.import_module("sys").modules,
        "sentence_transformers",
        type("FakeSentenceTransformers", (), {"CrossEncoder": ExplodingCrossEncoder}),
    )

    rr = reranker.SentenceTransformerReranker.__new__(
        reranker.SentenceTransformerReranker
    )
    rr.model_id = reranker.DEFAULT_RERANKER

    assert rr.score("anything", []) == []
