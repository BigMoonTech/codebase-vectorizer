"""Tests for cbv.embedder.

Slice 1 only covers the stub embedder behavior and the factory. The
real Jina embedder is exercised by the integration test (which skips
in stub mode by default) and by manual smoke runs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import numpy as np

from cbv import embedder  # noqa: E402


def test_stub_embedder_shape_and_dtype():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed(["hello", "world", "foo bar"])
    assert out.shape == (3, 1536)
    assert out.dtype == np.float32


def test_stub_embedder_deterministic():
    e = embedder.StubEmbedder(dim=1536)
    a = e.embed(["same text"])
    b = e.embed(["same text"])
    assert np.array_equal(a, b)


def test_stub_embedder_distinguishes_inputs():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed(["alpha", "beta"])
    # Different inputs produce different embeddings.
    assert not np.array_equal(out[0], out[1])


def test_stub_embedder_normalized():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed(["x", "yy", "zzz"])
    norms = np.linalg.norm(out, axis=1)
    np.testing.assert_allclose(norms, np.ones(3), atol=1e-5)


def test_factory_returns_stub_when_env_set(monkeypatch):
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    e = embedder.make_embedder()
    assert isinstance(e, embedder.StubEmbedder)


def test_factory_default_dim_matches_v1_schema(monkeypatch):
    monkeypatch.setenv("CBV_STUB_EMBEDDER", "1")
    e = embedder.make_embedder()
    assert e.dim == 1536


def test_stub_embedder_empty_list_returns_zero_rows():
    e = embedder.StubEmbedder(dim=1536)
    out = e.embed([])
    assert out.shape == (0, 1536)
    assert out.dtype == np.float32


def test_make_embedder_raises_friendly_error_when_cpu_unavailable(monkeypatch):
    """If llama_cpp can't be imported, make_embedder() must raise a clear
    RuntimeError rather than letting ImportError propagate."""
    import builtins
    import pytest
    monkeypatch.delenv("CBV_STUB_EMBEDDER", raising=False)
    monkeypatch.setenv("CBV_FORCE_CPU", "1")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "llama_cpp":
            raise ImportError("simulated: llama_cpp not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError) as exc:
        embedder.make_embedder()
    msg = str(exc.value)
    assert "llama-cpp-python" in msg
    assert "CBV_STUB_EMBEDDER" in msg
