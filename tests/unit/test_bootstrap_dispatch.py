"""Tests for the verb dispatcher's argument parsing only.

The actual command implementations are tested in their own modules.
This test asserts that `python -m cbv <verb> ...` parses without
error and dispatches to a function registered by the verb name.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import cli  # noqa: E402


def test_cli_known_verbs():
    """All Slice 1 verbs are registered on the parser."""
    parser = cli.build_parser()
    actions = {a.dest: a for a in parser._actions}
    sub = next(a for a in parser._actions if a.dest == "verb")
    choices = set(sub.choices.keys())
    assert {"vectorize", "query", "list", "info"} <= choices


def test_cli_dispatch_table_has_all_verbs():
    """Every parser choice has a callable in the dispatch table."""
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "verb")
    for verb in sub.choices.keys():
        assert verb in cli.DISPATCH, f"missing dispatcher for {verb!r}"
        assert callable(cli.DISPATCH[verb])


def test_cli_parses_vectorize_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["vectorize", "https://github.com/x/y"])
    assert ns.verb == "vectorize"
    assert ns.source == "https://github.com/x/y"


def test_cli_parses_query_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["query", "myrepo", "how does auth work", "--top-k", "5"])
    assert ns.verb == "query"
    assert ns.repo == "myrepo"
    assert ns.question == "how does auth work"
    assert ns.top_k == 5


def test_cli_query_top_k_default():
    parser = cli.build_parser()
    ns = parser.parse_args(["query", "r", "q"])
    assert ns.top_k == 10


def test_cli_unknown_verb_errors(capsys):
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nonsense"])
