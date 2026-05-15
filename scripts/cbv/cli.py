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
    pv.add_argument("--no-cache", action="store_true",
                    help="disable the cross-repo embedding cache")
    pv.add_argument("--update", action="store_true",
                    help="update an existing index instead of rebuilding when possible")
    pv.add_argument("--bench", action="store_true",
                    help="run benchmark queries after indexing")

    pq = sub.add_parser("query", help="Query an indexed repo")
    pq.add_argument("repo", help="indexed repo name")
    pq.add_argument("question", help="natural-language or identifier query")
    pq.add_argument("--top-k", type=int, default=10,
                    help="number of results to return (default 10)")
    pq.add_argument("--lane", choices=("auto", "fast", "full"), default="auto",
                    help="query lane: auto, fast, or full (default auto)")

    ps = sub.add_parser("stats", help="Print counts and top PageRank nodes")
    ps.add_argument("repo", help="indexed repo name")
    ps.add_argument("--top-k", type=int, default=10,
                    help="number of PageRank nodes to return (default 10)")

    pb = sub.add_parser("bench", help="Run retrieval benchmarks for an indexed repo")
    pb.add_argument("repo", help="indexed repo name")

    pr = sub.add_parser("relate", help="Run graph relationship queries")
    pr.add_argument("repo", help="indexed repo name")
    pr.add_argument(
        "relate_verb",
        choices=(
            "callers",
            "callees",
            "inheritance-chain",
            "neighbors",
            "concept-cluster",
            "pagerank-top",
            "shortest-path",
            "paths-through",
            "reaching-definitions",
            "reachable-uses",
            "conditions-for",
        ),
        help="relationship query to run",
    )
    pr.add_argument("query", nargs="?", default="", help="symbol or concept query")
    pr.add_argument("target", nargs="?", default=None, help="target symbol for shortest-path")
    pr.add_argument("--top-k", type=int, default=10,
                    help="number of results to return (default 10)")
    pr.add_argument("--hops", type=int, default=2,
                    help="maximum graph hops for walk/path queries (default 2)")

    pg = sub.add_parser("graph", help="Alias for relate neighbors")
    pg.add_argument("repo", help="indexed repo name")
    pg.add_argument("query", help="symbol query")
    pg.add_argument("--top-k", type=int, default=10,
                    help="number of results to return (default 10)")
    pg.add_argument("--hops", type=int, default=2,
                    help="maximum graph hops (default 2)")

    pf = sub.add_parser("flow", help="Alias for relate paths-through")
    pf.add_argument("repo", help="indexed repo name")
    pf.add_argument("query", help="symbol or block query")
    pf.add_argument("--top-k", type=int, default=10,
                    help="number of results to return (default 10)")

    sub.add_parser("list", help="List every indexed repo")
    sub.add_parser("info", help="Print plugin paths and readiness")

    return p


def _import_command(verb: str):
    if verb == "vectorize":
        from cbv.commands import vectorize as mod
    elif verb == "query":
        from cbv.commands import query as mod
    elif verb == "stats":
        from cbv.commands import stats as mod
    elif verb == "bench":
        from cbv.commands import bench_cmd as mod
    elif verb == "relate":
        from cbv.commands import relate as mod
    elif verb == "graph":
        from cbv.commands import graph_cmd as mod
    elif verb == "flow":
        from cbv.commands import flow_cmd as mod
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
    "stats":     lambda ns: _import_command("stats").run(ns),
    "bench":     lambda ns: _import_command("bench").run(ns),
    "relate":    lambda ns: _import_command("relate").run(ns),
    "graph":     lambda ns: _import_command("graph").run(ns),
    "flow":      lambda ns: _import_command("flow").run(ns),
    "list":      lambda ns: _import_command("list").run(ns),
    "info":      lambda ns: _import_command("info").run(ns),
}


def main(argv=None) -> int:
    ns = build_parser().parse_args(argv)
    return DISPATCH[ns.verb](ns)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
