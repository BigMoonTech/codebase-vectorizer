"""Thin wrapper around fastembed for local CPU embeddings.

Uses BAAI/bge-small-en-v1.5 by default (384-dim, ~130MB download on first use).
After the first run the model is cached locally, so subsequent indexing runs
are fully offline.
"""

from __future__ import annotations

import sys
from typing import List, Sequence

from fastembed import TextEmbedding


DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        print(f"[embedder] loading model: {model_name} (first run downloads ~130MB)", file=sys.stderr, flush=True)
        self.model_name = model_name
        self.model = TextEmbedding(model_name=model_name)
        sample = next(iter(self.model.embed(["dimension probe"])))
        self.dim = len(sample)
        print(f"[embedder] ready (dim={self.dim})", file=sys.stderr, flush=True)

    def embed_batch(self, texts: Sequence[str], batch_size: int = 32) -> List[List[float]]:
        if not texts:
            return []
        out: List[List[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start: start + batch_size])
            for vec in self.model.embed(batch):
                out.append([float(x) for x in vec])
        return out

    def embed_one(self, text: str) -> List[float]:
        return self.embed_batch([text])[0]
