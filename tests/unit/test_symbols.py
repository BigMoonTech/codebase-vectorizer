from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import parser, symbols, tag_queries  # noqa: E402


def _extract(language: str, filename: str, source: bytes):
    lang = parser.language_for_name(language)
    tree = parser.parse(source, lang)
    return symbols.extract_symbols(Path(filename), language, source, tree)


def _edge_tuples(extracted):
    return {(edge.src_name, edge.dst_name, edge.kind) for edge in extracted.edges}


def _node_tuples(extracted):
    return {(node.kind, node.name, node.short_name) for node in extracted.nodes}


def test_tag_queries_package_reexports_sibling_loader():
    assert tag_queries.LOADER_SOURCE == "scripts/cbv/tag_queries.py"
    assert (
        Path(tag_queries.query_source.__wrapped__.__code__.co_filename).as_posix()
        .endswith("scripts/cbv/tag_queries.py")
    )
    assert "(function_definition)" in tag_queries.query_source("python")


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


def test_python_tags_extract_exact_inherits_variables_references_and_contains():
    src = (
        b"class Base:\n"
        b"    pass\n"
        b"\n"
        b"class Auth(Base):\n"
        b"    token = make_token()\n"
        b"    def login(self):\n"
        b"        user = current_user\n"
        b"        return helper(user)\n"
    )
    extracted = _extract("python", "pkg/auth.py", src)

    assert {
        ("class", "pkg/auth.py::Base", "Base"),
        ("class", "pkg/auth.py::Auth", "Auth"),
        ("variable", "pkg/auth.py::Auth::token", "token"),
        ("method", "pkg/auth.py::Auth::login", "login"),
        ("variable", "pkg/auth.py::Auth::login::user", "user"),
    } <= _node_tuples(extracted)
    assert {
        ("pkg/auth.py", "pkg/auth.py::Base", "contains"),
        ("pkg/auth.py", "pkg/auth.py::Auth", "contains"),
        ("pkg/auth.py::Auth", "pkg/auth.py::Auth::login", "contains"),
        ("pkg/auth.py::Auth", "pkg/auth.py::Base", "inherits"),
        ("pkg/auth.py::Auth::token", "make_token", "calls"),
        ("pkg/auth.py::Auth::login", "helper", "calls"),
        ("pkg/auth.py::Auth::login::user", "current_user", "references"),
        ("pkg/auth.py::Auth::login", "pkg/auth.py::Auth::login::user", "references"),
    } <= _edge_tuples(extracted)


def test_javascript_symbols_extract_function_and_call():
    src = b"export function camelCase(x) { return snakeCase(x); }\n"
    lang = parser.language_for_name("javascript")
    tree = parser.parse(src, lang)
    extracted = symbols.extract_symbols(Path("util.js"), "javascript", src, tree)
    assert any(n.short_name == "camelCase" and n.kind == "function" for n in extracted.nodes)
    assert any(e.kind == "calls" and e.dst_name == "snakeCase" for e in extracted.edges)


@pytest.mark.parametrize(
    "language, filename, source, expected_nodes, expected_edges",
    [
        (
            "javascript",
            "web/auth.js",
            b"class Auth extends Base { login() { const token = currentUser; return helper(token); } }\n",
            {
                ("class", "web/auth.js::Auth", "Auth"),
                ("method", "web/auth.js::Auth::login", "login"),
                ("variable", "web/auth.js::Auth::login::token", "token"),
            },
            {
                ("web/auth.js::Auth", "Base", "inherits"),
                ("web/auth.js::Auth::login", "helper", "calls"),
                ("web/auth.js::Auth::login::token", "currentUser", "references"),
                ("web/auth.js::Auth::login", "web/auth.js::Auth::login::token", "references"),
            },
        ),
        (
            "typescript",
            "web/auth.ts",
            b"class User extends Base implements Named { field = currentUser; login(): void { const token = helper(field); } }\n",
            {
                ("class", "web/auth.ts::User", "User"),
                ("variable", "web/auth.ts::User::field", "field"),
                ("method", "web/auth.ts::User::login", "login"),
                ("variable", "web/auth.ts::User::login::token", "token"),
            },
            {
                ("web/auth.ts::User", "Base", "inherits"),
                ("web/auth.ts::User", "Named", "inherits"),
                ("web/auth.ts::User::field", "currentUser", "references"),
                ("web/auth.ts::User::login::token", "helper", "calls"),
                ("web/auth.ts::User::login::token", "web/auth.ts::User::field", "references"),
            },
        ),
        (
            "tsx",
            "web/view.tsx",
            b"class View extends Component { render() { const label = props.title; return <button onClick={submit}>{label}</button>; } }\n",
            {
                ("class", "web/view.tsx::View", "View"),
                ("method", "web/view.tsx::View::render", "render"),
                ("variable", "web/view.tsx::View::render::label", "label"),
            },
            {
                ("web/view.tsx::View", "Component", "inherits"),
                ("web/view.tsx::View::render::label", "props", "references"),
                ("web/view.tsx::View::render", "submit", "references"),
                ("web/view.tsx::View::render", "web/view.tsx::View::render::label", "references"),
            },
        ),
    ],
)
def test_js_family_tags_extract_exact_inherits_variables_and_references(
    language,
    filename,
    source,
    expected_nodes,
    expected_edges,
):
    extracted = _extract(language, filename, source)

    assert expected_nodes <= _node_tuples(extracted)
    assert expected_edges <= _edge_tuples(extracted)


@pytest.mark.parametrize(
    "language, filename, source, expected_nodes, expected_edges",
    [
        (
            "java",
            "src/Auth.java",
            b"class Auth extends Base implements Login { int token = seed; void login() { helper(token); } }\n",
            {
                ("class", "src/Auth.java::Auth", "Auth"),
                ("variable", "src/Auth.java::Auth::token", "token"),
                ("method", "src/Auth.java::Auth::login", "login"),
            },
            {
                ("src/Auth.java::Auth", "Base", "inherits"),
                ("src/Auth.java::Auth", "Login", "inherits"),
                ("src/Auth.java::Auth::token", "seed", "references"),
                ("src/Auth.java::Auth::login", "helper", "calls"),
                ("src/Auth.java::Auth::login", "src/Auth.java::Auth::token", "references"),
            },
        ),
        (
            "csharp",
            "src/Auth.cs",
            b"class Auth : Base, ILogin { int token = seed; void Login() { Helper(token); } }\n",
            {
                ("class", "src/Auth.cs::Auth", "Auth"),
                ("variable", "src/Auth.cs::Auth::token", "token"),
                ("method", "src/Auth.cs::Auth::Login", "Login"),
            },
            {
                ("src/Auth.cs::Auth", "Base", "inherits"),
                ("src/Auth.cs::Auth", "ILogin", "inherits"),
                ("src/Auth.cs::Auth::token", "seed", "references"),
                ("src/Auth.cs::Auth::Login", "Helper", "calls"),
                ("src/Auth.cs::Auth::Login", "src/Auth.cs::Auth::token", "references"),
            },
        ),
        (
            "cpp",
            "src/auth.cpp",
            b"class Auth : public Base { int token; void login() { helper(token); } };\n",
            {
                ("class", "src/auth.cpp::Auth", "Auth"),
                ("variable", "src/auth.cpp::Auth::token", "token"),
                ("method", "src/auth.cpp::Auth::login", "login"),
            },
            {
                ("src/auth.cpp::Auth", "Base", "inherits"),
                ("src/auth.cpp::Auth::login", "helper", "calls"),
                ("src/auth.cpp::Auth::login", "src/auth.cpp::Auth::token", "references"),
            },
        ),
    ],
)
def test_nominal_language_tags_extract_exact_inherits_variables_and_references(
    language,
    filename,
    source,
    expected_nodes,
    expected_edges,
):
    extracted = _extract(language, filename, source)

    assert expected_nodes <= _node_tuples(extracted)
    assert expected_edges <= _edge_tuples(extracted)


def test_c_tags_extract_exact_variables_and_references():
    src = b"int global = seed; int login() { int token = global; return check(token); }\n"
    extracted = _extract("c", "src/auth.c", src)

    assert {
        ("variable", "src/auth.c::global", "global"),
        ("function", "src/auth.c::login", "login"),
        ("variable", "src/auth.c::login::token", "token"),
    } <= _node_tuples(extracted)
    assert {
        ("src/auth.c::global", "seed", "references"),
        ("src/auth.c::login::token", "src/auth.c::global", "references"),
        ("src/auth.c::login", "check", "calls"),
        ("src/auth.c::login", "src/auth.c::login::token", "references"),
    } <= _edge_tuples(extracted)


def test_same_file_call_references_resolve_to_full_function_name():
    src = b"def helper():\n    return 1\n\ndef caller():\n    return helper()\n"
    extracted = _extract("python", "pkg/local.py", src)

    assert (
        "pkg/local.py::caller",
        "pkg/local.py::helper",
        "calls",
    ) in _edge_tuples(extracted)


def test_rust_impl_does_not_duplicate_struct_node_names():
    src = b"struct User;\nimpl User { fn login(&self) {} }\n"
    extracted = _extract("rust", "src/lib.rs", src)

    names = [node.name for node in extracted.nodes]
    assert names.count("src/lib.rs::User") == 1
    assert ("class", "src/lib.rs::User", "User") in _node_tuples(extracted)
    assert ("function", "src/lib.rs::login", "login") in _node_tuples(extracted)


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
