from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SymbolNode:
    kind: str
    name: str
    short_name: str
    file_path: str
    start_line: int | None
    end_line: int | None
    signature: str | None = None
    parent_name: str | None = None
    chunk_id: int | None = None
    start_byte: int = 0
    end_byte: int = 0


@dataclass(frozen=True)
class SymbolEdge:
    src_name: str
    dst_name: str
    kind: str
    weight: float = 1.0
    metadata: str | None = None


@dataclass(frozen=True)
class ExtractedSymbols:
    nodes: list[SymbolNode]
    edges: list[SymbolEdge]


EDGE_WEIGHTS = {
    "defines": 5.0,
    "calls": 3.0,
    "imports": 1.5,
    "inherits": 3.0,
    "references": 2.0,
    "contains": 1.0,
}


_PYTHON_DEFINITION_TYPES = frozenset(("function_definition", "class_definition"))
_JS_FAMILY_LANGUAGES = frozenset(("javascript", "typescript", "tsx"))
_JS_DEFINITION_TYPES = frozenset(
    ("function_declaration", "method_definition", "class_declaration")
)
_IDENTIFIER_NODE_TYPES = frozenset(
    ("identifier", "property_identifier", "private_property_identifier")
)


def extract_symbols(
    file_path: Path,
    language: str,
    source: bytes,
    tree,
) -> ExtractedSymbols:
    nodes: list[SymbolNode] = [_file_node(file_path, source)]
    edges: list[SymbolEdge] = []
    module_name = file_path.as_posix()

    if tree is None:
        return ExtractedSymbols(nodes, edges)

    def walk(node, parent_symbol: str) -> None:
        current_parent = parent_symbol
        definition_kind = _definition_kind(language, node)
        short_name = _definition_name(node, source) if definition_kind else None

        if definition_kind is not None and short_name:
            full_name = f"{parent_symbol}::{short_name}"
            nodes.append(
                SymbolNode(
                    kind=definition_kind,
                    name=full_name,
                    short_name=short_name,
                    file_path=module_name,
                    start_line=_start_line(node),
                    end_line=_end_line(node),
                    signature=_signature(node, source),
                    parent_name=parent_symbol,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                )
            )
            edges.append(
                SymbolEdge(
                    src_name=parent_symbol,
                    dst_name=full_name,
                    kind="contains",
                    weight=EDGE_WEIGHTS["contains"],
                )
            )
            current_parent = full_name

        if language == "python" and node.type in {
            "import_from_statement",
            "import_statement",
        }:
            for dst_name in _python_import_names(node, source):
                edges.append(
                    SymbolEdge(
                        src_name=current_parent,
                        dst_name=dst_name,
                        kind="imports",
                        weight=EDGE_WEIGHTS["imports"],
                    )
                )

        if language == "python" and node.type == "call":
            dst_name = _call_name(node, source)
            if dst_name:
                edges.append(
                    SymbolEdge(
                        src_name=current_parent,
                        dst_name=dst_name,
                        kind="calls",
                        weight=EDGE_WEIGHTS["calls"],
                    )
                )

        if language in _JS_FAMILY_LANGUAGES and node.type == "call_expression":
            dst_name = _call_name(node, source)
            if dst_name:
                edges.append(
                    SymbolEdge(
                        src_name=current_parent,
                        dst_name=dst_name,
                        kind="calls",
                        weight=EDGE_WEIGHTS["calls"],
                    )
                )

        for child in node.children:
            walk(child, current_parent)

    walk(tree.root_node, module_name)
    return ExtractedSymbols(nodes, edges)


def _file_node(file_path: Path, source: bytes) -> SymbolNode:
    return SymbolNode(
        kind="file",
        name=file_path.as_posix(),
        short_name=file_path.name,
        file_path=file_path.as_posix(),
        start_line=1,
        end_line=1,
        start_byte=0,
        end_byte=len(source),
    )


def _definition_kind(language: str, node) -> str | None:
    if language == "python" and node.type in _PYTHON_DEFINITION_TYPES:
        return "class" if node.type == "class_definition" else "function"
    if language in _JS_FAMILY_LANGUAGES and node.type in _JS_DEFINITION_TYPES:
        return "class" if node.type == "class_declaration" else "function"
    return None


def _definition_name(node, source: bytes) -> str | None:
    name_node = (
        node.child_by_field_name("name")
        if hasattr(node, "child_by_field_name")
        else None
    )
    if name_node is not None:
        return _text(name_node, source)

    for child in node.children:
        if child.type in _IDENTIFIER_NODE_TYPES:
            return _text(child, source)
    return None


def _python_import_names(node, source: bytes) -> list[str]:
    names: list[str] = []
    if node.type == "import_from_statement":
        seen_import_keyword = False
        for child in node.children:
            if child.type == "import":
                seen_import_keyword = True
                continue
            if not seen_import_keyword:
                continue
            name = _imported_name(child, source)
            if name:
                names.append(name)
        return names

    for child in node.children:
        name = _imported_name(child, source)
        if name:
            names.append(name)
    return names


def _imported_name(node, source: bytes) -> str | None:
    if node.type == "aliased_import":
        for child in node.children:
            if child.type == "dotted_name":
                return _last_name_part(child, source)
        return None
    if node.type == "dotted_name":
        return _last_name_part(node, source)
    if node.type == "identifier":
        return _text(node, source)
    return None


def _call_name(node, source: bytes) -> str | None:
    function_node = (
        node.child_by_field_name("function")
        if hasattr(node, "child_by_field_name")
        else None
    )
    if function_node is None:
        named_children = [child for child in node.children if child.is_named]
        if not named_children:
            return None
        function_node = named_children[0]

    return _last_name_part(function_node, source)


def _last_name_part(node, source: bytes) -> str:
    text = _text(node, source).strip()
    if not text:
        return text
    for separator in (".", "::"):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    if "[" in text:
        text = text.split("[", 1)[0]
    return text


def _signature(node, source: bytes) -> str | None:
    text = _text(node, source)
    lines = text.splitlines()
    return lines[0] if lines else None


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _start_line(node) -> int:
    return _point_row(node.start_point) + 1


def _end_line(node) -> int:
    return _point_row(node.end_point) + 1


def _point_row(point) -> int:
    row = getattr(point, "row", None)
    if row is not None:
        return int(row)
    return int(point[0])
