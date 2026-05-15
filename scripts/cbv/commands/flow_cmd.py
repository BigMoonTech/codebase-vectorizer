from __future__ import annotations

import argparse

from cbv.commands import relate


def run(ns: argparse.Namespace) -> int:
    related = argparse.Namespace(
        repo=ns.repo,
        relate_verb="paths-through",
        query=ns.query,
        target=None,
        top_k=getattr(ns, "top_k", 10),
        hops=getattr(ns, "hops", 2),
    )
    return relate.run(related)
