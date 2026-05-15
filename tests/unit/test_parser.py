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
