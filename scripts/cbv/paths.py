"""Path resolution for codebase-vectorizer.

All plugin state lives under a single root, in this order of preference:

  1. $CODEBASE_VECTORIZER_HOME    (user override / debugging)
  2. $CLAUDE_PLUGIN_DATA           (set by Claude Code; canonical)
  3. Platform default fallback     (running outside a Claude Code session)

Underneath that root:

  <root>/python-env/         the plugin's isolated venv (never activated)
  <root>/repos/<name>/       per-indexed-repo state
  <root>/embedding_cache.sqlite   cross-repo cache (populated in Slice 11)

Stdlib-only so bootstrap.py can import this before the venv exists.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


def data_home() -> Path:
    explicit = os.environ.get("CODEBASE_VECTORIZER_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "codebase-vectorizer"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "codebase-vectorizer"
    return Path.home() / ".local" / "share" / "codebase-vectorizer"


def python_env_dir() -> Path:
    return data_home() / "python-env"


def python_env_executable() -> Path:
    base = python_env_dir()
    if os.name == "nt":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def repos_dir() -> Path:
    return data_home() / "repos"


def repo_dir(repo_name: str) -> Path:
    return repos_dir() / repo_name


def find_repo(repo_name: str) -> Optional[Path]:
    candidate = repo_dir(repo_name)
    if (candidate / "index.sqlite").exists():
        return candidate
    return None


def list_indexed_repos() -> List[Path]:
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


def embedding_cache_path() -> Path:
    """Reserved for Slice 11. Returns the canonical location."""
    return data_home() / "embedding_cache.sqlite"
