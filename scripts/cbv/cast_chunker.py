"""cAST helper utilities for AST-aware chunking via tree-sitter.

Task 4 lays down the helper surface used by later cAST chunk construction:
byte-to-line conversion, definition name extraction, ast_path construction,
and per-language kind mapping.

Per-language kind mapping (function / class / method / section) lives in
this module. Tree-sitter node types differ across grammars; the mapping
is a per-language function that takes (node, ancestor_list) and returns
the cbv kind string. Unknown nodes fall back to "section".

The `cast_chunks()` entry point recursively splits and merges AST slots
while preserving the concat invariant.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import List, Optional, Sequence

from cbv.chunker import Chunk, _sha256_hex, _token_count


# --- byte / line helpers ---------------------------------------------------


def _line_starts(source: bytes) -> List[int]:
    """Return byte offsets where each 0-indexed line begins."""
    starts = [0]
    for i, b in enumerate(source):
        if b == 0x0A:
            starts.append(i + 1)
    return starts


def _byte_to_line(line_starts: Sequence[int], byte_offset: int) -> int:
    """Convert a byte offset into a 1-indexed line number."""
    idx = bisect.bisect_right(line_starts, byte_offset)
    return max(1, idx)


# --- name + ast_path extraction --------------------------------------------


_PYTHON_DEFINITION_TYPES = frozenset(
    ("function_definition", "async_function_definition", "class_definition")
)


def _unwrap_python_decorated_definition(node):
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in _PYTHON_DEFINITION_TYPES:
                return child
    return node


def _extract_name(node, source: bytes) -> Optional[str]:
    """Return the identifier name for a definition node, or None."""
    node = _unwrap_python_decorated_definition(node)
    if node.type not in NAMEABLE_NODE_TYPES:
        return None

    name_node = (
        node.child_by_field_name("name")
        if hasattr(node, "child_by_field_name")
        else None
    )
    if name_node is None:
        return None

    try:
        return source[name_node.start_byte:name_node.end_byte].decode(
            "utf-8",
            errors="replace",
        )
    except Exception:
        return None


_JAVASCRIPT_FAMILY_LANGUAGES = frozenset(("javascript", "typescript", "tsx"))
_JAVASCRIPT_NAME_NODE_TYPES = frozenset(
    ("identifier", "private_property_identifier", "property_identifier")
)
_C_CPP_LANGUAGES = frozenset(("c", "cpp"))
_C_CPP_NAME_NODE_TYPES = frozenset(
    (
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
    )
)


def _same_node(left, right) -> bool:
    if left is None or right is None:
        return False
    return (
        left.type == right.type
        and left.start_byte == right.start_byte
        and left.end_byte == right.end_byte
    )


def _extract_identifier_text(node, source: bytes) -> Optional[str]:
    if node is None or node.type not in _JAVASCRIPT_NAME_NODE_TYPES:
        return None
    try:
        return source[node.start_byte:node.end_byte].decode(
            "utf-8",
            errors="replace",
        )
    except Exception:
        return None


def _extract_c_cpp_identifier_text(node, source: bytes) -> Optional[str]:
    if node is None or node.type not in _C_CPP_NAME_NODE_TYPES:
        return None
    try:
        return source[node.start_byte:node.end_byte].decode(
            "utf-8",
            errors="replace",
        )
    except Exception:
        return None


def _extract_c_cpp_declarator_identifier(declarator, source: bytes) -> Optional[str]:
    name = _extract_c_cpp_identifier_text(declarator, source)
    if name is not None:
        return name

    nested = declarator.child_by_field_name("declarator") if declarator else None
    if nested is not None:
        name = _extract_c_cpp_declarator_identifier(nested, source)
        if name is not None:
            return name

    if declarator is None:
        return None

    for child in declarator.children:
        if child.is_named:
            name = _extract_c_cpp_identifier_text(child, source)
            if name is not None:
                return name

    for child in declarator.children:
        if child.is_named:
            name = _extract_c_cpp_declarator_identifier(child, source)
            if name is not None:
                return name

    return None


def _extract_c_cpp_function_name(node, source: bytes) -> Optional[str]:
    if node.type != "function_definition":
        return None
    return _extract_c_cpp_declarator_identifier(
        node.child_by_field_name("declarator"),
        source,
    )


def _direct_function_value_matches(value_node, function_node) -> bool:
    if _same_node(value_node, function_node):
        return True

    current = value_node
    while current is not None and current.type == "parenthesized_expression":
        named_children = [
            child
            for child in current.children
            if child.is_named and child.type != "comment"
        ]
        if len(named_children) != 1:
            return False
        child = named_children[0]
        if _same_node(child, function_node):
            return True
        current = child

    return False


def _extract_js_assignment_left_name(left_node, source: bytes) -> Optional[str]:
    if left_node is None:
        return None

    direct_name = _extract_identifier_text(left_node, source)
    if direct_name is not None:
        return direct_name

    if left_node.type == "member_expression":
        property_node = left_node.child_by_field_name("property")
        property_name = _extract_identifier_text(property_node, source)
        if property_name is not None:
            return property_name

        for child in reversed(left_node.children):
            child_name = _extract_identifier_text(child, source)
            if child_name is not None:
                return child_name

    return None


def _extract_js_assigned_function_name(node, parents, source: bytes) -> Optional[str]:
    for parent in reversed(parents):
        if parent.type == "variable_declarator":
            value = parent.child_by_field_name("value")
            if _direct_function_value_matches(value, node):
                return _extract_identifier_text(
                    parent.child_by_field_name("name"),
                    source,
                )

        if parent.type == "pair":
            value = parent.child_by_field_name("value")
            if _direct_function_value_matches(value, node):
                return _extract_identifier_text(
                    parent.child_by_field_name("key"),
                    source,
                )

        if parent.type in ("field_definition", "public_field_definition"):
            value = parent.child_by_field_name("value")
            if _direct_function_value_matches(value, node):
                return _extract_identifier_text(
                    parent.child_by_field_name("name")
                    or parent.child_by_field_name("property"),
                    source,
                )

        if parent.type == "assignment_expression":
            right = parent.child_by_field_name("right")
            if _direct_function_value_matches(right, node):
                return _extract_js_assignment_left_name(
                    parent.child_by_field_name("left"),
                    source,
                )

    return None


def _extract_name_with_parents(
    language: str,
    node,
    parents,
    source: bytes,
) -> Optional[str]:
    direct_name = _extract_name(node, source)
    if direct_name is not None:
        return direct_name
    if language in _C_CPP_LANGUAGES:
        return _extract_c_cpp_function_name(node, source)
    if language in _JAVASCRIPT_FAMILY_LANGUAGES:
        return _extract_js_assigned_function_name(node, parents, source)
    return None


# --- per-language kind mapping ---------------------------------------------


FUNCTION_NODE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset(("function_definition", "async_function_definition")),
    "javascript": frozenset(
        (
            "function",
            "function_declaration",
            "function_expression",
            "arrow_function",
            "generator_function",
            "generator_function_declaration",
            "method_definition",
        )
    ),
    "typescript": frozenset(
        (
            "function",
            "function_declaration",
            "function_expression",
            "arrow_function",
            "generator_function",
            "generator_function_declaration",
            "method_definition",
            "method_signature",
            "function_signature",
            "abstract_method_signature",
        )
    ),
    "tsx": frozenset(
        (
            "function",
            "function_declaration",
            "function_expression",
            "arrow_function",
            "generator_function",
            "generator_function_declaration",
            "method_definition",
            "method_signature",
            "function_signature",
            "abstract_method_signature",
        )
    ),
    "go": frozenset(("function_declaration", "method_declaration")),
    "rust": frozenset(("function_item",)),
    "java": frozenset(("method_declaration", "constructor_declaration")),
    "c": frozenset(("function_definition",)),
    "cpp": frozenset(("function_definition",)),
    "ruby": frozenset(("method", "singleton_method")),
    "csharp": frozenset(("method_declaration", "constructor_declaration")),
}


CLASS_NODE_TYPES: dict[str, frozenset[str]] = {
    "python": frozenset(("class_definition",)),
    "javascript": frozenset(("class", "class_declaration")),
    "typescript": frozenset(("class", "class_declaration", "interface_declaration")),
    "tsx": frozenset(("class", "class_declaration", "interface_declaration")),
    "go": frozenset(),
    "rust": frozenset(("enum_item", "impl_item", "struct_item", "trait_item")),
    "java": frozenset(
        (
            "class_declaration",
            "enum_declaration",
            "interface_declaration",
            "record_declaration",
        )
    ),
    "c": frozenset(("struct_specifier",)),
    "cpp": frozenset(("class_specifier", "struct_specifier")),
    "ruby": frozenset(("class", "module")),
    "csharp": frozenset(
        (
            "class_declaration",
            "enum_declaration",
            "interface_declaration",
            "record_declaration",
            "struct_declaration",
        )
    ),
}


METHOD_NODE_TYPES: dict[str, frozenset[str]] = {
    "csharp": frozenset(("local_function_statement",)),
    "go": frozenset(("method_declaration",)),
}


NAMEABLE_NODE_TYPES = frozenset(
    node_type
    for language_types in (
        *FUNCTION_NODE_TYPES.values(),
        *CLASS_NODE_TYPES.values(),
        *METHOD_NODE_TYPES.values(),
    )
    for node_type in language_types
)


KIND_MAPS: dict[str, tuple[frozenset[str], frozenset[str], frozenset[str]]] = {}
for _language in (
    FUNCTION_NODE_TYPES.keys() | CLASS_NODE_TYPES.keys() | METHOD_NODE_TYPES.keys()
):
    KIND_MAPS[_language] = (
        FUNCTION_NODE_TYPES.get(_language, frozenset()),
        CLASS_NODE_TYPES.get(_language, frozenset()),
        METHOD_NODE_TYPES.get(_language, frozenset()),
    )


def _kind_for_node(language: str, node, parents) -> str:
    node = _unwrap_python_decorated_definition(node)
    maps = KIND_MAPS.get(language)
    if maps is None:
        return "section"

    function_types, class_types, method_types = maps
    if node.type in method_types:
        return "method"

    if node.type in class_types:
        return "class"

    if node.type in function_types:
        if any(
            _unwrap_python_decorated_definition(parent).type in class_types
            for parent in parents
        ):
            return "method"
        return "function"

    return "section"


LABELLED_KINDS = frozenset(("function", "class", "method"))


def _semantic_representative(language: str, node, parents):
    """Return a mapped node to represent this range when there is a clear one."""
    if _kind_for_node(language, node, parents) in LABELLED_KINDS:
        return node, parents

    matches = []

    def visit(candidate, candidate_parents) -> None:
        if _kind_for_node(language, candidate, candidate_parents) in LABELLED_KINDS:
            matches.append((candidate, candidate_parents))
            return
        for child in candidate.children:
            if child.end_byte > child.start_byte:
                visit(child, candidate_parents + [candidate])

    for child in node.children:
        if child.end_byte > child.start_byte:
            visit(child, parents + [node])

    if len(matches) == 1:
        return matches[0]
    return node, parents


def _slot_for_node(node, parents, language_name: str) -> "_Slot":
    representative_node, representative_parents = _semantic_representative(
        language_name,
        node,
        list(parents),
    )
    return _Slot(
        node.start_byte,
        node.end_byte,
        representative_node,
        list(representative_parents),
    )


def _inner_decorated_definition(node):
    if node is None:
        return None
    if node.type != "decorated_definition":
        return None
    for child in node.children:
        if child.type in _PYTHON_DEFINITION_TYPES:
            return child
    return None


def _ast_path(language: str, node, parents, source: bytes) -> str:
    """Build a path like 'module/class[Foo]/method[bar]'."""
    parts: list[str] = ["module"]
    labelled = {"function", "class", "method"}
    previous_labelled_parent = None

    for i, parent in enumerate(parents[1:], start=1):
        kind = _kind_for_node(language, parent, parents[:i])
        if kind in labelled:
            name = (
                _extract_name_with_parents(language, parent, parents[:i], source)
                or "?"
            )
            segment = f"{kind}[{name}]"
            if (
                _inner_decorated_definition(previous_labelled_parent) == parent
                and parts[-1] == segment
            ):
                previous_labelled_parent = parent
                continue
            parts.append(segment)
            previous_labelled_parent = parent

    terminal_kind = _kind_for_node(language, node, parents)
    if terminal_kind in labelled:
        name = _extract_name_with_parents(language, node, parents, source) or "?"
        segment = f"{terminal_kind}[{name}]"
        if not (
            _inner_decorated_definition(previous_labelled_parent) == node
            and parts[-1] == segment
        ):
            parts.append(segment)
    else:
        parts.append("section")

    return "/".join(parts)


# --- chunk construction -----------------------------------------------------


def _chunk_from_node(
    node,
    parents,
    *,
    language_name: str,
    file_path: str,
    source: bytes,
    line_starts: Sequence[int],
) -> Chunk:
    """Build a Chunk from a single AST node."""
    return _chunk_from_byte_range(
        node.start_byte,
        node.end_byte,
        node=node,
        parents=parents,
        language_name=language_name,
        file_path=file_path,
        source=source,
        line_starts=line_starts,
    )


def _ast_path_for_parent_section(language: str, parents, source: bytes) -> str:
    parts: list[str] = ["module"]
    labelled = {"function", "class", "method"}
    previous_labelled_parent = None

    for i, parent in enumerate(parents[1:], start=1):
        kind = _kind_for_node(language, parent, parents[:i])
        if kind not in labelled:
            continue
        name = (
            _extract_name_with_parents(language, parent, parents[:i], source)
            or "?"
        )
        segment = f"{kind}[{name}]"
        if (
            _inner_decorated_definition(previous_labelled_parent) == parent
            and parts[-1] == segment
        ):
            previous_labelled_parent = parent
            continue
        parts.append(segment)
        previous_labelled_parent = parent

    parts.append("section")
    return "/".join(parts)


def _chunk_from_byte_range(
    start_byte: int,
    end_byte: int,
    *,
    node,
    parents,
    language_name: str,
    file_path: str,
    source: bytes,
    line_starts: Sequence[int],
) -> Chunk:
    """Build a Chunk for a byte range, optionally aligned to one AST node."""
    text = source[start_byte:end_byte].decode("utf-8", errors="replace")

    if node is None:
        kind = "section"
        name = None
        ast_path = _ast_path_for_parent_section(language_name, parents, source)
    else:
        kind = _kind_for_node(language_name, node, parents)
        name = _extract_name_with_parents(language_name, node, parents, source)
        ast_path = _ast_path(language_name, node, parents, source)

    return Chunk(
        file_path=file_path,
        language=language_name,
        kind=kind,
        name=name,
        ast_path=ast_path,
        start_line=_byte_to_line(line_starts, start_byte),
        end_line=_byte_to_line(line_starts, max(end_byte - 1, start_byte)),
        start_byte=start_byte,
        end_byte=end_byte,
        content=text,
        content_hash=_sha256_hex(text),
        token_count=_token_count(text),
    )


@dataclass
class _Slot:
    """Mutable intermediate cAST slot.

    Tracks the byte range plus the representative node, or None when this
    slot represents a merged sibling group. Slots are converted to Chunk
    objects at the end of cast_chunks().
    """
    start_byte: int
    end_byte: int
    node: Optional[object]
    parents: List[object]


def cast_chunks(
    tree,
    source: bytes,
    *,
    language_name: str,
    file_path: str,
    budget_bytes: int = 1500,
) -> List[Chunk]:
    """Apply cAST and return Chunks that tile [0, len(source)).

    The root node is structural, so its children are chunked with the root
    as parent context. Every other node is emitted whole when it fits the
    budget, recursively split when it does not, and then greedily merged with
    adjacent slots when the merged byte range fits.
    """
    if not source:
        return []

    root = tree.root_node
    slots = _cast_root(
        root,
        source=source,
        budget=budget_bytes,
        language_name=language_name,
    )
    if not slots:
        return []

    slots[0].start_byte = 0
    slots[-1].end_byte = len(source)

    line_starts = _line_starts(source)
    return [
        _chunk_from_byte_range(
            s.start_byte,
            s.end_byte,
            node=s.node,
            parents=s.parents,
            language_name=language_name,
            file_path=file_path,
            source=source,
            line_starts=line_starts,
        )
        for s in slots
    ]


def _cast_root(root, *, source: bytes, budget: int, language_name: str) -> List[_Slot]:
    """Split/merge the root's children while using root as parent context."""
    children = [c for c in root.children if c.end_byte > c.start_byte]
    if not children:
        return _cast(
            root,
            parents=[],
            source=source,
            budget=budget,
            language_name=language_name,
        )

    out: List[_Slot] = []
    parents = [root]
    for child in children:
        if child.end_byte - child.start_byte > budget:
            out.extend(
                _cast(
                    child,
                    parents=parents,
                    source=source,
                    budget=budget,
                    language_name=language_name,
                )
            )
        else:
            out.append(_slot_for_node(child, parents, language_name))

    tiled = _slots_with_explicit_gaps(
        out,
        0,
        len(source),
        parents,
        budget,
    )
    merged = _greedy_merge_slots(tiled, budget, language_name)
    _tile_slots_to_range(merged, 0, len(source))
    return merged


def _cast(node, *, parents, source: bytes, budget: int, language_name: str) -> List[_Slot]:
    """Recursive split-then-merge for one non-root node."""
    size = node.end_byte - node.start_byte
    if size <= budget:
        return [_slot_for_node(node, parents, language_name)]

    children = [c for c in node.children if c.end_byte > c.start_byte]
    if not children:
        return [_slot_for_node(node, parents, language_name)]

    next_parents = list(parents) + [node]
    out: List[_Slot] = []
    for child in children:
        if child.end_byte - child.start_byte > budget:
            out.extend(
                _cast(
                    child,
                    parents=next_parents,
                    source=source,
                    budget=budget,
                    language_name=language_name,
                )
            )
        else:
            out.append(_slot_for_node(child, next_parents, language_name))

    tiled = _slots_with_explicit_gaps(
        out,
        node.start_byte,
        node.end_byte,
        next_parents,
        budget,
    )
    merged = _greedy_merge_slots(tiled, budget, language_name)
    _tile_slots_to_range(merged, node.start_byte, node.end_byte)
    return merged


def _slots_with_explicit_gaps(
    slots: List[_Slot],
    start_byte: int,
    end_byte: int,
    parents,
    budget: int,
) -> List[_Slot]:
    """Return slots plus explicit section slots for byte gaps between them."""
    out: List[_Slot] = []
    cursor = start_byte
    previous_slot: Optional[_Slot] = None

    for slot in slots:
        if slot.start_byte > cursor:
            gap_parents = (
                _common_parent_stack(previous_slot.parents, slot.parents)
                if previous_slot is not None
                else list(parents)
            )
            out.extend(_split_gap_slots(cursor, slot.start_byte, gap_parents, budget))

        out.append(slot)
        cursor = max(cursor, slot.end_byte)
        previous_slot = slot

    if cursor < end_byte:
        out.extend(_split_gap_slots(cursor, end_byte, list(parents), budget))

    return out


def _split_gap_slots(
    start_byte: int,
    end_byte: int,
    parents,
    budget: int,
) -> List[_Slot]:
    if end_byte <= start_byte:
        return []

    if budget <= 0:
        return [_Slot(start_byte, end_byte, None, list(parents))]

    out: List[_Slot] = []
    cursor = start_byte
    while cursor < end_byte:
        next_cursor = min(end_byte, cursor + budget)
        out.append(_Slot(cursor, next_cursor, None, list(parents)))
        cursor = next_cursor
    return out


def _greedy_merge_slots(slots: List[_Slot], budget: int, language_name: str) -> List[_Slot]:
    """Merge consecutive slots while the combined byte range fits budget."""
    out: List[_Slot] = []
    current: Optional[_Slot] = None

    for slot in slots:
        if current is None:
            current = _Slot(
                slot.start_byte,
                slot.end_byte,
                slot.node,
                list(slot.parents),
            )
            continue

        if _should_merge_slots(current, slot, budget, language_name):
            node, parents = _merged_representative(current, slot, language_name)
            current.end_byte = slot.end_byte
            current.node = node
            current.parents = parents
        else:
            out.append(current)
            current = _Slot(
                slot.start_byte,
                slot.end_byte,
                slot.node,
                list(slot.parents),
            )

    if current is not None:
        out.append(current)
    return out


def _should_merge_slots(
    left: _Slot,
    right: _Slot,
    budget: int,
    language_name: str,
) -> bool:
    left_kind = _slot_semantic_kind(left, language_name)
    right_kind = _slot_semantic_kind(right, language_name)
    if right.end_byte - left.start_byte > budget:
        if (
            not left_kind
            and not right_kind
            and (
                (
                    left.end_byte - left.start_byte > budget
                    and right.end_byte - right.start_byte < budget
                )
                or (
                    right.end_byte - right.start_byte > budget
                    and left.end_byte - left.start_byte < budget
                )
            )
        ):
            return True
        return False
    if left_kind and right_kind:
        return False
    return True


def _slot_semantic_kind(slot: _Slot, language_name: str) -> Optional[str]:
    if slot.node is None:
        return None
    kind = _kind_for_node(language_name, slot.node, slot.parents)
    if kind in LABELLED_KINDS:
        return kind
    return None


def _merged_representative(left: _Slot, right: _Slot, language_name: str):
    left_kind = _slot_semantic_kind(left, language_name)
    right_kind = _slot_semantic_kind(right, language_name)

    if left_kind and not right_kind:
        return left.node, list(left.parents)
    if right_kind and not left_kind:
        return right.node, list(right.parents)
    return None, _common_parent_stack(left.parents, right.parents)


def _common_parent_stack(left, right) -> List[object]:
    """Return the shared ancestor prefix for two parent stacks."""
    common: List[object] = []
    for left_parent, right_parent in zip(left, right):
        if left_parent != right_parent:
            break
        common.append(left_parent)
    return common


def _tile_slots_to_range(slots: List[_Slot], start_byte: int, end_byte: int) -> None:
    """Mutate slots so adjacent ranges exactly cover the parent range."""
    if not slots:
        return
    slots[0].start_byte = start_byte
    for left, right in zip(slots, slots[1:]):
        left.end_byte = right.start_byte
    slots[-1].end_byte = end_byte
