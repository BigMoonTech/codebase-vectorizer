from __future__ import annotations

import os

# A genuine sequence-classification cross-encoder, which sentence-transformers'
# CrossEncoder is built for. NOT mxbai-rerank-v2: v2 is a generative Qwen2 model
# that saturates to ~1.0 through CrossEncoder and cannot rank (see
# tests/integration/test_reranker_model.py).
DEFAULT_RERANKER = "mixedbread-ai/mxbai-rerank-base-v1"


class Reranker:
    model_id = DEFAULT_RERANKER

    def score(self, query: str, passages: list[str]) -> list[float]:
        raise NotImplementedError


class StubReranker(Reranker):
    model_id = "stub://lexical-overlap-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = {_normalize_token(p) for p in query.split()}
        return [
            float(
                len(
                    q
                    & {_normalize_token(p) for p in passage.split()}
                )
            )
            for passage in passages
        ]


class SentenceTransformerReranker(Reranker):
    def __init__(self, model_id: str = DEFAULT_RERANKER) -> None:
        from sentence_transformers import CrossEncoder

        self.model_id = model_id
        self._model = CrossEncoder(model_id)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(x) for x in self._model.predict([(query, p[:512]) for p in passages])]


def make_reranker() -> Reranker:
    if os.environ.get("CBV_STUB_RERANKER") == "1" or os.environ.get("CBV_STUB_EMBEDDER") == "1":
        return StubReranker()
    return SentenceTransformerReranker()


def _normalize_token(token: str) -> str:
    return token.lower().strip(".,:;()[]{}")
