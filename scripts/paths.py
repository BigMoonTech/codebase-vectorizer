r"""Shared path helpers for the codebase-vectorizer plugin.

All plugin state lives under a single root, in this order of preference:

  1. $CODEBASE_VECTORIZER_HOME           (user override, debugging)
  2. $CLAUDE_PLUGIN_DATA                  (set by Claude Code per plugin; canonical)
  3. Platform default fallback            (running outside a Claude Code session)

Underneath that root:

  <root>/python-env/    — the plugin's isolated Python interpreter + deps
  <root>/repos/<name>/  — each indexed codebase (source + index.sqlite + manifest + ARCHITECTURE.md)

The venv directory is deliberately named `python-env`, not `.venv`, so it
cannot be confused with any project's own virtual environment. The plugin
NEVER activates this venv — its python is always called by absolute path,
so the user's shell, $PATH, $VIRTUAL_ENV, and project venvs are untouched.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


def data_home() -> Path:
    """Root directory for all plugin state (venv + indexed repos)."""
    explicit = os.environ.get("CODEBASE_VECTORIZER_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data).expanduser().resolve()
    # Fallback when running outside a Claude Code session.
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "codebase-vectorizer"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "codebase-vectorizer"
    return Path.home() / ".local" / "share" / "codebase-vectorizer"


def python_env_dir() -> Path:
    """Path to the plugin's Python virtual environment. NOT named .venv."""
    return data_home() / "python-env"


def python_env_executable() -> Path:
    base = python_env_dir()
    if os.name == "nt":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def repos_dir() -> Path:
    """Where indexed repos live, one subdirectory per repo."""
    return data_home() / "repos"


def find_repo(repo_name: str) -> Optional[Path]:
    """Locate an indexed repo by name. Returns its directory or None."""
    candidate = repos_dir() / repo_name
    if (candidate / "index.sqlite").exists():
        return candidate
    return None


def list_indexed_repos() -> List[Path]:
    """All indexed repos under repos_dir()."""
    out: List[Path] = []
    base = repos_dir()
    if not base.exists():
        return out
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if (child / "index.sqlite").exists():
            out.append(child)
    return out
