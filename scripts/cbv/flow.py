from __future__ import annotations

import ast
import json
from dataclasses import dataclass


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


def extract_python_flow(file_path: str, source: str) -> tuple[list[FlowNode], list[FlowEdge]]:
    tree = ast.parse(source)
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []

    for fn, parent in _function_defs(tree, file_path):
        previous_name: str | None = None
        last_defs: dict[str, tuple[str, int]] = {
            arg.arg: (parent, getattr(arg, "lineno", fn.lineno))
            for arg in fn.args.args
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

            stores = _store_names(stmt)
            loads = _load_names(stmt)
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
