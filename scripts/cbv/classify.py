"""Path-based file-kind classification for candidate-pool composition.

Pure and language-agnostic: maps a repo-relative POSIX path to one of six
categories. No file content is read. Heuristic by design; v2 refines it.
"""
from __future__ import annotations

from pathlib import PurePosixPath

CATEGORIES = ("source", "config", "test", "docs", "meta", "vendor")

_VENDOR_SEGMENTS = {
    "node_modules", "vendor", "third_party", "bower_components",
    "site-packages", ".venv", "venv", ".yarn", "pods", ".pnp",
}
_META_SEGMENTS = {
    ".claude", ".claude-plugin", ".codex", ".codex-plugin", ".cursor",
    ".gemini", ".kiro", ".agents", ".codebuddy",
}
# NOTE: .github is deliberately NOT meta -- .github/workflows/*.yml is CI/build
# config and is classified `config` by the _CONFIG_EXTS rule below.
_META_NAMES = {"claude.md", "agents.md", "gemini.md", ".cursorrules"}
_TEST_SEGMENTS = {"test", "tests", "__tests__", "e2e", "fixtures", "testdata"}
_DOC_SEGMENTS = {
    "docs", "doc", "documentation", "examples", "example", "samples", "specs",
}
_DOC_EXTS = {".md", ".markdown", ".rst", ".txt", ".adoc"}
_CONFIG_NAMES = {
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "tsconfig.json", "jsconfig.json", "dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "makefile", "cargo.toml", "cargo.lock", "go.mod",
    "go.sum", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "pipfile", "gemfile", "build.gradle", "pom.xml", ".gitignore",
    ".prettierrc", ".prettierignore", ".editorconfig",
}
_CONFIG_EXTS = {".toml", ".ini", ".cfg", ".lock", ".yaml", ".yml", ".json"}


def classify(relpath: str) -> str:
    """Return the file-kind category for a repo-relative POSIX path."""
    p = PurePosixPath(relpath)
    segs = {s.lower() for s in p.parts}
    name = p.name.lower()
    ext = p.suffix.lower()
    stem_no_ext = name[: -len(ext)] if ext else name

    if segs & _VENDOR_SEGMENTS:
        return "vendor"
    if (segs & _META_SEGMENTS) or name in _META_NAMES:
        return "meta"
    if segs & _TEST_SEGMENTS:
        return "test"
    if ".test." in name or ".spec." in name or name.startswith("test_"):
        return "test"
    if segs & _DOC_SEGMENTS:
        return "docs"
    if name in _CONFIG_NAMES or ext in _CONFIG_EXTS:
        return "config"
    if stem_no_ext.endswith(".config"):  # vite.config.ts, eslint.config.mjs
        return "config"
    if ext in _DOC_EXTS:
        return "docs"
    if ".example" in name or ".sample" in name:
        return "docs"
    return "source"
