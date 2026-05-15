from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import query_router  # noqa: E402


def test_identifier_routes_fast():
    assert query_router.route("authenticate_user") == "fast"
    assert query_router.route("where is authenticate_user") == "fast"


def test_regex_routes_fast():
    assert query_router.route("regex:authenticate_.*") == "fast"


def test_short_identifier_like_query_routes_fast():
    assert query_router.route("auth db") == "fast"


def test_natural_language_routes_full():
    assert query_router.route("how does login authenticate users") == "full"


def test_forced_lane_wins():
    assert query_router.route("authenticate_user", forced="full") == "full"
    assert query_router.route("how does auth work", forced="fast") == "fast"
