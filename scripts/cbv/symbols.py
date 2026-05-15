from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cbv import parser, tag_queries


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


@dataclass(frozen=True)
class _RawDefinition:
    node: object
    kind: str
    short_name: str


@dataclass(frozen=True)
class _DefinitionEntry:
    node: object
    kind: str
    name: str
    short_name: str
    parent_name: str


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
_JS_ASSIGNED_FUNCTION_TYPES = frozenset(
    ("arrow_function", "function_expression", "generator_function")
)
_IDENTIFIER_NODE_TYPES = frozenset(
    (
        "identifier",
        "type_identifier",
        "property_identifier",
        "field_identifier",
        "private_property_identifier",
        "package_identifier",
        "qualified_identifier",
        "scoped_identifier",
        "destructor_name",
        "operator_name",
    )
)
_STRING_CONTENT_NODE_TYPES = frozenset(
    (
        "string_content",
        "string_fragment",
        "interpreted_string_literal_content",
        "raw_string_literal_content",
        "system_lib_string",
    )
)
_CALL_COMPATIBLE_KINDS = frozenset(("function", "method"))
_REFERENCE_COMPATIBLE_KINDS = frozenset(
    ("class", "function", "method", "module", "variable")
)


def extract_symbols(
    file_path: Path,
    language: str,
    source: bytes,
    tree,
) -> ExtractedSymbols:
    if tree is None:
        return ExtractedSymbols([_file_node(file_path, source)], [])

    try:
        return _extract_symbols_with_queries(file_path, language, source, tree)
    except Exception:
        return _extract_symbols_bootstrap(file_path, language, source, tree)


def _extract_symbols_with_queries(
    file_path: Path,
    language: str,
    source: bytes,
    tree,
) -> ExtractedSymbols:
    module_name = file_path.as_posix()
    nodes: list[SymbolNode] = [_file_node(file_path, source)]
    edges: list[SymbolEdge] = []

    captures = _query_captures(language, tree)
    parent_by_key = _parent_map(tree.root_node)
    raw_definitions = _definition_captures(language, source, captures, parent_by_key)
    definitions: list[_DefinitionEntry] = []

    for raw in raw_definitions:
        parent = _nearest_enclosing_definition(raw.node, definitions)
        parent_name = parent.name if parent is not None else module_name
        kind = _effective_definition_kind(raw.kind, parent)
        full_name = f"{parent_name}::{raw.short_name}"

        nodes.append(
            SymbolNode(
                kind=kind,
                name=full_name,
                short_name=raw.short_name,
                file_path=module_name,
                start_line=_start_line(raw.node),
                end_line=_end_line(raw.node),
                signature=_signature(raw.node, source),
                parent_name=parent_name,
                start_byte=raw.node.start_byte,
                end_byte=raw.node.end_byte,
            )
        )
        edges.append(
            SymbolEdge(
                src_name=parent_name,
                dst_name=full_name,
                kind="contains",
                weight=EDGE_WEIGHTS["contains"],
            )
        )
        definitions.append(
            _DefinitionEntry(
                node=raw.node,
                kind=kind,
                name=full_name,
                short_name=raw.short_name,
                parent_name=parent_name,
            )
        )

    edges.extend(
        _reference_edges(
            language,
            source,
            captures,
            definitions,
            module_name,
        )
    )
    return ExtractedSymbols(nodes, edges)


def _query_captures(language: str, tree) -> list[tuple[str, object]]:
    language_meta = parser.language_for_name(language)
    if language_meta is None:
        raise ValueError(f"unsupported language: {language}")

    from tree_sitter import Query, QueryCursor
    from tree_sitter_language_pack import get_language

    ts_language = get_language(language_meta.ts_language_name)
    query = Query(ts_language, tag_queries.query_source(language))
    raw_captures = QueryCursor(query).captures(tree.root_node)

    if isinstance(raw_captures, dict):
        return [
            (capture_name, node)
            for capture_name, captured_nodes in raw_captures.items()
            for node in captured_nodes
        ]

    captures: list[tuple[str, object]] = []
    for item in raw_captures:
        node, capture = item
        capture_name = (
            query.capture_name(capture)
            if isinstance(capture, int)
            else str(capture)
        )
        captures.append((capture_name, node))
    return captures


def _definition_captures(
    language: str,
    source: bytes,
    captures: list[tuple[str, object]],
    parent_by_key: dict[tuple[int, int, str], object],
) -> list[_RawDefinition]:
    definitions: list[_RawDefinition] = []
    seen: set[tuple[tuple[int, int, str], str, str]] = set()

    for capture_name, node in captures:
        kind = tag_queries.CAPTURE_TO_NODE_KIND.get(capture_name)
        if kind is None:
            continue

        definition_node = _definition_container_node(node, parent_by_key)
        short_name = _definition_name(language, definition_node, source, parent_by_key)
        if not short_name:
            continue

        key = (_node_key(definition_node), kind, short_name)
        if key in seen:
            continue
        seen.add(key)
        definitions.append(_RawDefinition(definition_node, kind, short_name))

    definitions.sort(key=lambda entry: (entry.node.start_byte, -entry.node.end_byte))
    return definitions


def _definition_container_node(
    node,
    parent_by_key: dict[tuple[int, int, str], object],
):
    current = node
    while current is not None:
        if _looks_like_definition_container(current):
            return current
        current = parent_by_key.get(_node_key(current))
    return node


def _looks_like_definition_container(node) -> bool:
    if node.type in {
        "class_definition",
        "function_definition",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
        "struct_declaration",
        "method_declaration",
        "constructor_declaration",
        "local_function_statement",
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
        "function_expression",
        "generator_function",
        "arrow_function",
        "method_signature",
        "abstract_method_signature",
        "function_signature",
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "function_declarator",
        "function_definition",
        "class_specifier",
        "struct_specifier",
        "method",
        "singleton_method",
        "module",
        "class",
        "type_spec",
        "method_declaration",
    }:
        return True
    return False


def _effective_definition_kind(
    kind: str,
    parent: _DefinitionEntry | None,
) -> str:
    if kind == "function" and parent is not None and parent.kind == "class":
        return "method"
    return kind


def _reference_edges(
    language: str,
    source: bytes,
    captures: list[tuple[str, object]],
    definitions: list[_DefinitionEntry],
    module_name: str,
) -> list[SymbolEdge]:
    edges: list[SymbolEdge] = []
    seen: set[tuple[str, str, str]] = set()

    for capture_name, node in captures:
        edge_kind = tag_queries.CAPTURE_TO_EDGE_KIND.get(capture_name)
        if edge_kind is None:
            continue

        src_definition = _nearest_enclosing_definition(node, definitions)
        src_name = src_definition.name if src_definition is not None else module_name

        for dst_name in _reference_names(language, edge_kind, node, source):
            if not dst_name:
                continue
            dst_name = _resolve_same_file_reference(dst_name, edge_kind, definitions)
            key = (src_name, dst_name, edge_kind)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                SymbolEdge(
                    src_name=src_name,
                    dst_name=dst_name,
                    kind=edge_kind,
                    weight=EDGE_WEIGHTS[edge_kind],
                )
            )

    return edges


def _reference_names(
    language: str,
    edge_kind: str,
    node,
    source: bytes,
) -> list[str]:
    if edge_kind == "imports":
        return _import_reference_names(language, node, source)

    if edge_kind == "calls":
        name = _call_name(node, source)
    else:
        name = _last_name_part(node, source)

    return [name] if name else []


def _import_reference_names(language: str, node, source: bytes) -> list[str]:
    if language == "python":
        return _python_import_names(node, source)

    identifiers = _identifier_descendant_texts(node, source)
    strings = _string_descendant_texts(node, source)

    if language in _JS_FAMILY_LANGUAGES and identifiers:
        return identifiers
    if language == "ruby" and strings:
        return [_module_basename(value) for value in strings]
    if identifiers:
        return [identifiers[-1]]
    if strings:
        return [_module_basename(value) for value in strings]

    name = _last_name_part(node, source)
    return [name] if name else []


def _resolve_same_file_reference(
    dst_name: str,
    edge_kind: str,
    definitions: list[_DefinitionEntry],
) -> str:
    if "::" in dst_name:
        return dst_name

    compatible_kinds = _compatible_kinds_for_edge(edge_kind)
    if not compatible_kinds:
        return dst_name

    matches = [
        definition
        for definition in definitions
        if definition.short_name == dst_name and definition.kind in compatible_kinds
    ]
    if len(matches) == 1:
        return matches[0].name
    return dst_name


def _compatible_kinds_for_edge(edge_kind: str) -> frozenset[str]:
    if edge_kind == "calls":
        return _CALL_COMPATIBLE_KINDS
    if edge_kind == "inherits":
        return frozenset(("class",))
    if edge_kind == "references":
        return _REFERENCE_COMPATIBLE_KINDS
    return frozenset()


def _nearest_enclosing_definition(
    node,
    definitions: list[_DefinitionEntry],
) -> _DefinitionEntry | None:
    nearest = None
    nearest_size = None
    for definition in definitions:
        if _same_node(definition.node, node):
            continue
        if not _node_contains(definition.node, node):
            continue

        size = definition.node.end_byte - definition.node.start_byte
        if nearest_size is None or size < nearest_size:
            nearest = definition
            nearest_size = size
    return nearest


def _definition_name(
    language: str,
    node,
    source: bytes,
    parent_by_key: dict[tuple[int, int, str], object],
) -> str | None:
    if language in _JS_FAMILY_LANGUAGES and node.type in _JS_ASSIGNED_FUNCTION_TYPES:
        assigned_name = _js_assigned_function_name(node, source, parent_by_key)
        if assigned_name is not None:
            return assigned_name

    for field_name in ("name", "property"):
        name = _name_from_node(node.child_by_field_name(field_name), source)
        if name is not None:
            return name

    declarator_name = _name_from_declarator(
        node.child_by_field_name("declarator"),
        source,
    )
    if declarator_name is not None:
        return declarator_name

    if language in _JS_FAMILY_LANGUAGES:
        assigned_name = _js_assigned_function_name(node, source, parent_by_key)
        if assigned_name is not None:
            return assigned_name

    for child in node.children:
        name = _name_from_node(child, source)
        if name is not None:
            return name

    return None


def _js_assigned_function_name(
    node,
    source: bytes,
    parent_by_key: dict[tuple[int, int, str], object],
) -> str | None:
    current = node
    while current is not None:
        parent = parent_by_key.get(_node_key(current))
        if parent is None:
            return None

        if parent.type == "variable_declarator":
            value = parent.child_by_field_name("value")
            if _same_node(value, current):
                return _name_from_node(parent.child_by_field_name("name"), source)

        if parent.type == "pair":
            value = parent.child_by_field_name("value")
            if _same_node(value, current):
                return _name_from_node(parent.child_by_field_name("key"), source)

        if parent.type in ("field_definition", "public_field_definition"):
            value = parent.child_by_field_name("value")
            if _same_node(value, current):
                return _name_from_node(
                    parent.child_by_field_name("name")
                    or parent.child_by_field_name("property"),
                    source,
                )

        if parent.type == "assignment_expression":
            right = parent.child_by_field_name("right")
            if _same_node(right, current):
                return _name_from_assignment_left(
                    parent.child_by_field_name("left"),
                    source,
                )

        current = parent
    return None


def _name_from_assignment_left(node, source: bytes) -> str | None:
    name = _name_from_node(node, source)
    if name is not None:
        return name

    if node is None:
        return None

    if node.type in ("member_expression", "subscript_expression"):
        for child in reversed(node.children):
            name = _name_from_node(child, source)
            if name is not None:
                return name
    return None


def _name_from_declarator(node, source: bytes) -> str | None:
    if node is None:
        return None

    name = _name_from_node(node, source)
    if name is not None:
        return name

    nested = node.child_by_field_name("declarator")
    name = _name_from_declarator(nested, source)
    if name is not None:
        return name

    for child in node.children:
        name = _name_from_node(child, source)
        if name is not None:
            return name

    for child in node.children:
        name = _name_from_declarator(child, source)
        if name is not None:
            return name

    return None


def _name_from_node(node, source: bytes) -> str | None:
    if node is None:
        return None

    if node.type in _IDENTIFIER_NODE_TYPES:
        return _last_name_part(node, source)

    if node.type == "computed_property_name":
        for child in node.children:
            name = _name_from_node(child, source)
            if name is not None:
                return name

    if node.type == "string":
        strings = _string_descendant_texts(node, source)
        if len(strings) == 1:
            return strings[0]

    return None


def _identifier_descendant_texts(node, source: bytes) -> list[str]:
    names: list[str] = []

    def visit(candidate) -> None:
        if candidate.type in _IDENTIFIER_NODE_TYPES:
            names.append(_last_name_part(candidate, source))
            return
        for child in candidate.children:
            visit(child)

    visit(node)
    return [name for name in names if name]


def _string_descendant_texts(node, source: bytes) -> list[str]:
    strings: list[str] = []

    def visit(candidate) -> None:
        if candidate.type in _STRING_CONTENT_NODE_TYPES:
            value = _text(candidate, source).strip()
            value = value.strip("'\"<>")
            if value:
                strings.append(value)
            return
        for child in candidate.children:
            visit(child)

    visit(node)
    return strings


def _module_basename(value: str) -> str:
    module = value.strip().strip("'\"<>")
    module = module.replace("\\", "/").rstrip("/")
    if "/" in module:
        module = module.rsplit("/", 1)[-1]
    if module.endswith((".js", ".ts", ".tsx", ".py", ".rb", ".go", ".rs")):
        module = module.rsplit(".", 1)[0]
    return module


def _parent_map(root) -> dict[tuple[int, int, str], object]:
    parents: dict[tuple[int, int, str], object] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            parents[_node_key(child)] = node
            stack.append(child)
    return parents


def _node_key(node) -> tuple[int, int, str]:
    return (node.start_byte, node.end_byte, node.type)


def _node_contains(parent, child) -> bool:
    return parent.start_byte <= child.start_byte and child.end_byte <= parent.end_byte


def _same_node(left, right) -> bool:
    if left is None or right is None:
        return False
    return _node_key(left) == _node_key(right)


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


def _extract_symbols_bootstrap(
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
        definition_kind = _bootstrap_definition_kind(language, node)
        short_name = _legacy_definition_name(node, source) if definition_kind else None

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


def _bootstrap_definition_kind(language: str, node) -> str | None:
    if language == "python" and node.type in _PYTHON_DEFINITION_TYPES:
        return "class" if node.type == "class_definition" else "function"
    if language in _JS_FAMILY_LANGUAGES and node.type in _JS_DEFINITION_TYPES:
        return "class" if node.type == "class_declaration" else "function"
    return None


def _legacy_definition_name(node, source: bytes) -> str | None:
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
    function_node = None
    if hasattr(node, "child_by_field_name"):
        for field_name in ("function", "name", "method"):
            function_node = node.child_by_field_name(field_name)
            if function_node is not None:
                break

    if function_node is None:
        named_children = [child for child in node.children if child.is_named]
        if not named_children:
            return _last_name_part(node, source)
        function_node = named_children[0]

    return _last_name_part(function_node, source)


def _last_name_part(node, source: bytes) -> str:
    text = _text(node, source).strip().strip("'\"<>")
    if not text:
        return text
    for separator in (".", "::", "/", "\\"):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    if "[" in text:
        text = text.split("[", 1)[0]
    if "(" in text:
        text = text.split("(", 1)[0]
    return text.strip().strip("'\"<>;")


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
