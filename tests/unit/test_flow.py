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
RUBY_SOURCE = (
    "class Runner\n"
    "  def run(flag)\n"
    "    value = 0\n"
    "    while flag\n"
    "      value = 1\n"
    "      break\n"
    "    end\n"
    "    value\n"
    "  end\n"
    "\n"
    "  def self.build\n"
    "    run(true)\n"
    "  end\n"
    "end\n"
)
RUST_SOURCE = (
    "fn spin(limit: i32) -> i32 {\n"
    "    let mut total = 0;\n"
    "    while total < limit {\n"
    "        total += 1;\n"
    "    }\n"
    "    for item in 0..limit {\n"
    "        total += item;\n"
    "    }\n"
    "    total\n"
    "}\n"
)
RUBY_BRANCH_LOOP_SOURCE = (
    "def decide(flag, count)\n"
    "  value = 0\n"
    "  if flag\n"
    "    value = 1\n"
    "  else\n"
    "    value = 2\n"
    "  end\n"
    "  while count > 0\n"
    "    count = count - 1\n"
    "  end\n"
    "  value\n"
    "end\n"
)
JS_ASSIGNED_SOURCE = (
    "const decide = (flag) => {\n"
    "  let approved = false;\n"
    "  if (flag) {\n"
    "    approved = true;\n"
    "  }\n"
    "  return approved;\n"
    "};\n"
    "const other = function(flag) {\n"
    "  let approved = false;\n"
    "  if (flag) {\n"
    "    approved = true;\n"
    "  }\n"
    "  return approved;\n"
    "};\n"
)
TS_ASSIGNED_SOURCE = (
    "const decide = (flag: boolean): boolean => {\n"
    "  let approved = false;\n"
    "  if (flag) {\n"
    "    approved = true;\n"
    "  }\n"
    "  return approved;\n"
    "};\n"
)
CPP_METHOD_SOURCE = (
    "class Runner {\n"
    "public:\n"
    "  int run(bool flag) {\n"
    "    int value = 0;\n"
    "    if (flag) {\n"
    "      value = 1;\n"
    "    }\n"
    "    return value;\n"
    "  }\n"
    "};\n"
)


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


def test_python_branch_sensitive_dfg_keeps_alternate_reaching_definitions():
    source = (
        "def choose(flag):\n"
        "    x = 0\n"
        "    if flag:\n"
        "        x = 1\n"
        "    return x\n"
    )

    nodes, edges = flow.extract_flow("python", "branch.py", source)
    return_node = next(node for node in nodes if node.signature.strip() == "return x")
    reaching_lines = {
        json.loads(edge.metadata or "{}").get("definition_line")
        for edge in edges
        if edge.kind == "dataflow"
        and edge.dst_name == return_node.name
        and json.loads(edge.metadata or "{}").get("variable") == "x"
    }

    assert reaching_lines == {2, 4}


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


def test_javascript_flow_extracts_assigned_arrow_and_function_expression():
    nodes, edges = flow.extract_flow("javascript", "assigned.js", JS_ASSIGNED_SOURCE)

    parent_symbols = {node.parent_symbol for node in nodes}
    assert "assigned.js::decide" in parent_symbols
    assert "assigned.js::other" in parent_symbols
    assert any(edge.kind == "controls" for edge in edges)
    assert any(edge.kind == "guards" and "flag" in (edge.metadata or "") for edge in edges)
    assert any(edge.kind == "dataflow" and '"variable": "approved"' in (edge.metadata or "") for edge in edges)


def test_typescript_flow_extracts_assigned_arrow_function():
    nodes, edges = flow.extract_flow("typescript", "assigned.ts", TS_ASSIGNED_SOURCE)

    parent_symbols = {node.parent_symbol for node in nodes}
    assert "assigned.ts::decide" in parent_symbols
    assert any(edge.kind == "controls" for edge in edges)
    assert any(edge.kind == "guards" and "flag" in (edge.metadata or "") for edge in edges)
    assert any(edge.kind == "dataflow" and '"variable": "approved"' in (edge.metadata or "") for edge in edges)


def test_cpp_flow_uses_class_scoped_method_parent_symbol():
    nodes, edges = flow.extract_flow("cpp", "flow.cpp", CPP_METHOD_SOURCE)

    parent_symbols = {node.parent_symbol for node in nodes}
    assert "flow.cpp::Runner::run" in parent_symbols
    assert "flow.cpp::run" not in parent_symbols
    assert any(edge.kind == "controls" for edge in edges)


def test_ruby_flow_extracts_instance_and_singleton_methods():
    nodes, edges = flow.extract_flow("ruby", "flow.rb", RUBY_SOURCE)

    parent_symbols = {node.parent_symbol for node in nodes}
    assert "flow.rb::Runner::run" in parent_symbols
    assert "flow.rb::Runner::build" in parent_symbols
    assert any(edge.kind == "controls" for edge in edges)


def test_ruby_flow_emits_if_and_while_guards_and_loop_back_edge():
    nodes, edges = flow.extract_flow("ruby", "flow.rb", RUBY_BRANCH_LOOP_SOURCE)

    guard_payloads = [
        json.loads(edge.metadata or "{}")
        for edge in edges
        if edge.kind == "guards"
    ]
    control_edges = {
        (edge.src_name, edge.dst_name)
        for edge in edges
        if edge.kind == "controls"
    }
    blocks_by_signature = {node.signature: node.name for node in nodes}

    assert any(payload.get("predicate") == "flag" for payload in guard_payloads)
    assert any(payload.get("predicate") == "count > 0" for payload in guard_payloads)
    assert (
        blocks_by_signature["count = count - 1"],
        blocks_by_signature["while count > 0"],
    ) in control_edges


def test_rust_flow_extracts_common_loop_guards():
    _, edges = flow.extract_flow("rust", "flow.rs", RUST_SOURCE)

    loop_guards = [
        json.loads(edge.metadata or "{}")
        for edge in edges
        if edge.kind == "guards" and json.loads(edge.metadata or "{}").get("branch") == "loop"
    ]
    predicates = json.dumps(loop_guards)
    assert "total < limit" in predicates
    assert "0..limit" in predicates


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
