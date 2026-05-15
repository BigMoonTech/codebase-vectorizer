"""cAST helper utilities for AST-aware chunking via tree-sitter.

Task 4 lays down the helper surface used by later cAST chunk construction:
byte-to-line conversion, definition name extraction, ast_path construction,
and per-language kind mapping for Python nodes.

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
from typing import Callable, List, Optional, Sequence

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


def _extract_name(node, source: bytes) -> Optional[str]:
    """Return the identifier name for a definition node, or None."""
    if node.type == "decorated_definition":
        for child in node.children:
            if child.type in (
                "function_definition",
                "async_function_definition",
                "class_definition",
            ):
                node = child
                break

    if node.type not in (
        "function_definition",
        "async_function_definition",
        "class_definition",
    ):
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


# --- per-language kind mapping ---------------------------------------------


def _python_kind(node, parents) -> str:
    """Map a Python tree-sitter node to a Chunk.kind."""
    real_type = node.type
    if real_type == "decorated_definition":
        for child in node.children:
            if child.type in (
                "function_definition",
                "async_function_definition",
                "class_definition",
            ):
                real_type = child.type
                break

    if real_type in ("function_definition", "async_function_definition"):
        for parent in parents:
            if parent.type == "class_definition":
                return "method"
        return "function"

    if real_type == "class_definition":
        return "class"

    return "section"


KIND_MAPS: dict[str, Callable] = {
    "python": _python_kind,
}


def _kind_for_node(language: str, node, parents) -> str:
    fn = KIND_MAPS.get(language)
    if fn is None:
        return "section"
    return fn(node, parents)


def _inner_decorated_definition(node):
    if node is None:
        return None
    if node.type != "decorated_definition":
        return None
    for child in node.children:
        if child.type in (
            "function_definition",
            "async_function_definition",
            "class_definition",
        ):
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
            name = _extract_name(parent, source) or "?"
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
        name = _extract_name(node, source) or "?"
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
        name = _extract_name(parent, source) or "?"
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
        name = _extract_name(node, source)
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
    node: object
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
            out.append(_Slot(child.start_byte, child.end_byte, child, list(parents)))

    merged = _greedy_merge_slots(out, budget)
    _tile_slots_to_range(merged, root.start_byte, root.end_byte)
    return merged


def _cast(node, *, parents, source: bytes, budget: int, language_name: str) -> List[_Slot]:
    """Recursive split-then-merge for one non-root node."""
    size = node.end_byte - node.start_byte
    if size <= budget:
        return [_Slot(node.start_byte, node.end_byte, node, list(parents))]

    children = [c for c in node.children if c.end_byte > c.start_byte]
    if not children:
        return [_Slot(node.start_byte, node.end_byte, node, list(parents))]

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
            out.append(_Slot(child.start_byte, child.end_byte, child, list(next_parents)))

    merged = _greedy_merge_slots(out, budget)
    _tile_slots_to_range(merged, node.start_byte, node.end_byte)
    return merged


def _greedy_merge_slots(slots: List[_Slot], budget: int) -> List[_Slot]:
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

        if slot.end_byte - current.start_byte <= budget:
            current.end_byte = slot.end_byte
            current.node = None
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


def _tile_slots_to_range(slots: List[_Slot], start_byte: int, end_byte: int) -> None:
    """Mutate slots so adjacent ranges exactly cover the parent range."""
    if not slots:
        return
    slots[0].start_byte = start_byte
    for left, right in zip(slots, slots[1:]):
        left.end_byte = right.start_byte
    slots[-1].end_byte = end_byte
