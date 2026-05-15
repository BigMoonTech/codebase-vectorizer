from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import parser, symbols  # noqa: E402


def test_python_symbols_extract_defs_imports_calls():
    src = b"from pkg.auth import authenticate_user\n\ndef route(req):\n    return authenticate_user(req['u'], req['p'])\n"
    lang = parser.language_for_name("python")
    tree = parser.parse(src, lang)
    extracted = symbols.extract_symbols(Path("pkg/router.py"), "python", src, tree)
    assert ("function", "pkg/router.py::route", "route") in [
        (n.kind, n.name, n.short_name) for n in extracted.nodes
    ]
    assert any(e.kind == "imports" and e.dst_name == "authenticate_user" for e in extracted.edges)
    assert any(e.kind == "calls" and e.dst_name == "authenticate_user" for e in extracted.edges)


def test_javascript_symbols_extract_function_and_call():
    src = b"export function camelCase(x) { return snakeCase(x); }\n"
    lang = parser.language_for_name("javascript")
    tree = parser.parse(src, lang)
    extracted = symbols.extract_symbols(Path("util.js"), "javascript", src, tree)
    assert any(n.short_name == "camelCase" and n.kind == "function" for n in extracted.nodes)
    assert any(e.kind == "calls" and e.dst_name == "snakeCase" for e in extracted.edges)


def test_extract_symbols_returns_empty_when_tree_missing():
    extracted = symbols.extract_symbols(Path("pkg/router.py"), "python", b"", None)

    assert extracted.nodes == []
    assert extracted.edges == []


def test_nested_python_definitions_emit_contains_edges():
    src = b"class Controller:\n    def route(self):\n        def helper():\n            return 1\n        return helper()\n"
    lang = parser.language_for_name("python")
    tree = parser.parse(src, lang)
    extracted = symbols.extract_symbols(Path("pkg/router.py"), "python", src, tree)

    assert any(
        n.kind == "file" and n.name == "pkg/router.py" and n.short_name == "router.py"
        for n in extracted.nodes
    )
    assert any(
        e.kind == "contains"
        and e.src_name == "pkg/router.py"
        and e.dst_name == "pkg/router.py::Controller"
        for e in extracted.edges
    )
    assert any(
        e.kind == "contains"
        and e.src_name == "pkg/router.py::Controller::route"
        and e.dst_name == "pkg/router.py::Controller::route::helper"
        for e in extracted.edges
    )
