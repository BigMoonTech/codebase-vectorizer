"""Tests for cbv.parser -- Language registry only (parse() is exercised in
the next task). The registry is stdlib-only so these tests run without
tree-sitter installed."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import parser  # noqa: E402


def test_language_dataclass_fields():
    py = parser.LANGUAGES["python"]
    assert py.name == "python"
    assert py.ts_language_name == "python"
    assert ".py" in py.extensions
    assert ".pyi" in py.extensions


def test_languages_registry_includes_tier_a():
    expected = {
        "python", "javascript", "typescript", "tsx",
        "go", "rust", "java", "c", "cpp", "ruby", "csharp",
    }
    assert expected <= set(parser.LANGUAGES.keys()), \
        f"missing: {expected - set(parser.LANGUAGES.keys())}"


def test_language_for_path_python():
    lang = parser.language_for_path(Path("foo.py"))
    assert lang is not None
    assert lang.name == "python"


def test_language_for_path_typescript_vs_tsx():
    assert parser.language_for_path(Path("a.ts")).name == "typescript"
    assert parser.language_for_path(Path("a.tsx")).name == "tsx"


def test_language_for_path_jsx_is_javascript():
    """The JS grammar handles JSX too in tree-sitter-language-pack."""
    assert parser.language_for_path(Path("a.jsx")).name == "javascript"


def test_language_for_path_cpp_extensions():
    for ext in (".cpp", ".cxx", ".cc", ".hpp", ".hxx"):
        lang = parser.language_for_path(Path(f"a{ext}"))
        assert lang is not None, ext
        assert lang.name == "cpp"


def test_language_for_path_unknown_returns_none():
    assert parser.language_for_path(Path("foo.unknown")) is None
    assert parser.language_for_path(Path("foo.md")) is None  # markdown not in Tier-A


def test_language_for_name():
    assert parser.language_for_name("python").name == "python"
    assert parser.language_for_name("bogus") is None


def test_parse_python_returns_tree():
    lang = parser.LANGUAGES["python"]
    src = b"def foo(x):\n    return x + 1\n"
    tree = parser.parse(src, lang)
    assert tree is not None
    root = tree.root_node
    assert root.type == "module"
    # First child is the function definition
    fn = root.children[0]
    assert fn.type == "function_definition"
    assert fn.start_byte == 0
    assert fn.end_byte == len(src.rstrip(b"\n"))
    assert root.end_byte == len(src)


def test_parse_javascript_returns_tree():
    lang = parser.LANGUAGES["javascript"]
    src = b"function add(a, b) { return a + b; }\n"
    tree = parser.parse(src, lang)
    assert tree is not None
    root = tree.root_node
    assert root.type == "program"
    fn = root.children[0]
    assert fn.type == "function_declaration"


def test_parse_returns_a_tree_even_on_syntax_errors():
    """tree-sitter is error-tolerant: it returns a tree with ERROR nodes
    rather than raising. We rely on this for graceful chunking of broken
    files."""
    lang = parser.LANGUAGES["python"]
    src = b"def foo(:\n    this is not valid python\n"
    tree = parser.parse(src, lang)
    assert tree is not None  # NOT None -- tree-sitter is permissive
    assert tree.root_node.has_error  # tree carries an ERROR somewhere


def test_parse_empty_input():
    """Empty bytes are still a valid (trivial) parse."""
    lang = parser.LANGUAGES["python"]
    tree = parser.parse(b"", lang)
    assert tree is not None
    assert tree.root_node.start_byte == 0
    assert tree.root_node.end_byte == 0
