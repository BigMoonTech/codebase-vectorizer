from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import identifiers  # noqa: E402


def test_extract_identifiers_splits_common_code_names():
    text = "authenticate_user camelCase HTTPServer2 user_id"
    assert identifiers.extract_identifiers(text) == {
        "authenticate_user", "authenticate", "user",
        "camelCase", "camel", "Case",
        "HTTPServer2", "HTTP", "Server2", "user_id", "id",
    }


def test_trigrams_pad_and_lowercase():
    assert identifiers.trigrams("Auth") == {"  a", " au", "aut", "uth", "th "}


def test_symbol_rows_count_occurrences_by_chunk():
    rows = identifiers.symbol_trigram_rows(7, "auth auth user")
    assert ("aut", 7, "auth", 2) in rows
    assert ("use", 7, "user", 1) in rows
