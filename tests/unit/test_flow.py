from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import flow  # noqa: E402


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "flow-heavy" / "flow_app.py"
FLOW_HEAVY_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "flow-heavy"

PY_SOURCE = (
    "def approve(user, items):\n"
    "    approved = False\n"
    "    if user.is_admin:\n"
    "        approved = True\n"
    "    else:\n"
    "        for item in items:\n"
    "            if item.blocked:\n"
    "                return False\n"
    "            approved = True\n"
    "    return approved\n"
)
JS_SOURCE = (FLOW_HEAVY_DIR / "js_flow.js").read_text(encoding="utf-8")
TS_SOURCE = (FLOW_HEAVY_DIR / "ts_flow.ts").read_text(encoding="utf-8")
GO_SOURCE = (FLOW_HEAVY_DIR / "go_flow.go").read_text(encoding="utf-8")


def _extract_fixture():
    return flow.extract_python_flow("flow_app.py", FIXTURE.read_text(encoding="utf-8"))


def test_cfg_emits_true_false_loop_and_exit_blocks():
    nodes, edges = flow.extract_flow("python", "flow.py", PY_SOURCE)

    assert any(edge.kind == "controls" for edge in edges)
    assert any(
        edge.kind == "guards" and "is_admin" in (edge.metadata or "")
        for edge in edges
    )
    assert any("exit" in node.short_name for node in nodes)


def test_dfg_reaches_use_with_variable_metadata():
    _, edges = flow.extract_flow("python", "flow.py", PY_SOURCE)

    assert any(
        edge.kind == "dataflow" and '"variable": "approved"' in (edge.metadata or "")
        for edge in edges
    )


@pytest.mark.parametrize(
    ("language", "filename", "source"),
    [
        ("python", "flow.py", PY_SOURCE),
        ("javascript", "flow.js", JS_SOURCE),
        ("typescript", "flow.ts", TS_SOURCE),
        ("go", "flow.go", GO_SOURCE),
    ],
)
def test_tier_a_flow_extractors_do_not_fail_and_emit_blocks(language, filename, source):
    nodes, edges = flow.extract_flow(language, filename, source)

    assert nodes
    assert any(edge.kind == "controls" for edge in edges)


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


def test_extract_python_flow_prunes_comprehension_scope_dataflow_from_outer_function():
    source = (
        "def outer(values):\n"
        "    items = [item for item in values]\n"
        "    return item\n"
    )

    _, edges = flow.extract_python_flow("scope.py", source)

    item_edges = [
        edge
        for edge in edges
        if edge.kind == "dataflow"
        and json.loads(edge.metadata or "{}").get("variable") == "item"
    ]
    assert item_edges == []
