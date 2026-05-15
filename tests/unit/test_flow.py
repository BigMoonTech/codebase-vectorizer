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


def _node_with_exact_signature(nodes, signature):
    return next(node for node in nodes if node.signature.strip() == signature)


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


def test_python_loop_break_does_not_flow_to_later_body_statement():
    source = (
        "def walk(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        if item.stop:\n"
        "            break\n"
        "        total += item.value\n"
        "    return total\n"
    )

    nodes, edges = flow.extract_flow("python", "loop.py", source)
    break_node = _node_with_exact_signature(nodes, "break")
    after_break = _node_with_exact_signature(nodes, "total += item.value")
    return_node = _node_with_exact_signature(nodes, "return total")

    assert not any(
        edge.kind == "controls"
        and edge.src_name == break_node.name
        and edge.dst_name == after_break.name
        for edge in edges
    )
    assert any(
        edge.kind == "controls"
        and edge.src_name == break_node.name
        and edge.dst_name == return_node.name
        for edge in edges
    )


def test_python_loop_continue_flows_to_loop_header_not_later_body_statement():
    source = (
        "def walk(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        if item.skip:\n"
        "            continue\n"
        "        total += item.value\n"
        "    return total\n"
    )

    nodes, edges = flow.extract_flow("python", "loop.py", source)
    continue_node = _node_with_exact_signature(nodes, "continue")
    after_continue = _node_with_exact_signature(nodes, "total += item.value")
    loop_node = next(node for node in nodes if node.signature.strip().startswith("for item in items"))

    assert not any(
        edge.kind == "controls"
        and edge.src_name == continue_node.name
        and edge.dst_name == after_continue.name
        for edge in edges
    )
    assert any(
        edge.kind == "controls"
        and edge.src_name == continue_node.name
        and edge.dst_name == loop_node.name
        for edge in edges
    )


def test_python_entry_dataflow_seeds_all_argument_forms():
    source = (
        "def collect(pos, /, normal, *items, named, **extras):\n"
        "    return pos, normal, items, named, extras\n"
    )

    nodes, edges = flow.extract_flow("python", "args.py", source)
    return_node = _node_with_exact_signature(
        nodes,
        "return pos, normal, items, named, extras",
    )
    variables = {
        json.loads(edge.metadata or "{}").get("variable")
        for edge in edges
        if edge.kind == "dataflow"
        and edge.src_name == "args.py::collect#entry"
        and edge.dst_name == return_node.name
    }

    assert variables == {"pos", "normal", "items", "named", "extras"}


def test_python_augassign_reads_previous_target_definition_and_redefines():
    source = (
        "def bump(seed):\n"
        "    x = seed\n"
        "    x += 1\n"
        "    return x\n"
    )

    nodes, edges = flow.extract_flow("python", "aug.py", source)
    aug_node = _node_with_exact_signature(nodes, "x += 1")
    return_node = _node_with_exact_signature(nodes, "return x")
    payloads = [
        (edge.src_name, edge.dst_name, json.loads(edge.metadata or "{}"))
        for edge in edges
        if edge.kind == "dataflow"
    ]

    assert any(
        dst == aug_node.name
        and payload.get("variable") == "x"
        and payload.get("definition_line") == 2
        and payload.get("use_line") == 3
        for _, dst, payload in payloads
    )
    assert any(
        src == aug_node.name
        and dst == return_node.name
        and payload.get("variable") == "x"
        and payload.get("definition_line") == 3
        and payload.get("use_line") == 4
        for src, dst, payload in payloads
    )


def test_tree_sitter_loop_control_and_augassign_edges_for_javascript():
    source = (
        "function walk(items, seed) {\n"
        "  let total = seed;\n"
        "  for (const item of items) {\n"
        "    if (item.skip) {\n"
        "      continue;\n"
        "    }\n"
        "    total += item.value;\n"
        "    if (item.stop) {\n"
        "      break;\n"
        "    }\n"
        "    total += 10;\n"
        "  }\n"
        "  return total;\n"
        "}\n"
    )

    nodes, edges = flow.extract_flow("javascript", "loop.js", source)
    continue_node = _node_with_exact_signature(nodes, "continue;")
    break_node = _node_with_exact_signature(nodes, "break;")
    after_continue = _node_with_exact_signature(nodes, "total += item.value;")
    after_break = _node_with_exact_signature(nodes, "total += 10;")
    loop_node = next(node for node in nodes if node.signature.strip().startswith("for "))
    return_node = _node_with_exact_signature(nodes, "return total;")
    dataflow_payloads = [
        (edge.src_name, edge.dst_name, json.loads(edge.metadata or "{}"))
        for edge in edges
        if edge.kind == "dataflow"
    ]

    assert not any(
        edge.kind == "controls"
        and edge.src_name == continue_node.name
        and edge.dst_name == after_continue.name
        for edge in edges
    )
    assert any(
        edge.kind == "controls"
        and edge.src_name == continue_node.name
        and edge.dst_name == loop_node.name
        for edge in edges
    )
    assert not any(
        edge.kind == "controls"
        and edge.src_name == break_node.name
        and edge.dst_name == after_break.name
        for edge in edges
    )
    assert any(
        edge.kind == "controls"
        and edge.src_name == break_node.name
        and edge.dst_name == return_node.name
        for edge in edges
    )
    assert any(
        dst == after_continue.name
        and payload.get("variable") == "total"
        and payload.get("definition_line") == 2
        and payload.get("use_line") == 7
        for _, dst, payload in dataflow_payloads
    )
    assert any(
        src == after_continue.name
        and payload.get("variable") == "total"
        and payload.get("definition_line") == 7
        and payload.get("use_line") == 13
        for src, _, payload in dataflow_payloads
    )


@pytest.mark.parametrize(
    (
        "language",
        "filename",
        "source",
        "continue_signature",
        "break_signature",
        "after_continue_signature",
        "after_break_signature",
        "loop_prefix",
        "after_loop_signature",
    ),
    [
        (
            "ruby",
            "loop.rb",
            (
                "def walk(count)\n"
                "  total = 0\n"
                "  while count > 0\n"
                "    count -= 1\n"
                "    if count == 3\n"
                "      next\n"
                "    end\n"
                "    total += count\n"
                "    if count == 1\n"
                "      break\n"
                "    end\n"
                "    total += 10\n"
                "  end\n"
                "  total\n"
                "end\n"
            ),
            "next",
            "break",
            "total += count",
            "total += 10",
            "while count > 0",
            "total",
        ),
        (
            "rust",
            "loop.rs",
            (
                "fn walk(mut count: i32) -> i32 {\n"
                "    let mut total = 0;\n"
                "    while count > 0 {\n"
                "        count -= 1;\n"
                "        if count == 3 {\n"
                "            continue;\n"
                "        }\n"
                "        total += count;\n"
                "        if count == 1 {\n"
                "            break;\n"
                "        }\n"
                "        total += 10;\n"
                "    }\n"
                "    total\n"
                "}\n"
            ),
            "continue;",
            "break;",
            "total += count;",
            "total += 10;",
            "while count > 0",
            "total",
        ),
    ],
)
def test_tree_sitter_ruby_and_rust_loop_control_edges(
    language,
    filename,
    source,
    continue_signature,
    break_signature,
    after_continue_signature,
    after_break_signature,
    loop_prefix,
    after_loop_signature,
):
    nodes, edges = flow.extract_flow(language, filename, source)
    continue_node = _node_with_exact_signature(nodes, continue_signature)
    break_node = _node_with_exact_signature(nodes, break_signature)
    after_continue = _node_with_exact_signature(nodes, after_continue_signature)
    after_break = _node_with_exact_signature(nodes, after_break_signature)
    loop_node = next(node for node in nodes if node.signature.strip().startswith(loop_prefix))
    after_loop = _node_with_exact_signature(nodes, after_loop_signature)

    assert not any(
        edge.kind == "controls"
        and edge.src_name == continue_node.name
        and edge.dst_name == after_continue.name
        for edge in edges
    )
    assert any(
        edge.kind == "controls"
        and edge.src_name == continue_node.name
        and edge.dst_name == loop_node.name
        for edge in edges
    )
    assert not any(
        edge.kind == "controls"
        and edge.src_name == break_node.name
        and edge.dst_name == after_break.name
        for edge in edges
    )
    assert any(
        edge.kind == "controls"
        and edge.src_name == break_node.name
        and edge.dst_name == after_loop.name
        for edge in edges
    )


@pytest.mark.parametrize(
    (
        "language",
        "filename",
        "source",
        "entry_name",
        "aug_signature",
        "use_signature",
        "entry_line",
        "aug_line",
        "use_line",
    ),
    [
        (
            "go",
            "aug.go",
            (
                "package flow\n"
                "func Bump(total int) int {\n"
                "    total += 1\n"
                "    return total\n"
                "}\n"
            ),
            "aug.go::Bump#entry",
            "total += 1",
            "return total",
            2,
            3,
            4,
        ),
        (
            "rust",
            "aug.rs",
            (
                "fn bump(mut total: i32) -> i32 {\n"
                "    total += 1;\n"
                "    total\n"
                "}\n"
            ),
            "aug.rs::bump#entry",
            "total += 1;",
            "total",
            1,
            2,
            3,
        ),
        (
            "ruby",
            "aug.rb",
            (
                "def bump(total)\n"
                "  total += 1\n"
                "  total\n"
                "end\n"
            ),
            "aug.rb::bump#entry",
            "total += 1",
            "total",
            1,
            2,
            3,
        ),
        (
            "cpp",
            "aug.cpp",
            (
                "int bump(int seed) {\n"
                "  int total = seed;\n"
                "  total += 1;\n"
                "  return total;\n"
                "}\n"
            ),
            "aug.cpp::bump#block_1",
            "total += 1;",
            "return total;",
            2,
            3,
            4,
        ),
    ],
)
def test_tree_sitter_augassign_reads_target_and_redefines(
    language,
    filename,
    source,
    entry_name,
    aug_signature,
    use_signature,
    entry_line,
    aug_line,
    use_line,
):
    nodes, edges = flow.extract_flow(language, filename, source)
    aug_node = _node_with_exact_signature(nodes, aug_signature)
    use_node = _node_with_exact_signature(nodes, use_signature)
    payloads = [
        (edge.src_name, edge.dst_name, json.loads(edge.metadata or "{}"))
        for edge in edges
        if edge.kind == "dataflow"
    ]

    assert any(
        src == entry_name
        and dst == aug_node.name
        and payload.get("variable") == "total"
        and payload.get("definition_line") == entry_line
        and payload.get("use_line") == aug_line
        for src, dst, payload in payloads
    )
    assert any(
        src == aug_node.name
        and dst == use_node.name
        and payload.get("variable") == "total"
        and payload.get("definition_line") == aug_line
        and payload.get("use_line") == use_line
        for src, dst, payload in payloads
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
