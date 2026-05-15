from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import architecture  # noqa: E402


class FakeWriter:
    def write(self, payload: dict) -> str:
        return "# fake\n\nLLM map.\n"


class BrokenWriter:
    def write(self, payload: dict) -> str:
        raise RuntimeError("adapter exploded")


def test_render_architecture_returns_writer_markdown_without_warning():
    text, warning = architecture.render_architecture(
        {"repo_name": "demo"},
        FakeWriter(),
    )

    assert text == "# fake\n\nLLM map.\n"
    assert warning is None


def test_render_architecture_falls_back_when_writer_raises():
    text, warning = architecture.render_architecture(
        {
            "repo_name": "demo",
            "counts": {
                "chunks": 2,
                "symbol_nodes": 3,
                "symbol_edges": 4,
                "flow_nodes": 5,
                "flow_edges": 6,
                "clusters": 7,
            },
            "top_nodes": [
                {"name": "pkg/router.py::route", "kind": "function", "pagerank": 0.5}
            ],
        },
        BrokenWriter(),
    )

    assert "# demo Architecture" in text
    assert "Chunks: 2" in text
    assert "pkg/router.py::route" in text
    assert warning is not None
    assert "LLM architecture generation failed" in warning


def test_fallback_supports_plan_count_keys():
    text, warning = architecture.render_architecture(
        {
            "repo_name": "demo",
            "counts": {
                "chunks": 2,
                "nodes_symbol": 3,
                "edges_symbol": 4,
                "nodes_block": 5,
                "edges_flow": 6,
                "clusters": 7,
            },
        },
        BrokenWriter(),
    )

    assert warning is not None
    assert "Chunks: 2" in text
    assert "Symbol nodes: 3" in text
    assert "Symbol edges: 4" in text
    assert "Flow nodes: 5" in text
    assert "Flow edges: 6" in text
