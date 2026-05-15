from __future__ import annotations

import importlib.util
from pathlib import Path


_LOADER_PATH = Path(__file__).resolve().parent.parent / "tag_queries.py"
_SPEC = importlib.util.spec_from_file_location("_cbv_tag_queries_loader", _LOADER_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load tag query loader from {_LOADER_PATH}")

_LOADER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LOADER)

LOADER_SOURCE = _LOADER.LOADER_SOURCE
CAPTURE_TO_NODE_KIND = _LOADER.CAPTURE_TO_NODE_KIND
CAPTURE_TO_EDGE_KIND = _LOADER.CAPTURE_TO_EDGE_KIND
query_source = _LOADER.query_source

__all__ = [
    "LOADER_SOURCE",
    "CAPTURE_TO_NODE_KIND",
    "CAPTURE_TO_EDGE_KIND",
    "query_source",
]
