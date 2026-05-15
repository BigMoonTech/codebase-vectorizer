"""Tests for cbv.cast_chunker - kind mapping, name extraction, ast_path,
byte_to_line. The full cast_chunks() algorithm is tested in subsequent tasks."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cbv.cast_chunker as cast_chunker  # noqa: E402
from cbv import parser  # noqa: E402


def _parse_python(src: bytes):
    return parser.parse(src, parser.LANGUAGES["python"])


def _parse_language(language_name: str, src: bytes):
    return parser.parse(src, parser.LANGUAGES[language_name])


def _find_first_node_with_parents(root, node_type: str):
    stack = [(root, [])]
    while stack:
        node, parents = stack.pop()
        if node.type == node_type:
            return node, parents
        for child in reversed(node.children):
            stack.append((child, parents + [node]))
    raise AssertionError(f"could not find node type {node_type!r}")


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


def test_chunk_from_byte_range_node_none_emits_section_with_content_hash():
    src = b"import os\nx = 1\n"
    tree = _parse_python(src)
    line_starts = cast_chunker._line_starts(src)
    chunk = cast_chunker._chunk_from_byte_range(
        0, len(src),
        node=None, parents=[tree.root_node],
        language_name="python", file_path="x.py",
        source=src, line_starts=line_starts,
    )
    assert chunk.kind == "section"
    assert chunk.name is None
    assert chunk.ast_path == "module/section"
    assert chunk.content == src.decode("utf-8")
    assert chunk.content_hash == cast_chunker._sha256_hex(chunk.content)


def test_cast_chunks_concat_invariant_tiny_file():
    src = b"def foo():\n    pass\n"
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src


def test_cast_chunks_concat_invariant_multiple_functions():
    src = (
        b"def a():\n    return 1\n"
        b"def b():\n    return 2\n"
        b"def c():\n    return 3\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src


def test_cast_chunks_multiple_functions_do_not_merge_into_section():
    src = (
        b'"""Authentication helpers."""\n'
        b"import hashlib\n"
        b"\n"
        b"def authenticate_user(username, password):\n"
        b"    digest = hashlib.sha256(password.encode()).hexdigest()\n"
        b"    return username == 'admin' and digest\n"
        b"\n"
        b"def issue_token(username):\n"
        b"    return f'token:{username}'\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="auth.py", budget_bytes=1500,
    )

    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    assert any(
        chunk.kind == "function" and chunk.name == "authenticate_user"
        for chunk in chunks
    ), chunks
    assert not all(chunk.kind == "section" for chunk in chunks)


def test_cast_chunks_concat_invariant_contiguous_byte_ranges():
    """Chunk byte ranges must tile [0, len(source)) contiguously."""
    src = (
        b"import os\n"
        b"\n"
        b"def foo():\n    return 1\n"
        b"\n"
        b"def bar():\n    return 2\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert chunks, "expected at least one chunk"
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(src)
    for a, b in zip(chunks, chunks[1:]):
        assert a.end_byte == b.start_byte, \
            f"gap between {a.end_byte} and {b.start_byte}"


def test_cast_chunks_hidden_trivia_gap_does_not_blow_semantic_budget():
    src = (
        b"def a():\n    return 1\n"
        + (b"\n" * 5000)
        + b"def b():\n    return 2\n"
    )

    chunks = cast_chunker.cast_chunks(
        _parse_python(src),
        src,
        language_name="python",
        file_path="x.py",
        budget_bytes=1500,
    )

    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(src)
    for left, right in zip(chunks, chunks[1:]):
        assert left.end_byte == right.start_byte

    assert any(
        chunk.kind == "section" and chunk.content.strip() == ""
        for chunk in chunks
    ), chunks
    assert all(
        len(chunk.content.encode("utf-8")) <= 1500
        for chunk in chunks
        if chunk.kind != "section"
    )
    assert any(chunk.kind == "function" and chunk.name == "a" for chunk in chunks)
    assert any(chunk.kind == "function" and chunk.name == "b" for chunk in chunks)


def test_cast_chunks_leading_root_trivia_does_not_blow_semantic_budget():
    src = (b"\n" * 3000) + b"def a():\n    return 1\n"

    chunks = cast_chunker.cast_chunks(
        _parse_python(src),
        src,
        language_name="python",
        file_path="x.py",
        budget_bytes=1500,
    )

    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(src)
    for left, right in zip(chunks, chunks[1:]):
        assert left.end_byte == right.start_byte

    assert chunks[0].kind == "section"
    assert chunks[0].content.strip() == ""
    function_chunks = [
        chunk
        for chunk in chunks
        if chunk.kind == "function" and chunk.name == "a"
    ]
    assert function_chunks, chunks
    for chunk in function_chunks:
        assert len(chunk.content.encode("utf-8")) <= 1500
        assert chunk.start_byte != 0


def test_cast_chunks_trailing_root_trivia_does_not_blow_semantic_budget():
    src = b"def a():\n    return 1\n" + (b"\n" * 3000)

    chunks = cast_chunker.cast_chunks(
        _parse_python(src),
        src,
        language_name="python",
        file_path="x.py",
        budget_bytes=1500,
    )

    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    assert chunks[0].start_byte == 0
    assert chunks[-1].end_byte == len(src)
    for left, right in zip(chunks, chunks[1:]):
        assert left.end_byte == right.start_byte

    assert chunks[-1].kind == "section"
    assert chunks[-1].content.strip() == ""
    function_chunks = [
        chunk
        for chunk in chunks
        if chunk.kind == "function" and chunk.name == "a"
    ]
    assert function_chunks, chunks
    for chunk in function_chunks:
        assert len(chunk.content.encode("utf-8")) <= 1500
        assert chunk.end_byte != len(src)


def test_cast_chunks_single_function_under_budget_is_one_chunk():
    src = b"def foo():\n    return 42\n"
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert len(chunks) == 1
    assert chunks[0].kind == "function"
    assert chunks[0].name == "foo"


def test_cast_chunks_splits_when_over_budget():
    """A class containing several methods, each under budget but together
    exceeding it, should split into multiple chunks."""
    src = (
        b"class C:\n"
        b"    def aaa(self):\n        return 'aaaaa'\n"
        b"    def bbb(self):\n        return 'bbbbb'\n"
        b"    def ccc(self):\n        return 'ccccc'\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=60,
    )
    assert len(chunks) > 1
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    # At least one chunk should be a method.
    assert any(c.kind == "method" for c in chunks)


def test_cast_chunks_oversized_leaf_emits_overbudget_chunk():
    """A single deeply-leaf node bigger than budget still emits as one
    chunk (no further split possible)."""
    src = b"x = '" + (b"X" * 5000) + b"'\n"
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=100,
    )
    # Concat still holds; some chunk(s) are over-budget.
    assert b"".join(c.content.encode("utf-8") for c in chunks) == src
    assert max(len(c.content.encode("utf-8")) for c in chunks) > 100


def test_cast_chunks_empty_source_returns_no_chunks():
    src = b""
    tree = _parse_python(src)
    chunks = cast_chunker.cast_chunks(
        tree, src,
        language_name="python", file_path="x.py", budget_bytes=1500,
    )
    assert chunks == []


def test_cast_chunks_method_chunk_has_method_path():
    """A chunk emitted for a method-sized class should preserve ast_path."""
    src = (
        b"class Big:\n"
        b"    def first(self):\n        " + b"x = 1\n        " * 60 + b"\n"
        b"    def second(self):\n        return 2\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=80,
    )
    paths = [c.ast_path for c in chunks]
    # At least one chunk should be inside class Big (its ast_path contains 'class[Big]').
    assert any("class[Big]" in p for p in paths), f"paths: {paths}"


def test_cast_chunks_cross_method_merge_uses_class_section_path():
    src = (
        b"class C:\n"
        b"    def m1():\n"
        b"        a = 1\n"
        b"        a = 1\n"
        b"        a = 1\n"
        b"    def m2():\n"
        b"        x = 1\n"
        b"        y = 2\n"
    )
    chunks = cast_chunker.cast_chunks(
        _parse_python(src), src,
        language_name="python", file_path="x.py", budget_bytes=32,
    )

    cross_method_chunks = [
        c for c in chunks
        if "def m2" in c.content and c.ast_path != "module/class[C]/method[m2]"
    ]
    assert cross_method_chunks, f"expected a cross-method merged chunk: {chunks}"
    for chunk in cross_method_chunks:
        assert chunk.ast_path == "module/class[C]/section"


@pytest.mark.parametrize(
    ("language_name", "source", "expected_text", "expected_kind", "expected_name"),
    [
        (
            "javascript",
            b"function add(a, b) { return a + b; }\n",
            "function add",
            "function",
            "add",
        ),
        (
            "javascript",
            b"class Widget { render() { return 1; } }\n",
            "class Widget",
            "class",
            "Widget",
        ),
        (
            "typescript",
            b"function add(a: number): number { return a; }\n",
            "function add",
            "function",
            "add",
        ),
        (
            "tsx",
            b"function Component() { return <div />; }\n",
            "function Component",
            "function",
            "Component",
        ),
        (
            "go",
            b"package main\nfunc add(a int) int { return a }\n",
            "func add",
            "function",
            "add",
        ),
        (
            "rust",
            b"fn add(a: i32) -> i32 { a }\n",
            "fn add",
            "function",
            "add",
        ),
        (
            "java",
            b"class Widget { int value() { return 1; } }\n",
            "class Widget",
            "class",
            "Widget",
        ),
        (
            "c",
            b"int add(int a) { return a; }\n",
            "int add",
            "function",
            None,
        ),
        (
            "cpp",
            b"int add(int a) { return a; }\n",
            "int add",
            "function",
            None,
        ),
        (
            "ruby",
            b"def add(a)\n  a\nend\n",
            "def add",
            "function",
            "add",
        ),
        (
            "csharp",
            b"class Widget { int Value() { return 1; } }\n",
            "class Widget",
            "class",
            "Widget",
        ),
    ],
)
def test_kind_mapping_per_language(
    language_name,
    source,
    expected_text,
    expected_kind,
    expected_name,
):
    tree = _parse_language(language_name, source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name=language_name,
        file_path=f"x.{language_name}",
        budget_bytes=35 if language_name == "go" else 120,
    )

    matching_chunks = [chunk for chunk in chunks if expected_text in chunk.content]
    assert matching_chunks, f"expected chunk containing {expected_text!r}: {chunks}"
    chunk = matching_chunks[0]
    assert chunk.kind == expected_kind
    assert chunk.name == expected_name


@pytest.mark.parametrize(
    ("language_name", "source", "expected_name"),
    [
        (
            "javascript",
            b"class Widget { render() { return 1; } }\n",
            "Widget",
        ),
        (
            "typescript",
            b"class Widget { render(): number { return 1; } }\n",
            "Widget",
        ),
        (
            "java",
            b"class Widget { int value() { return 1; } }\n",
            "Widget",
        ),
        (
            "csharp",
            b"class Widget { int Value() { return 1; } }\n",
            "Widget",
        ),
    ],
)
def test_method_kind_inside_class(language_name, source, expected_name):
    tree = _parse_language(language_name, source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name=language_name,
        file_path=f"x.{language_name}",
        budget_bytes=1500,
    )

    assert len(chunks) == 1
    assert chunks[0].kind == "class"
    assert chunks[0].name == expected_name


@pytest.mark.parametrize(
    ("language_name", "source", "budget_bytes", "method_name"),
    [
        (
            "javascript",
            b"class C { tick() { return 1; } tock() { return 2; } }\n",
            20,
            "tick",
        ),
        (
            "typescript",
            b"class C { tick(): number { return 1; } tock(): number { return 2; } }\n",
            28,
            "tick",
        ),
        (
            "java",
            b"class C { int tick() { return 1; } int tock() { return 2; } }\n",
            24,
            "tick",
        ),
        (
            "csharp",
            b"class C { int Tick() { return 1; } int Tock() { return 2; } }\n",
            24,
            "Tick",
        ),
    ],
)
def test_method_kind_emitted_for_split_non_python_classes(
    language_name,
    source,
    budget_bytes,
    method_name,
):
    tree = _parse_language(language_name, source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name=language_name,
        file_path=f"x.{language_name}",
        budget_bytes=budget_bytes,
    )

    method_chunks = [chunk for chunk in chunks if chunk.kind == "method"]
    assert method_chunks, f"expected method chunk: {chunks}"
    expected_path = f"module/class[C]/method[{method_name}]"
    assert any(chunk.ast_path == expected_path for chunk in method_chunks), (
        f"expected {expected_path!r}: {[chunk.ast_path for chunk in chunks]}"
    )


@pytest.mark.parametrize(
    ("language_name", "source", "node_type"),
    [
        ("javascript", b"const f = () => 1;\n", "arrow_function"),
        ("javascript", b"const f = function () { return 1; };\n", "function_expression"),
        ("javascript", b"function* gen() { yield 1; }\n", "generator_function_declaration"),
        ("tsx", b"const Component = () => <div />;\n", "arrow_function"),
    ],
)
def test_common_javascript_typescript_function_forms_are_functions(
    language_name,
    source,
    node_type,
):
    tree = _parse_language(language_name, source)
    node, parents = _find_first_node_with_parents(tree.root_node, node_type)

    assert cast_chunker._kind_for_node(language_name, node, parents) == "function"


@pytest.mark.parametrize(
    ("language_name", "source", "expected_name"),
    [
        ("javascript", b"const f = () => 1;\n", "f"),
        ("javascript", b"const f = function () { return 1; };\n", "f"),
        ("tsx", b"const Component = () => <div />;\n", "Component"),
        ("javascript", b"obj.f = () => 1;\n", "f"),
        ("javascript", b"exports.f = function () { return 1; };\n", "f"),
        ("javascript", b"const f = (() => 1);\n", "f"),
        ("javascript", b"const f = (/* c */ () => 1);\n", "f"),
        (
            "javascript",
            b"obj.f = (/* c */ function () { return 1; });\n",
            "f",
        ),
    ],
)
def test_assigned_function_chunks_use_declarator_name(
    language_name,
    source,
    expected_name,
):
    tree = _parse_language(language_name, source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name=language_name,
        file_path=f"x.{language_name}",
        budget_bytes=1500,
    )

    function_chunks = [chunk for chunk in chunks if chunk.kind == "function"]
    assert function_chunks, chunks
    assert any(chunk.name == expected_name for chunk in function_chunks)
    assert any(
        chunk.ast_path == f"module/function[{expected_name}]"
        for chunk in function_chunks
    )


def test_typescript_interface_and_method_signature_are_class_and_method():
    source = b"interface I { tick(): number; }\n"
    tree = _parse_language("typescript", source)
    interface_node, interface_parents = _find_first_node_with_parents(
        tree.root_node,
        "interface_declaration",
    )
    method_node, method_parents = _find_first_node_with_parents(
        tree.root_node,
        "method_signature",
    )

    assert (
        cast_chunker._kind_for_node("typescript", interface_node, interface_parents)
        == "class"
    )
    assert cast_chunker._kind_for_node("typescript", method_node, method_parents) == "method"
    assert (
        cast_chunker._ast_path("typescript", method_node, method_parents, source)
        == "module/class[I]/method[tick]"
    )


def test_go_receiver_method_emits_method_chunk():
    source = b"package main\ntype C struct{}\nfunc (c C) Tick() int { return 1 }\n"
    tree = _parse_language("go", source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name="go",
        file_path="x.go",
        budget_bytes=40,
    )

    method_chunks = [chunk for chunk in chunks if chunk.kind == "method"]
    assert method_chunks, f"expected method chunk: {chunks}"
    assert any(chunk.ast_path == "module/method[Tick]" for chunk in method_chunks)


def test_rust_impl_function_emits_method_chunk_with_impl_path():
    source = b"struct C;\nimpl C { fn tick(&self) -> i32 { 1 } }\n"
    tree = _parse_language("rust", source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name="rust",
        file_path="x.rs",
        budget_bytes=28,
    )

    method_chunks = [chunk for chunk in chunks if chunk.kind == "method"]
    assert method_chunks, f"expected method chunk: {chunks}"
    assert any(
        chunk.ast_path == "module/class[?]/method[tick]"
        for chunk in method_chunks
    )


@pytest.mark.parametrize(
    ("language_name", "source", "node_type", "expected_kind"),
    [
        ("javascript", b"class C {}\n", "class", "class"),
        ("typescript", b"class C {}\n", "class", "class"),
        ("tsx", b"class C {}\n", "class", "class"),
        ("rust", b"struct C;\n", "struct_item", "class"),
        ("rust", b"trait T { fn tick(&self); }\n", "trait_item", "class"),
        ("rust", b"enum E { A }\n", "enum_item", "class"),
        ("java", b"enum E { A }\n", "enum_declaration", "class"),
        ("java", b"record R(int x) {}\n", "record_declaration", "class"),
        ("c", b"struct C { int x; };\n", "struct_specifier", "class"),
        ("csharp", b"record R(int X);\n", "record_declaration", "class"),
        ("csharp", b"enum E { A }\n", "enum_declaration", "class"),
        (
            "csharp",
            b"class C { void M() { int Local() { return 1; } } }\n",
            "local_function_statement",
            "method",
        ),
    ],
)
def test_kind_mapping_planned_node_types(
    language_name,
    source,
    node_type,
    expected_kind,
):
    tree = _parse_language(language_name, source)
    node, parents = _find_first_node_with_parents(tree.root_node, node_type)

    assert cast_chunker._kind_for_node(language_name, node, parents) == expected_kind


@pytest.mark.parametrize(
    ("language_name", "source", "expected_kind"),
    [
        ("c", b"struct C { int x; };\n", "class"),
        ("cpp", b"struct C { int x; };\n", "class"),
        ("javascript", b"class C {};\n", "class"),
        ("typescript", b"interface I { m(): void; }\n", "class"),
        ("javascript", b"const f = () => 1;\n", "function"),
        ("javascript", b"const gen = function* () { yield 1; };\n", "function"),
    ],
)
def test_emitted_chunks_preserve_mapped_metadata_through_trivia_merges(
    language_name,
    source,
    expected_kind,
):
    tree = _parse_language(language_name, source)
    chunks = cast_chunker.cast_chunks(
        tree,
        source,
        language_name=language_name,
        file_path=f"x.{language_name}",
        budget_bytes=1500,
    )

    assert any(chunk.kind == expected_kind for chunk in chunks), chunks
