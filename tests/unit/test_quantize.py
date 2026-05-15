"""Tests for cbv.quantize — INT8 quant/dequant for sqlite-vec storage."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import numpy as np

from cbv import quantize  # noqa: E402


def test_quantize_returns_int8_with_same_shape():
    x = np.random.default_rng(0).standard_normal((3, 1536)).astype(np.float32)
    q = quantize.quantize_int8(x)
    assert q.dtype == np.int8
    assert q.shape == (3, 1536)


def test_quantize_bounds():
    x = np.random.default_rng(0).standard_normal((1, 1536)).astype(np.float32) * 1000
    q = quantize.quantize_int8(x)
    assert q.min() >= -128
    assert q.max() <= 127


def test_quantize_normalizes_first():
    """Two inputs that differ only in magnitude quantize identically (up to rounding)."""
    base = np.random.default_rng(1).standard_normal((1, 1536)).astype(np.float32)
    q1 = quantize.quantize_int8(base)
    q2 = quantize.quantize_int8(base * 5.0)
    # Allow small differences from rounding at the boundary, but most must agree.
    agree = (q1 == q2).sum()
    assert agree >= int(q1.size * 0.99), f"only {agree}/{q1.size} agree"


def test_quantize_zero_vector_no_nan(recwarn):
    """A zero-magnitude row uses the norm=1.0 fallback to avoid divide-by-zero."""
    x = np.zeros((1, 1536), dtype=np.float32)
    q = quantize.quantize_int8(x)
    assert q.dtype == np.int8
    assert q.shape == (1, 1536)
    assert (q == 0).all()
    # No NaN warning leaked from the divide path.
    assert not any("invalid value" in str(w.message).lower() for w in recwarn)


def test_dequantize_is_approximate_inverse():
    rng = np.random.default_rng(42)
    x = rng.standard_normal((2, 1536)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)  # already-normalized
    q = quantize.quantize_int8(x)
    back = quantize.dequantize_int8(q)
    # Cosine similarity between original and dequantized should be very high.
    sim = (x * back).sum(axis=1) / (
        np.linalg.norm(x, axis=1) * np.linalg.norm(back, axis=1)
    )
    assert (sim > 0.995).all(), f"min sim = {sim.min()}"
