from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import flow  # noqa: E402


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "flow-heavy" / "flow_app.py"


def _extract_fixture():
    return flow.extract_python_flow("flow_app.py", FIXTURE.read_text(encoding="utf-8"))


def test_extract_python_flow_emits_function_statement_blocks_and_controls():
    nodes, edges = _extract_fixture()

    top_level_blocks = {node.short_name: node for node in nodes}
    assert {"block_1", "block_2", "block_3"}.issubset(top_level_blocks)
    assert top_level_blocks["block_1"].parent_symbol == "flow_app.py::decide"
    assert top_level_blocks["block_1"].start_line == 2
    assert top_level_blocks["block_2"].start_line == 3
    assert top_level_blocks["block_3"].start_line == 7

    control_edges = {
        (edge.src_name, edge.dst_name)
        for edge in edges
        if edge.kind == "controls"
    }
    assert (
        "flow_app.py::decide#block_1",
        "flow_app.py::decide#block_2",
    ) in control_edges
    assert (
        "flow_app.py::decide#block_2",
        "flow_app.py::decide#block_3",
    ) in control_edges


def test_extract_python_flow_preserves_if_predicate_guard_metadata():
    _, edges = _extract_fixture()

    guard_payloads = [
        json.loads(edge.metadata or "{}")
        for edge in edges
        if edge.kind == "guards"
    ]

    assert any(payload.get("predicate") == "user.is_admin" for payload in guard_payloads)
    assert any("amount < 100" in json.dumps(payload) for payload in guard_payloads)


def test_extract_python_flow_emits_basic_approved_dataflow_metadata():
    _, edges = _extract_fixture()

    approved_edges = [
        json.loads(edge.metadata or "{}")
        for edge in edges
        if edge.kind == "dataflow" and "approved" in (edge.metadata or "")
    ]

    assert approved_edges
    assert any(payload.get("variable") == "approved" for payload in approved_edges)
    assert any(payload.get("use_line") == 7 for payload in approved_edges)


def test_extract_python_flow_uses_symbol_style_parent_symbols_for_methods_and_nested_functions():
    source = (
        "class Alpha:\n"
        "    def render(self, value):\n"
        "        return value\n"
        "\n"
        "class Beta:\n"
        "    def render(self, value):\n"
        "        return value\n"
        "\n"
        "def outer(value):\n"
        "    def inner(delta):\n"
        "        return value + delta\n"
        "    return inner(value)\n"
    )

    nodes, _ = flow.extract_python_flow("scopes.py", source)

    parent_symbols = {node.parent_symbol for node in nodes}
    assert "scopes.py::Alpha::render" in parent_symbols
    assert "scopes.py::Beta::render" in parent_symbols
    assert "scopes.py::outer::inner" in parent_symbols
    assert "scopes.py::render" not in parent_symbols
    assert "scopes.py::inner" not in parent_symbols


def test_extract_python_flow_prunes_nested_scope_dataflow_from_outer_function():
    source = (
        "def outer(seed):\n"
        "    current = seed\n"
        "    def inner():\n"
        "        leaked = seed\n"
        "        return leaked\n"
        "    return current\n"
    )

    _, edges = flow.extract_python_flow("scope.py", source)

    outer_leaked_edges = [
        edge
        for edge in edges
        if edge.kind == "dataflow"
        and (
            edge.src_name.startswith("scope.py::outer#")
            or edge.dst_name.startswith("scope.py::outer#")
        )
        and json.loads(edge.metadata or "{}").get("variable") == "leaked"
    ]
    assert outer_leaked_edges == []
