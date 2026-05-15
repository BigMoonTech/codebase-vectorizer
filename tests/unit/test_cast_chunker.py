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


def test_ast_path_decorated_class_method_does_not_duplicate_class_segment():
    src = b"@deco\nclass C:\n    def foo(self):\n        pass\n"
    tree = _parse_python(src)
    deco = tree.root_node.children[0]
    assert deco.type == "decorated_definition"
    cls = next(c for c in deco.children if c.type == "class_definition")
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    parents = [tree.root_node, deco, cls, body]
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


def test_chunk_from_node_single_function():
    src = b"def add(a, b):\n    return a + b\n"
    tree = _parse_python(src)
    fn = tree.root_node.children[0]
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_node(
        fn, parents=[tree.root_node],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "function"
    assert chunk.name == "add"
    assert chunk.ast_path == "module/function[add]"
    assert chunk.file_path == "x.py"
    assert chunk.language == "python"
    assert chunk.start_line == 1
    assert chunk.end_line == 2
    assert chunk.start_byte == 0
    assert chunk.end_byte == fn.end_byte
    assert chunk.content == src[fn.start_byte:fn.end_byte].decode("utf-8")
    assert chunk.token_count == len(chunk.content.split())


def test_chunk_from_node_class_with_method_records_method():
    src = b"class C:\n    def m(self):\n        return 1\n"
    tree = _parse_python(src)
    cls = tree.root_node.children[0]
    body = cls.child_by_field_name("body")
    fn = next(c for c in body.children if c.type == "function_definition")
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_node(
        fn, parents=[tree.root_node, cls, body],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "method"
    assert chunk.name == "m"
    assert chunk.ast_path == "module/class[C]/method[m]"


def test_chunk_from_node_top_level_statement():
    src = b"x = 1\n"
    tree = _parse_python(src)
    stmt = tree.root_node.children[0]
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_node(
        stmt, parents=[tree.root_node],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "section"
    assert chunk.name is None
    assert chunk.ast_path == "module/section"
