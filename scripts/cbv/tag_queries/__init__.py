from __future__ import annotations

from functools import lru_cache
from importlib import resources


CAPTURE_TO_NODE_KIND = {
    "definition.class": "class",
    "definition.function": "function",
    "definition.method": "method",
    "definition.variable": "variable",
    "definition.module": "module",
}


CAPTURE_TO_EDGE_KIND = {
    "reference.call": "calls",
    "reference.import": "imports",
    "reference.inherits": "inherits",
    "reference.identifier": "references",
}


@lru_cache(maxsize=None)
def query_source(language_name: str) -> str:
    return (
        resources.files("cbv.tag_queries")
        .joinpath(f"{language_name}.scm")
        .read_text(encoding="utf-8")
    )
