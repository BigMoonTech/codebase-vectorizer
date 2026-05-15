"""argparse-based verb dispatcher for `python -m cbv`.

Each verb lives in `cbv.commands.<verb>` and exposes a `run(ns) -> int`
function. The parser is built independently of the dispatch table so
that unit tests can verify both surface shapes without invoking commands.
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict

# Commands are imported lazily inside _dispatch() so unit tests that
# only exercise argument parsing don't pull in heavy modules
# (transformers, torch) at import time.


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cbv", description="codebase-vectorizer v1.0")
    sub = p.add_subparsers(dest="verb", required=True)

    pv = sub.add_parser("vectorize", help="Index a repo (URL or local path)")
    pv.add_argument("source", help="git URL or local path")
    pv.add_argument("--output-dir", default=None,
                    help="override repo directory location")
    pv.add_argument("--max-file-mb", type=float, default=1.5,
                    help="skip files larger than this many MB (default 1.5)")

    pq = sub.add_parser("query", help="Query an indexed repo")
    pq.add_argument("repo", help="indexed repo name")
    pq.add_argument("question", help="natural-language or identifier query")
    pq.add_argument("--top-k", type=int, default=10,
                    help="number of results to return (default 10)")
    pq.add_argument("--lane", choices=("auto", "fast", "full"), default="auto",
                    help="query lane: auto, fast, or full (default auto)")

    sub.add_parser("list", help="List every indexed repo")
    sub.add_parser("info", help="Print plugin paths and readiness")

    return p


def _import_command(verb: str):
    if verb == "vectorize":
        from cbv.commands import vectorize as mod
    elif verb == "query":
        from cbv.commands import query as mod
    elif verb == "list":
        from cbv.commands import list_cmd as mod
    elif verb == "info":
        from cbv.commands import info as mod
    else:  # pragma: no cover — argparse rejects unknown verbs first
        raise SystemExit(f"unknown verb: {verb}")
    return mod


DISPATCH: Dict[str, Callable[[argparse.Namespace], int]] = {
    # Wrapped to defer the import until invocation. Each entry returns the
    # result of the command's run() function.
    "vectorize": lambda ns: _import_command("vectorize").run(ns),
    "query":     lambda ns: _import_command("query").run(ns),
    "list":      lambda ns: _import_command("list").run(ns),
    "info":      lambda ns: _import_command("info").run(ns),
}


def main(argv=None) -> int:
    ns = build_parser().parse_args(argv)
    return DISPATCH[ns.verb](ns)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
