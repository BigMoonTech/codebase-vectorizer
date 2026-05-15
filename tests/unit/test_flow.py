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
