from __future__ import annotations

import ast
import json
from dataclasses import dataclass

from cbv import parser


@dataclass(frozen=True)
class FlowNode:
    name: str
    short_name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    parent_symbol: str


@dataclass(frozen=True)
class FlowEdge:
    src_name: str
    dst_name: str
    kind: str
    metadata: str | None


@dataclass
class _LoopContext:
    breaks: list[str]
    continues: list[str]
    break_defs: list[dict[str, list[tuple[str, int]]]]
    continue_defs: list[dict[str, list[tuple[str, int]]]]


_TS_FUNCTION_TYPES = frozenset(
    {
        "function_declaration",
        "method_definition",
        "method_declaration",
        "function_definition",
        "function_item",
        "local_function_statement",
        "method",
        "singleton_method",
    }
)
_TS_ASSIGNED_FUNCTION_TYPES = frozenset(("arrow_function", "function_expression"))
_TS_CLASS_TYPES = frozenset(
    {
        "class_declaration",
        "class_definition",
        "class",
        "class_specifier",
        "struct_specifier",
        "type_declaration",
        "struct_item",
    }
)
_TS_BLOCK_TYPES = frozenset(
    {
        "block",
        "statement_block",
        "statement_list",
        "compound_statement",
        "body_statement",
        "do_block",
        "then",
        "do",
        "else",
    }
)
_TS_IF_TYPES = frozenset(("if_statement", "if_expression", "unless", "if"))
_TS_LOOP_TYPES = frozenset(
    (
        "for_statement",
        "for_in_statement",
        "for_range_loop",
        "for_expression",
        "while_statement",
        "while_expression",
        "while",
        "do_statement",
        "loop_expression",
    )
)
_TS_RETURN_TYPES = frozenset(("return_statement",))
_TS_BREAK_TYPES = frozenset(("break_statement", "break_expression", "break"))
_TS_CONTINUE_TYPES = frozenset(("continue_statement", "continue_expression", "next"))
_TS_AUGMENTED_ASSIGNMENT_TYPES = frozenset(
    (
        "augmented_assignment_expression",
        "augmented_assignment_statement",
        "compound_assignment_expr",
        "operator_assignment",
    )
)
_TS_AUGMENTED_ASSIGNMENT_OPERATORS = frozenset(
    ("+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "**=", "//=", "&^=")
)
_TS_ASSIGNMENT_TYPES = frozenset(
    (
        "assignment_expression",
        "assignment_statement",
        "short_var_declaration",
        "augmented_assignment_expression",
        "augmented_assignment_statement",
        "compound_assignment_expr",
        "operator_assignment",
    )
)
_TS_IDENTIFIER_TYPES = frozenset(
    (
        "identifier",
        "shorthand_property_identifier",
        "field_identifier",
        "constant",
    )
)


def extract_flow(
    language: str,
    file_path: str,
    source: str,
) -> tuple[list[FlowNode], list[FlowEdge]]:
    if language == "python":
        return _extract_python_flow_cfg(file_path, source)

    language_meta = parser.language_for_name(language)
    if language_meta is None:
        return [], []

    tree = parser.parse(source.encode("utf-8"), language_meta)
    if tree is None:
        return [], []
    return _extract_tree_sitter_flow(language, file_path, source, tree)


def extract_python_flow(file_path: str, source: str) -> tuple[list[FlowNode], list[FlowEdge]]:
    """Legacy Python-only flow entrypoint; prefer extract_flow("python", ...)."""
    tree = ast.parse(source)
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []

    for fn, parent in _function_defs(tree, file_path):
        previous_name: str | None = None
        last_defs: dict[str, tuple[str, int]] = {
            name: (parent, line)
            for name, line in _python_argument_definitions(fn).items()
        }

        for idx, stmt in enumerate(fn.body, start=1):
            start = int(getattr(stmt, "lineno", fn.lineno))
            end = int(getattr(stmt, "end_lineno", start))
            name = f"{parent}#block_{idx}"
            short_name = f"block_{idx}"
            signature = ast.get_source_segment(source, stmt) or type(stmt).__name__
            nodes.append(
                FlowNode(
                    name=name,
                    short_name=short_name,
                    file_path=file_path,
                    start_line=start,
                    end_line=end,
                    signature=signature,
                    parent_symbol=parent,
                )
            )

            if previous_name is not None:
                edges.append(FlowEdge(previous_name, name, "controls", None))
            previous_name = name

            if isinstance(stmt, ast.If):
                edges.append(
                    FlowEdge(
                        name,
                        name,
                        "guards",
                        _json_guard_metadata(stmt),
                    )
                )

            stores, loads = _python_statement_store_load_names(stmt)
            for variable, use_line in sorted(loads.items()):
                prior = last_defs.get(variable)
                if prior is not None:
                    def_name, def_line = prior
                    edges.append(
                        FlowEdge(
                            def_name,
                            name,
                            "dataflow",
                            _json_dataflow_metadata(variable, def_line, use_line),
                        )
                    )
                elif variable in stores:
                    edges.append(
                        FlowEdge(
                            name,
                            name,
                            "dataflow",
                            _json_dataflow_metadata(variable, start, use_line),
                        )
                    )

            for variable, def_line in sorted(stores.items()):
                last_defs[variable] = (name, def_line)

    return nodes, _dedupe_edges(edges)


class _PythonFlowBuilder:
    def __init__(self, file_path: str, source: str, fn: ast.FunctionDef | ast.AsyncFunctionDef, parent: str):
        self.file_path = file_path
        self.source = source
        self.fn = fn
        self.parent = parent
        self.nodes: list[FlowNode] = []
        self.edges: list[FlowEdge] = []
        self.block_index = 0
        self.loop_stack: list[_LoopContext] = []
        self.reaching_defs: dict[str, list[tuple[str, int]]] = {
            name: [(self.entry_name, line)]
            for name, line in _python_argument_definitions(fn).items()
        }

    @property
    def entry_name(self) -> str:
        return f"{self.parent}#entry"

    @property
    def exit_name(self) -> str:
        return f"{self.parent}#exit"

    def build(self) -> tuple[list[FlowNode], list[FlowEdge]]:
        self.nodes.append(
            FlowNode(
                name=self.entry_name,
                short_name="entry",
                file_path=self.file_path,
                start_line=int(getattr(self.fn, "lineno", 1)),
                end_line=int(getattr(self.fn, "lineno", 1)),
                signature=f"entry {self.fn.name}",
                parent_symbol=self.parent,
            )
        )
        self.nodes.append(
            FlowNode(
                name=self.exit_name,
                short_name="exit",
                file_path=self.file_path,
                start_line=int(getattr(self.fn, "end_lineno", getattr(self.fn, "lineno", 1))),
                end_line=int(getattr(self.fn, "end_lineno", getattr(self.fn, "lineno", 1))),
                signature=f"exit {self.fn.name}",
                parent_symbol=self.parent,
            )
        )
        exits = self._emit_statements(self.fn.body, [self.entry_name])
        for exit_src in exits:
            self.edges.append(FlowEdge(exit_src, self.exit_name, "controls", None))
        return self.nodes, self.edges

    def _emit_statements(self, statements: list[ast.stmt], incoming: list[str]) -> list[str]:
        exits = incoming
        for stmt in statements:
            if not exits:
                break
            block_name = self._add_statement_block(stmt)
            for src_name in exits:
                self.edges.append(FlowEdge(src_name, block_name, "controls", None))
            exits = self._statement_exits(stmt, block_name)
        return exits

    def _add_statement_block(self, stmt: ast.stmt) -> str:
        self.block_index += 1
        start = int(getattr(stmt, "lineno", self.fn.lineno))
        end = int(getattr(stmt, "end_lineno", start))
        name = f"{self.parent}#block_{self.block_index}"
        self.nodes.append(
            FlowNode(
                name=name,
                short_name=f"block_{self.block_index}",
                file_path=self.file_path,
                start_line=start,
                end_line=end,
                signature=ast.get_source_segment(self.source, stmt) or type(stmt).__name__,
                parent_symbol=self.parent,
            )
        )
        self._add_dataflow_edges(stmt, name)
        return name

    def _statement_exits(self, stmt: ast.stmt, block_name: str) -> list[str]:
        if isinstance(stmt, ast.Return):
            self.edges.append(FlowEdge(block_name, self.exit_name, "controls", None))
            return []
        if isinstance(stmt, ast.Break):
            if self.loop_stack:
                context = self.loop_stack[-1]
                context.breaks.append(block_name)
                context.break_defs.append(_copy_reaching_defs(self.reaching_defs))
            return []
        if isinstance(stmt, ast.Continue):
            if self.loop_stack:
                context = self.loop_stack[-1]
                context.continues.append(block_name)
                context.continue_defs.append(_copy_reaching_defs(self.reaching_defs))
            return []
        if isinstance(stmt, ast.If):
            self.edges.append(FlowEdge(block_name, block_name, "guards", _json_guard_metadata(stmt)))
            incoming_defs = _copy_reaching_defs(self.reaching_defs)
            body_exits = self._emit_statements(stmt.body, [block_name])
            body_defs = _copy_reaching_defs(self.reaching_defs) if body_exits else {}
            self.reaching_defs = _copy_reaching_defs(incoming_defs)
            if stmt.orelse:
                else_exits = self._emit_statements(stmt.orelse, [block_name])
                else_defs = _copy_reaching_defs(self.reaching_defs) if else_exits else {}
            else:
                else_exits = [block_name]
                else_defs = _copy_reaching_defs(incoming_defs)
            self.reaching_defs = _merge_reaching_defs(body_defs, else_defs)
            return [*body_exits, *else_exits]
        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            self.edges.append(
                FlowEdge(block_name, block_name, "guards", _json_loop_guard_metadata(stmt))
            )
            incoming_defs = _copy_reaching_defs(self.reaching_defs)
            context = _LoopContext([], [], [], [])
            self.loop_stack.append(context)
            body_exits = self._emit_statements(stmt.body, [block_name])
            body_defs = _copy_reaching_defs(self.reaching_defs) if body_exits else {}
            self.loop_stack.pop()
            for body_exit in body_exits:
                self.edges.append(FlowEdge(body_exit, block_name, "controls", None))
            for continue_src in context.continues:
                self.edges.append(FlowEdge(continue_src, block_name, "controls", None))
            continue_defs = _merge_reaching_defs(*context.continue_defs)
            break_defs = _merge_reaching_defs(*context.break_defs)
            normal_defs = _merge_reaching_defs(incoming_defs, body_defs, continue_defs)
            if stmt.orelse:
                self.reaching_defs = _copy_reaching_defs(normal_defs)
                orelse_exits = self._emit_statements(stmt.orelse, [block_name])
                orelse_defs = _copy_reaching_defs(self.reaching_defs)
                self.reaching_defs = _merge_reaching_defs(orelse_defs, break_defs)
                return [*orelse_exits, *context.breaks]
            self.reaching_defs = _merge_reaching_defs(normal_defs, break_defs)
            return [block_name, *context.breaks]
        return [block_name]

    def _add_dataflow_edges(self, stmt: ast.stmt, block_name: str) -> None:
        stores, loads = _python_statement_store_load_names(stmt)
        for variable, use_line in sorted(loads.items()):
            prior_defs = self.reaching_defs.get(variable, [])
            for def_name, def_line in prior_defs:
                self.edges.append(
                    FlowEdge(
                        def_name,
                        block_name,
                        "dataflow",
                        _json_dataflow_metadata(variable, def_line, use_line),
                    )
                )
        for variable, def_line in sorted(stores.items()):
            self.reaching_defs[variable] = [(block_name, def_line)]


def _python_statement_store_load_names(stmt: ast.stmt) -> tuple[dict[str, int], dict[str, int]]:
    if isinstance(stmt, ast.If):
        return {}, _load_names(stmt.test)
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        stores = _store_names(stmt.target)
        loads = _load_names(stmt.iter)
        return stores, loads
    if isinstance(stmt, ast.While):
        return {}, _load_names(stmt.test)
    if isinstance(stmt, ast.Return):
        return {}, _load_names(stmt.value) if stmt.value is not None else {}
    if isinstance(stmt, ast.AugAssign):
        stores = _store_names(stmt.target)
        loads = _load_names(stmt.value)
        for variable, line in stores.items():
            loads.setdefault(variable, line)
        return stores, loads
    return _store_names(stmt), _load_names(stmt)


def _python_argument_definitions(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, int]:
    args = [
        *fn.args.posonlyargs,
        *fn.args.args,
        *fn.args.kwonlyargs,
    ]
    if fn.args.vararg is not None:
        args.append(fn.args.vararg)
    if fn.args.kwarg is not None:
        args.append(fn.args.kwarg)
    return {
        arg.arg: int(getattr(arg, "lineno", getattr(fn, "lineno", 0)))
        for arg in args
    }


def _copy_reaching_defs(
    defs: dict[str, list[tuple[str, int]]],
) -> dict[str, list[tuple[str, int]]]:
    return {variable: list(values) for variable, values in defs.items()}


def _merge_reaching_defs(
    *defs_maps: dict[str, list[tuple[str, int]]],
) -> dict[str, list[tuple[str, int]]]:
    merged: dict[str, list[tuple[str, int]]] = {}
    for defs in defs_maps:
        for variable, values in defs.items():
            bucket = merged.setdefault(variable, [])
            for value in values:
                if value not in bucket:
                    bucket.append(value)
    return merged


def _extract_python_flow_cfg(file_path: str, source: str) -> tuple[list[FlowNode], list[FlowEdge]]:
    tree = ast.parse(source)
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []
    for fn, parent in _function_defs(tree, file_path):
        fn_nodes, fn_edges = _PythonFlowBuilder(file_path, source, fn, parent).build()
        nodes.extend(fn_nodes)
        edges.extend(fn_edges)
    return nodes, _dedupe_edges(edges)


def _function_defs(
    tree: ast.AST,
    file_path: str,
) -> list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    definitions: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = []

    def visit(node: ast.AST, parent_symbol: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbol = f"{parent_symbol}::{child.name}"
                definitions.append((child, symbol))
                visit(child, symbol)
                continue
            if isinstance(child, ast.ClassDef):
                visit(child, f"{parent_symbol}::{child.name}")
                continue
            visit(child, parent_symbol)

    visit(tree, file_path)
    return definitions


def _extract_tree_sitter_flow(language: str, file_path: str, source: str, tree) -> tuple[list[FlowNode], list[FlowEdge]]:
    source_bytes = source.encode("utf-8")
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []
    for fn_node, parent_symbol in _ts_function_defs(tree.root_node, file_path, source_bytes):
        fn_nodes, fn_edges = _TreeSitterFlowBuilder(
            language,
            file_path,
            source_bytes,
            fn_node,
            parent_symbol,
        ).build()
        nodes.extend(fn_nodes)
        edges.extend(fn_edges)
    return nodes, _dedupe_edges(edges)


class _TreeSitterFlowBuilder:
    def __init__(self, language: str, file_path: str, source: bytes, fn_node, parent: str):
        self.language = language
        self.file_path = file_path
        self.source = source
        self.fn_node = fn_node
        self.parent = parent
        self.nodes: list[FlowNode] = []
        self.edges: list[FlowEdge] = []
        self.block_index = 0
        self.loop_stack: list[_LoopContext] = []
        self.reaching_defs: dict[str, list[tuple[str, int]]] = {
            name: [(self.entry_name, _ts_start_line(fn_node))]
            for name in _ts_parameter_names(fn_node, source)
        }

    @property
    def entry_name(self) -> str:
        return f"{self.parent}#entry"

    @property
    def exit_name(self) -> str:
        return f"{self.parent}#exit"

    def build(self) -> tuple[list[FlowNode], list[FlowEdge]]:
        short_name = self.parent.rsplit("::", 1)[-1]
        self.nodes.append(
            FlowNode(
                name=self.entry_name,
                short_name="entry",
                file_path=self.file_path,
                start_line=_ts_start_line(self.fn_node),
                end_line=_ts_start_line(self.fn_node),
                signature=f"entry {short_name}",
                parent_symbol=self.parent,
            )
        )
        self.nodes.append(
            FlowNode(
                name=self.exit_name,
                short_name="exit",
                file_path=self.file_path,
                start_line=_ts_end_line(self.fn_node),
                end_line=_ts_end_line(self.fn_node),
                signature=f"exit {short_name}",
                parent_symbol=self.parent,
            )
        )
        body = _ts_body_node(self.fn_node)
        statements = _ts_statement_children(body) if body is not None else []
        exits = self._emit_statements(statements, [self.entry_name])
        for src_name in exits:
            self.edges.append(FlowEdge(src_name, self.exit_name, "controls", None))
        return self.nodes, self.edges

    def _emit_statements(self, statements: list[object], incoming: list[str]) -> list[str]:
        exits = incoming
        for stmt in statements:
            if not exits:
                break
            block_name = self._add_statement_block(stmt)
            for src_name in exits:
                self.edges.append(FlowEdge(src_name, block_name, "controls", None))
            exits = self._statement_exits(stmt, block_name)
        return exits

    def _add_statement_block(self, stmt) -> str:
        self.block_index += 1
        name = f"{self.parent}#block_{self.block_index}"
        self.nodes.append(
            FlowNode(
                name=name,
                short_name=f"block_{self.block_index}",
                file_path=self.file_path,
                start_line=_ts_start_line(stmt),
                end_line=_ts_end_line(stmt),
                signature=_ts_signature(stmt, self.source),
                parent_symbol=self.parent,
            )
        )
        self._add_dataflow_edges(stmt, name)
        return name

    def _statement_exits(self, stmt, block_name: str) -> list[str]:
        control = _ts_control_node(stmt)
        if control.type in _TS_RETURN_TYPES:
            self.edges.append(FlowEdge(block_name, self.exit_name, "controls", None))
            return []
        if control.type in _TS_BREAK_TYPES:
            if self.loop_stack:
                context = self.loop_stack[-1]
                context.breaks.append(block_name)
                context.break_defs.append(_copy_reaching_defs(self.reaching_defs))
            return []
        if control.type in _TS_CONTINUE_TYPES:
            if self.loop_stack:
                context = self.loop_stack[-1]
                context.continues.append(block_name)
                context.continue_defs.append(_copy_reaching_defs(self.reaching_defs))
            return []
        if control.type in _TS_IF_TYPES:
            self.edges.append(
                FlowEdge(
                    block_name,
                    block_name,
                    "guards",
                    _json_ts_guard_metadata(control, self.source, branch="if"),
                )
            )
            incoming_defs = _copy_reaching_defs(self.reaching_defs)
            bodies = _ts_branch_bodies(control)
            body_exits = (
                self._emit_statements(_ts_statement_children(bodies[0]), [block_name])
                if bodies
                else [block_name]
            )
            body_defs = _copy_reaching_defs(self.reaching_defs) if body_exits else {}
            self.reaching_defs = _copy_reaching_defs(incoming_defs)
            else_exits = (
                self._emit_statements(_ts_statement_children(bodies[1]), [block_name])
                if len(bodies) > 1 and bodies[1] is not None
                else [block_name]
            )
            if len(bodies) > 1 and bodies[1] is not None:
                else_defs = _copy_reaching_defs(self.reaching_defs) if else_exits else {}
            else:
                else_defs = _copy_reaching_defs(incoming_defs)
            self.reaching_defs = _merge_reaching_defs(body_defs, else_defs)
            return [*body_exits, *else_exits]
        if control.type in _TS_LOOP_TYPES:
            self.edges.append(
                FlowEdge(
                    block_name,
                    block_name,
                    "guards",
                    _json_ts_guard_metadata(control, self.source, branch="loop"),
                )
            )
            incoming_defs = _copy_reaching_defs(self.reaching_defs)
            body = _ts_body_node(control)
            context = _LoopContext([], [], [], [])
            self.loop_stack.append(context)
            body_exits = self._emit_statements(_ts_statement_children(body), [block_name])
            body_defs = _copy_reaching_defs(self.reaching_defs) if body_exits else {}
            self.loop_stack.pop()
            for body_exit in body_exits:
                self.edges.append(FlowEdge(body_exit, block_name, "controls", None))
            for continue_src in context.continues:
                self.edges.append(FlowEdge(continue_src, block_name, "controls", None))
            self.reaching_defs = _merge_reaching_defs(
                incoming_defs,
                body_defs,
                *context.break_defs,
                *context.continue_defs,
            )
            return [block_name, *context.breaks]
        return [block_name]

    def _add_dataflow_edges(self, stmt, block_name: str) -> None:
        stores, loads = _ts_statement_store_load_names(stmt, self.source)
        for variable, use_line in sorted(loads.items()):
            prior_defs = self.reaching_defs.get(variable, [])
            for def_name, def_line in prior_defs:
                self.edges.append(
                    FlowEdge(
                        def_name,
                        block_name,
                        "dataflow",
                        _json_dataflow_metadata(variable, def_line, use_line),
                    )
                )
        for variable, def_line in sorted(stores.items()):
            self.reaching_defs[variable] = [(block_name, def_line)]


def _ts_function_defs(root, file_path: str, source: bytes) -> list[tuple[object, str]]:
    definitions: list[tuple[object, str]] = []

    def visit(node, parent_symbol: str) -> None:
        if node.type in _TS_CLASS_TYPES:
            short_name = _ts_definition_name(node, source)
            next_parent = f"{parent_symbol}::{short_name}" if short_name else parent_symbol
            for child in node.children:
                if child.is_named:
                    visit(child, next_parent)
            return
        assigned = _ts_assigned_function(node, source)
        if assigned is not None:
            fn_node, short_name = assigned
            symbol = f"{parent_symbol}::{short_name}"
            definitions.append((fn_node, symbol))
            for child in fn_node.children:
                if child.is_named:
                    visit(child, symbol)
            return
        if node.type in _TS_FUNCTION_TYPES:
            short_name = _ts_definition_name(node, source)
            if short_name:
                symbol = f"{parent_symbol}::{short_name}"
                definitions.append((node, symbol))
                for child in node.children:
                    if child.is_named:
                        visit(child, symbol)
                return
        for child in node.children:
            if child.is_named:
                visit(child, parent_symbol)

    visit(root, file_path)
    return definitions


def _ts_assigned_function(node, source: bytes) -> tuple[object, str] | None:
    if node.type != "variable_declarator":
        return None
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if (
        name_node is None
        or value_node is None
        or value_node.type not in _TS_ASSIGNED_FUNCTION_TYPES
    ):
        return None
    short_name = _ts_last_name_part(_ts_text(name_node, source))
    if not short_name:
        return None
    return value_node, short_name


def _ts_definition_name(node, source: bytes) -> str | None:
    for field_name in ("name", "property"):
        child = node.child_by_field_name(field_name)
        if child is not None:
            return _ts_last_name_part(_ts_text(child, source))
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        name = _ts_definition_name(declarator, source)
        if name:
            return name
    for child in node.children:
        if child.type in _TS_IDENTIFIER_TYPES or child.type in {"type_identifier"}:
            return _ts_last_name_part(_ts_text(child, source))
    return None


def _ts_body_node(node):
    body = node.child_by_field_name("body")
    if body is not None:
        return body
    for child in reversed(node.children):
        if child.is_named and child.type in _TS_BLOCK_TYPES:
            return child
    return None


def _ts_statement_children(node) -> list[object]:
    if node is None:
        return []
    if node.type == "else_clause":
        for child in node.children:
            if child.is_named and (child.type in _TS_BLOCK_TYPES or child.type in _TS_IF_TYPES):
                return [child] if child.type in _TS_IF_TYPES else _ts_statement_children(child)
        return []
    if node.type in _TS_BLOCK_TYPES:
        children: list[object] = []
        for child in node.children:
            if not child.is_named:
                continue
            if child.type in _TS_BLOCK_TYPES:
                children.extend(_ts_statement_children(child))
            else:
                children.append(child)
        return children
    return [node] if getattr(node, "is_named", False) else []


def _ts_branch_bodies(node) -> list[object | None]:
    blocks = [child for child in node.children if child.is_named and child.type in _TS_BLOCK_TYPES]
    else_clause = next((child for child in node.children if child.is_named and child.type == "else_clause"), None)
    if else_clause is not None:
        return [blocks[0] if blocks else None, else_clause]
    return blocks[:2]


def _ts_parameter_names(node, source: bytes) -> list[str]:
    params = node.child_by_field_name("parameters") or node.child_by_field_name("parameter")
    if params is None:
        for child in node.children:
            if child.type in {"formal_parameters", "parameter_list", "parameters"}:
                params = child
                break
    if params is None:
        return []
    names: list[str] = []
    for child in params.children:
        if not child.is_named:
            continue
        if child.type in _TS_IDENTIFIER_TYPES:
            names.append(_ts_text(child, source))
            continue
        name = child.child_by_field_name("name")
        if name is not None:
            names.append(_ts_text(name, source))
            continue
        for grandchild in child.children:
            if grandchild.type in _TS_IDENTIFIER_TYPES:
                names.append(_ts_text(grandchild, source))
                break
    return [name for name in names if name]


def _ts_statement_store_load_names(node, source: bytes) -> tuple[dict[str, int], dict[str, int]]:
    control = _ts_control_node(node)
    if control.type in _TS_IF_TYPES | _TS_LOOP_TYPES:
        condition = _ts_condition_node(control)
        loads = _ts_load_names(condition, source, set()) if condition is not None else {}
        return {}, loads
    if control.type in _TS_RETURN_TYPES:
        return {}, _ts_load_names(node, source, set())
    stores = _ts_store_names(node, source)
    excluded_stores = set() if _ts_contains_augmented_assignment(node, source) else set(stores)
    loads = _ts_load_names(node, source, excluded_stores)
    return stores, loads


def _ts_control_node(node):
    control_types = _TS_IF_TYPES | _TS_LOOP_TYPES | _TS_RETURN_TYPES | _TS_BREAK_TYPES | _TS_CONTINUE_TYPES
    if node.type in control_types:
        return node
    if node.type == "expression_statement":
        for child in node.children:
            if child.is_named and child.type in control_types:
                return child
    return node


def _ts_contains_augmented_assignment(node, source: bytes) -> bool:
    for candidate in _ts_descendants(node):
        if candidate.type in _TS_AUGMENTED_ASSIGNMENT_TYPES:
            return True
        if candidate.type in {"assignment_expression", "assignment_statement"}:
            if _ts_assignment_operator(candidate, source) in _TS_AUGMENTED_ASSIGNMENT_OPERATORS:
                return True
    return False


def _ts_assignment_operator(node, source: bytes) -> str | None:
    for child in node.children:
        if not child.is_named and child.type in _TS_AUGMENTED_ASSIGNMENT_OPERATORS:
            return child.type
    text = _ts_text(node, source).splitlines()[0]
    for operator in sorted(_TS_AUGMENTED_ASSIGNMENT_OPERATORS, key=len, reverse=True):
        if operator in text:
            return operator
    return None


def _ts_store_names(node, source: bytes) -> dict[str, int]:
    stores: dict[str, int] = {}

    def add_from(candidate) -> None:
        for ident in _ts_identifier_descendants(candidate):
            stores.setdefault(_ts_text(ident, source), _ts_start_line(ident))

    for candidate in _ts_descendants(node):
        if candidate.type == "variable_declarator":
            target = candidate.child_by_field_name("name")
            if target is not None:
                add_from(target)
        elif candidate.type in {"var_spec", "init_declarator"}:
            target = candidate.child_by_field_name("name") or candidate.child_by_field_name("declarator")
            if target is not None:
                add_from(target)
        elif candidate.type in _TS_ASSIGNMENT_TYPES:
            target = (
                candidate.child_by_field_name("left")
                or candidate.child_by_field_name("name")
            )
            if target is None:
                named_children = [child for child in candidate.children if child.is_named]
                target = named_children[0] if named_children else None
            if target is not None:
                add_from(target)
    return stores


def _ts_load_names(node, source: bytes, stores: set[str]) -> dict[str, int]:
    loads: dict[str, int] = {}
    for ident in _ts_identifier_descendants(node):
        name = _ts_text(ident, source)
        if name in stores:
            continue
        loads.setdefault(name, _ts_start_line(ident))
    return loads


def _ts_identifier_descendants(node) -> list[object]:
    return [candidate for candidate in _ts_descendants(node) if candidate.type in _TS_IDENTIFIER_TYPES]


def _ts_descendants(node) -> list[object]:
    descendants: list[object] = []
    stack = [node]
    while stack:
        current = stack.pop()
        descendants.append(current)
        stack.extend(reversed([child for child in current.children if child.is_named]))
    return descendants


def _json_loop_guard_metadata(stmt: ast.For | ast.AsyncFor | ast.While) -> str:
    if isinstance(stmt, ast.While):
        predicate = ast.unparse(stmt.test)
    else:
        predicate = ast.unparse(stmt.iter)
    return json.dumps(
        {
            "predicate": predicate,
            "branch": "loop",
            "line": int(getattr(stmt, "lineno", 0)),
        },
        sort_keys=True,
    )


def _json_ts_guard_metadata(node, source: bytes, *, branch: str) -> str:
    condition = _ts_condition_text(node, source)
    return json.dumps(
        {
            "predicate": condition,
            "branch": branch,
            "line": _ts_start_line(node),
        },
        sort_keys=True,
    )


def _ts_condition_text(node, source: bytes) -> str:
    condition = _ts_condition_node(node)
    if condition is None:
        return ""
    text = _ts_text(condition, source).strip()
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip()
    return text


def _ts_condition_node(node):
    condition = node.child_by_field_name("condition")
    if condition is None and node.type in {"if", "while"}:
        for child in node.children:
            if child.is_named and child.type not in _TS_BLOCK_TYPES:
                return child
    if condition is None:
        for child in node.children:
            if not child.is_named or child.type in _TS_BLOCK_TYPES or child.type == "else_clause":
                continue
            if child.type not in {"identifier", "type_identifier"}:
                condition = child
                break
    return condition


def _json_guard_metadata(stmt: ast.If) -> str:
    predicates = _if_predicates(stmt)
    first = predicates[0] if predicates else {"predicate": "", "branch": "if"}
    return json.dumps(
        {
            "predicate": first["predicate"],
            "branch": first["branch"],
            "predicates": predicates,
        },
        sort_keys=True,
    )


def _if_predicates(stmt: ast.If) -> list[dict[str, object]]:
    predicates: list[dict[str, object]] = []
    current: ast.If | None = stmt
    branch = "if"
    while current is not None:
        predicates.append(
            {
                "predicate": ast.unparse(current.test),
                "branch": branch,
                "line": int(getattr(current, "lineno", 0)),
            }
        )
        if len(current.orelse) == 1 and isinstance(current.orelse[0], ast.If):
            current = current.orelse[0]
            branch = "elif"
        else:
            current = None
    return predicates


def _json_dataflow_metadata(variable: str, definition_line: int, use_line: int) -> str:
    return json.dumps(
        {
            "variable": variable,
            "var": variable,
            "definition_line": definition_line,
            "use_line": use_line,
        },
        sort_keys=True,
    )


def _store_names(stmt: ast.AST) -> dict[str, int]:
    stores: dict[str, int] = {}
    for node in _scope_visible_nodes(stmt):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            stores.setdefault(node.id, int(getattr(node, "lineno", getattr(stmt, "lineno", 0))))
    return stores


def _load_names(stmt: ast.AST) -> dict[str, int]:
    loads: dict[str, int] = {}
    for node in _scope_visible_nodes(stmt):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loads.setdefault(node.id, int(getattr(node, "lineno", getattr(stmt, "lineno", 0))))
    return loads


_NESTED_SCOPE_TYPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _scope_visible_nodes(root: ast.AST):
    if isinstance(root, _NESTED_SCOPE_TYPES):
        return

    stack = [root]
    while stack:
        node = stack.pop()
        if node is not root and isinstance(node, _NESTED_SCOPE_TYPES):
            continue
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _dedupe_edges(edges: list[FlowEdge]) -> list[FlowEdge]:
    seen: set[tuple[str, str, str, str | None]] = set()
    deduped: list[FlowEdge] = []
    for edge in edges:
        key = (edge.src_name, edge.dst_name, edge.kind, edge.metadata)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


def _ts_signature(node, source: bytes) -> str:
    return _ts_text(node, source).splitlines()[0].strip()


def _ts_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _ts_start_line(node) -> int:
    return _ts_point_row(node.start_point) + 1


def _ts_end_line(node) -> int:
    return _ts_point_row(node.end_point) + 1


def _ts_point_row(point) -> int:
    row = getattr(point, "row", None)
    if row is not None:
        return int(row)
    return int(point[0])


def _ts_last_name_part(text: str) -> str:
    value = text.strip().strip("'\"<>")
    for separator in (".", "::", "/", "\\"):
        if separator in value:
            value = value.rsplit(separator, 1)[-1]
    if "(" in value:
        value = value.split("(", 1)[0]
    return value.strip().strip(";")
