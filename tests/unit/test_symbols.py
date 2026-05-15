from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


def test_extract_symbols_returns_file_node_when_tree_missing():
    extracted = symbols.extract_symbols(Path("pkg/router.py"), "python", b"", None)

    assert [
        (n.kind, n.name, n.short_name, n.file_path, n.start_line, n.end_line)
        for n in extracted.nodes
    ] == [("file", "pkg/router.py", "router.py", "pkg/router.py", 1, 1)]
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


@pytest.mark.parametrize(
    "language, filename, source, expected_defs, expected_edges",
    [
        (
            "python",
            "pkg/auth.py",
            b"import os\nclass Auth:\n    def login(self):\n        return os.getenv('X')\n",
            {"Auth", "login"},
            {"imports", "calls", "contains"},
        ),
        (
            "javascript",
            "util.js",
            b"import { snakeCase } from './fmt.js';\nexport function camelCase(x) { return snakeCase(x); }\n",
            {"camelCase"},
            {"imports", "calls"},
        ),
        (
            "typescript",
            "svc.ts",
            b"interface User { name: string }\nfunction loadUser(): User { return fetchUser(); }\n",
            {"User", "loadUser"},
            {"calls"},
        ),
        (
            "tsx",
            "view.tsx",
            b"export function Login() { return <button onClick={submit}>Go</button>; }\n",
            {"Login"},
            {"references"},
        ),
        (
            "go",
            "main.go",
            b"package main\nimport \"fmt\"\nfunc run() { fmt.Println(\"x\") }\n",
            {"run"},
            {"imports", "calls"},
        ),
        (
            "rust",
            "lib.rs",
            b"use crate::auth;\nstruct User;\nfn login() { auth::check(); }\n",
            {"User", "login"},
            {"imports", "calls"},
        ),
        (
            "java",
            "Auth.java",
            b"import java.util.List; class Auth { void login() { check(); } }\n",
            {"Auth", "login"},
            {"imports", "calls"},
        ),
        (
            "c",
            "auth.c",
            b"#include <stdio.h>\nint login() { return check(); }\n",
            {"login"},
            {"imports", "calls"},
        ),
        (
            "cpp",
            "auth.cpp",
            b"#include <vector>\nclass Auth {}; int login() { return check(); }\n",
            {"Auth", "login"},
            {"imports", "calls"},
        ),
        (
            "ruby",
            "auth.rb",
            b"require 'json'\ndef login\n  check\nend\n",
            {"login"},
            {"imports", "calls"},
        ),
        (
            "csharp",
            "Auth.cs",
            b"using System; class Auth { void Login() { Check(); } }\n",
            {"Auth", "Login"},
            {"imports", "calls"},
        ),
    ],
)
def test_tier_a_tags_extract_defs_and_edges(
    language,
    filename,
    source,
    expected_defs,
    expected_edges,
):
    lang = parser.language_for_name(language)
    tree = parser.parse(source, lang)
    extracted = symbols.extract_symbols(Path(filename), language, source, tree)
    short_names = {n.short_name for n in extracted.nodes}
    edge_kinds = {e.kind for e in extracted.edges}
    assert expected_defs <= short_names
    assert expected_edges <= edge_kinds
