"""Tests for cbv.paths — pure path resolution, no I/O against real
filesystem locations. We override env vars per test with monkeypatch
to avoid touching the user's actual data home.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# scripts/ on sys.path so `from cbv import paths` resolves the way
# bootstrap.py will at runtime.
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv import paths  # noqa: E402


def _clear_env(monkeypatch):
    for k in ("CODEBASE_VECTORIZER_HOME", "CLAUDE_PLUGIN_DATA",
              "XDG_DATA_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(k, raising=False)


def test_data_home_uses_codebase_vectorizer_home_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "custom"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "ignored"))
    assert paths.data_home() == (tmp_path / "custom").resolve()


def test_data_home_uses_claude_plugin_data_when_no_override(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "plugin"))
    assert paths.data_home() == (tmp_path / "plugin").resolve()


def test_data_home_falls_back_to_platform_default(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
        assert paths.data_home() == tmp_path / "appdata" / "codebase-vectorizer"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert paths.data_home() == (tmp_path / "xdg").resolve() / "codebase-vectorizer"


def test_repos_dir_under_data_home(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.repos_dir() == tmp_path.resolve() / "repos"


def test_repo_dir_combines_name(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.repo_dir("myrepo") == tmp_path.resolve() / "repos" / "myrepo"


def test_find_repo_returns_none_when_missing(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.find_repo("nope") is None


def test_find_repo_returns_dir_when_index_present(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    repo = tmp_path.resolve() / "repos" / "yes"
    repo.mkdir(parents=True)
    (repo / "index.sqlite").write_bytes(b"")
    assert paths.find_repo("yes") == repo


def test_list_indexed_repos_filters_to_dirs_with_index(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    repos = tmp_path.resolve() / "repos"
    (repos / "a").mkdir(parents=True)
    (repos / "a" / "index.sqlite").write_bytes(b"")
    (repos / "b").mkdir(parents=True)  # no index.sqlite
    (repos / "stray.txt").write_text("not a dir")
    listed = paths.list_indexed_repos()
    assert [p.name for p in listed] == ["a"]


def test_python_env_executable_layout(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    exe = paths.python_env_executable()
    if os.name == "nt":
        assert exe == tmp_path.resolve() / "python-env" / "Scripts" / "python.exe"
    else:
        assert exe == tmp_path.resolve() / "python-env" / "bin" / "python"


def test_embedding_cache_path_under_data_home(monkeypatch, tmp_path):
    """Slice 11 populates this; Slice 1 just reserves the location."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path))
    assert paths.embedding_cache_path() == tmp_path.resolve() / "embedding_cache.sqlite"
