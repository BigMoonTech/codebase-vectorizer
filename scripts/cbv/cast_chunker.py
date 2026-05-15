"""cAST chunker - AST-aware chunking via tree-sitter.

Implements the cAST algorithm (Zhang et al., arXiv 2506.15655) referenced
in spec section "Step 4 - Chunk via cAST": a recursive split-then-merge over
the parse tree that emits non-overlapping Chunk objects. The emitted
chunks' byte ranges tile the source bytes contiguously so concat == file.

Per-language kind mapping (function / class / method / section) lives in
this module. Tree-sitter node types differ across grammars; the mapping
is a per-language function that takes (node, ancestor_list) and returns
the cbv kind string. Unknown nodes fall back to "section".

`cast_chunks()` is the entry point. It is called by chunker.py's
orchestrator only after parser.parse() returned a non-None Tree.
"""
from __future__ import annotations

import bisect
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
