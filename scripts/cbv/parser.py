"""Language registry for codebase-vectorizer tree-sitter support.

This module defines the set of languages cbv will parse with
tree-sitter ("Tier-A" languages per the spec), plus helpers for looking
up languages by canonical name or file extension.

Top-level imports are stdlib-only so the registry can be used without
tree-sitter installed. A future slice will add parsing support with lazy
tree-sitter imports.

Slice 2 covers Tier-A languages. Tier-B / Tier-C support (more grammars
without CFG/DFG) is a future-slice concern; nothing prevents us from
adding entries to LANGUAGES later.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Language:
    """cbv-side language metadata.

    `name` is the canonical cbv name used in `Chunk.language` and
    elsewhere downstream. `ts_language_name` is the string
    `tree_sitter_language_pack.get_parser()` expects (sometimes the
    same, sometimes not -- e.g. "csharp" vs "c_sharp").
    """

    name: str
    ts_language_name: str
    extensions: tuple[str, ...]


# Tier-A languages per the spec section "Per-language coverage tier".
LANGUAGES: dict[str, Language] = {
    "python": Language("python", "python", (".py", ".pyi")),
    "javascript": Language("javascript", "javascript", (".js", ".mjs", ".cjs", ".jsx")),
    "typescript": Language("typescript", "typescript", (".ts",)),
    "tsx": Language("tsx", "tsx", (".tsx",)),
    "go": Language("go", "go", (".go",)),
    "rust": Language("rust", "rust", (".rs",)),
    "java": Language("java", "java", (".java",)),
    "c": Language("c", "c", (".c", ".h")),
    "cpp": Language("cpp", "cpp", (".cpp", ".cxx", ".cc", ".hpp", ".hxx")),
    "ruby": Language("ruby", "ruby", (".rb",)),
    "csharp": Language("csharp", "csharp", (".cs",)),
}


EXTENSION_LANGUAGE: dict[str, Language] = {
    ext: lang for lang in LANGUAGES.values() for ext in lang.extensions
}


def language_for_name(name: str) -> Optional[Language]:
    """Look up a Language by its cbv canonical name."""
    return LANGUAGES.get(name)


def language_for_path(path: Path) -> Optional[Language]:
    """Look up the Language that should parse the given file path.

    Return None when the extension is unrecognized, so callers can fall
    back to text-window chunking.
    """
    return EXTENSION_LANGUAGE.get(path.suffix.lower())


def parse(content: bytes, language: Language):
    """Parse `content` with the given Language. Returns a tree-sitter Tree
    (or None on failure).

    `tree_sitter_language_pack` is imported lazily so that callers
    needing only `LANGUAGES` / `language_for_path` (or tests that don't
    touch tree-sitter) pay zero import cost.

    Tree-sitter parsers are error-tolerant; a malformed source still
    returns a Tree (with `has_error == True`). The None path is reserved
    for outright failure to construct a parser (e.g. an unsupported
    language slipped through the registry).
    """
    try:
        from tree_sitter_language_pack import get_parser
    except ImportError:
        return None
    try:
        parser_obj = get_parser(language.ts_language_name)
        return parser_obj.parse(content)
    except Exception:
        return None
