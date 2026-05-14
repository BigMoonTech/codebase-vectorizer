"""Embedder for codebase-vectorizer v1.0 (Slice 1).

Default model: `jinaai/jina-code-embeddings-1.5b` — 1.5B-param encoder,
1536-dim output. Runtime selection:

  - GPU path: transformers + torch.float16, batch 32
  - CPU path: llama-cpp-python + GGUF INT4, batch 8
  - Stub path: deterministic SHA-256 hash-derived embeddings (tests)

The factory `make_embedder()` reads CBV_STUB_EMBEDDER first (tests),
then auto-detects CUDA via torch. To force the CPU path on a CUDA box
set CBV_FORCE_CPU=1.

The GGUF repo and filename are env-configurable:
  CBV_GGUF_REPO   default 'jinaai/jina-code-embeddings-1.5b-GGUF'
  CBV_GGUF_FILE   default 'jina-code-embeddings-1.5b.Q4_K_M.gguf'

Slice 2 adds tree-sitter chunking; the embedder itself doesn't change.
Slice 5 adds the cross-encoder reranker (separate module).
"""
from __future__ import annotations

import abc
import hashlib
import os
from typing import List

import numpy as np

DEFAULT_DIM = 1536
DEFAULT_MODEL_ID = "jinaai/jina-code-embeddings-1.5b"


class Embedder(abc.ABC):
    """Embedder interface. All implementations return L2-normalized float32."""

    model_id: str = DEFAULT_MODEL_ID
    dim: int = DEFAULT_DIM

    @abc.abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        """Return an (N, dim) float32 array. Rows are L2-normalized."""


class StubEmbedder(Embedder):
    """Deterministic, hash-based embedder for tests.

    Distinct inputs yield distinct outputs; identical inputs yield identical
    outputs. Outputs are L2-normalized. This is sufficient for testing the
    indexing/retrieval pipeline without downloading the real model.
    """
    model_id = "stub://sha256"

    def __init__(self, dim: int = DEFAULT_DIM) -> None:
        self.dim = dim

    def embed(self, texts: List[str]) -> np.ndarray:
        rows = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode("utf-8")).digest()[:8], "big")
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(self.dim).astype(np.float32)
            v /= np.linalg.norm(v) or 1.0
            rows.append(v)
        return np.stack(rows, axis=0) if rows else np.zeros((0, self.dim), dtype=np.float32)


class JinaCodeGPUEmbedder(Embedder):
    """transformers + torch.float16 on CUDA."""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, batch_size: int = 32) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.model_id = model_id
        self.batch_size = batch_size
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(
            model_id, torch_dtype=torch.float16
        ).eval().to("cuda")
        self.dim = self.model.config.hidden_size

    def embed(self, texts: List[str]) -> np.ndarray:
        import torch
        out = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            enc = self.tokenizer(
                batch, padding=True, truncation=True, max_length=512,
                return_tensors="pt",
            ).to("cuda")
            with torch.inference_mode():
                hidden = self.model(**enc).last_hidden_state
                # Mean-pool over non-padding tokens.
                mask = enc["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(pooled.float().cpu().numpy())
        return np.concatenate(out, axis=0) if out else np.zeros((0, self.dim), dtype=np.float32)


class JinaCodeCPUEmbedder(Embedder):
    """llama-cpp-python with GGUF INT4."""

    def __init__(
        self,
        gguf_repo: str | None = None,
        gguf_file: str | None = None,
        batch_size: int = 8,
    ) -> None:
        from llama_cpp import Llama
        from huggingface_hub import hf_hub_download

        repo = gguf_repo or os.environ.get(
            "CBV_GGUF_REPO", "jinaai/jina-code-embeddings-1.5b-GGUF"
        )
        fname = gguf_file or os.environ.get(
            "CBV_GGUF_FILE", "jina-code-embeddings-1.5b.Q4_K_M.gguf"
        )
        path = hf_hub_download(repo_id=repo, filename=fname)
        self.model_id = f"{repo}/{fname}"
        self.batch_size = batch_size
        self.llm = Llama(
            model_path=path,
            embedding=True,
            n_ctx=512,
            n_threads=os.cpu_count() or 4,
            verbose=False,
        )
        self.dim = DEFAULT_DIM

    def embed(self, texts: List[str]) -> np.ndarray:
        # Note: `batch_size` here is iteration chunking, not true batched
        # inference. llama-cpp-python's `create_embedding` accepts a single
        # text at a time on the versions we target. If a future version
        # exposes batched embedding, switch to that.
        out_rows = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            for t in batch:
                r = self.llm.create_embedding(t)
                vec = np.array(r["data"][0]["embedding"], dtype=np.float32)
                norm = np.linalg.norm(vec) or 1.0
                out_rows.append(vec / norm)
        if not out_rows:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack(out_rows, axis=0)


def _cpu_embedder_or_friendly_error() -> "JinaCodeCPUEmbedder":
    try:
        return JinaCodeCPUEmbedder()
    except ImportError as e:
        raise RuntimeError(
            "codebase-vectorizer needs `llama-cpp-python` for the CPU embedder "
            "path, but it's not importable. Either:\n"
            "  - install it: `pip install llama-cpp-python` (Windows: requires "
            "VS Build Tools or a prebuilt wheel)\n"
            "  - run with CUDA available so the GPU path is used\n"
            "  - set CBV_STUB_EMBEDDER=1 for tests"
        ) from e


def make_embedder() -> Embedder:
    """Factory honoring CBV_STUB_EMBEDDER then CBV_FORCE_CPU then auto-detect."""
    if os.environ.get("CBV_STUB_EMBEDDER") == "1":
        return StubEmbedder()

    if os.environ.get("CBV_FORCE_CPU") == "1":
        return _cpu_embedder_or_friendly_error()

    try:
        import torch
        if torch.cuda.is_available():
            return JinaCodeGPUEmbedder()
    except ImportError:
        pass

    return _cpu_embedder_or_friendly_error()
