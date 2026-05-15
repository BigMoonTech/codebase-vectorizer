from __future__ import annotations

import os

DEFAULT_RERANKER = "mixedbread-ai/mxbai-rerank-large-v2"


class Reranker:
    model_id = DEFAULT_RERANKER

    def score(self, query: str, passages: list[str]) -> list[float]:
        raise NotImplementedError


class StubReranker(Reranker):
    model_id = "stub://lexical-overlap-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = {p.lower() for p in query.split()}
        return [
            float(
                len(
                    q
                    & {
                        p.lower().strip(".,:;()[]{}")
                        for p in passage.split()
                    }
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
