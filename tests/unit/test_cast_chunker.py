"""Tests for cbv.cast_chunker - kind mapping, name extraction, ast_path,
byte_to_line. The full cast_chunks() algorithm is tested in subsequent tasks."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cbv.cast_chunker as cast_chunker  # noqa: E402
from cbv import parser  # noqa: E402


def _parse_python(src: bytes):
    return parser.parse(src, parser.LANGUAGES["python"])


def test_byte_to_line_simple():
    src = b"a\nbb\nccc\n"
    line_starts = cast_chunker._line_starts(src)
    # line_starts = [0, 2, 5, 9]
    assert cast_chunker._byte_to_line(line_starts, 0) == 1
    assert cast_chunker._byte_to_line(line_starts, 1) == 1
    assert cast_chunker._byte_to_line(line_starts, 2) == 2
    assert cast_chunker._byte_to_line(line_starts, 4) == 2
    assert cast_chunker._byte_to_line(line_starts, 5) == 3
    assert cast_chunker._byte_to_line(line_starts, 8) == 3


def test_byte_to_line_no_trailing_newline():
    src = b"abc"
    line_starts = cast_chunker._line_starts(src)
    assert cast_chunker._byte_to_line(line_starts, 0) == 1
    assert cast_chunker._byte_to_line(line_starts, 2) == 1


def test_python_kind_function_at_top_level():
    src = b"def foo():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    assert fn.type == "function_definition"
    assert cast_chunker._kind_for_node("python", fn, parents=[tree.root_node]) == "function"


def test_python_kind_method_inside_class():
    src = b"class C:\n    def foo(self):\n        pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    assert cls.type == "class_definition"
    # Find the function_definition inside the class body
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    parents = [tree.root_node, cls, body]
    assert cast_chunker._kind_for_node("python", fn, parents=parents) == "method"


def test_python_kind_class():
    src = b"class C:\n    pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    assert cast_chunker._kind_for_node("python", cls, parents=[tree.root_node]) == "class"


def test_python_kind_async_function():
    src = b"async def foo():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    # tree-sitter-python may name this 'function_definition' or
    # 'async_function_definition' depending on grammar version; either
    # one must resolve to "function".
    parents = [tree.root_node]
    kind = cast_chunker._kind_for_node("python", fn, parents=parents)
    assert kind == "function", f"got {kind!r} for node type {fn.type!r}"


def test_python_kind_decorated_function():
    src = b"@deco\ndef foo():\n    pass\n"
    tree = _parse_python(src)
    deco = tree.root_node.children[0]
    # tree-sitter-python wraps decorated functions in 'decorated_definition'
    assert deco.type == "decorated_definition"
    assert cast_chunker._kind_for_node("python", deco, parents=[tree.root_node]) == "function"


def test_python_kind_falls_back_to_section():
    src = b"import os\n"
    tree = _parse_python(src)
    imp = tree.root_node.children[0]
    assert imp.type == "import_statement"
    assert cast_chunker._kind_for_node("python", imp, parents=[tree.root_node]) == "section"


def test_extract_name_function():
    src = b"def foo_bar():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    assert cast_chunker._extract_name(fn, src) == "foo_bar"


def test_extract_name_class():
    src = b"class MyClass:\n    pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    assert cast_chunker._extract_name(cls, src) == "MyClass"


def test_extract_name_decorated_definition():
    src = b"@deco\ndef wrapped():\n    pass\n"
    tree = _parse_python(src)
    deco = tree.root_node.children[0]
    assert cast_chunker._extract_name(deco, src) == "wrapped"


def test_extract_name_no_name_node_returns_none():
    src = b"import os\n"
    tree = _parse_python(src)
    imp = tree.root_node.children[0]
    assert cast_chunker._extract_name(imp, src) is None


def test_ast_path_top_level_function():
    src = b"def foo():\n    pass\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    # Path includes only nodes that have a name; top-level fn under module
    assert cast_chunker._ast_path("python", fn, [tree.root_node], src) == "module/function[foo]"


def test_ast_path_method():
    src = b"class C:\n    def foo(self):\n        pass\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    parents = [tree.root_node, cls, body]
    assert (
        cast_chunker._ast_path("python", fn, parents, src)
        == "module/class[C]/method[foo]"
    )


def test_ast_path_module_only_for_root_children():
    """Top-level statements (not class/function) get the module prefix only."""
    src = b"x = 1\n"
    tree = _parse_python(src)
    stmt = tree.root_node.children[0]
    assert cast_chunker._ast_path("python", stmt, [tree.root_node], src) == "module/section"
