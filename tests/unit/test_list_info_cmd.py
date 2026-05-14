"""Tests for cbv.commands.list_cmd and cbv.commands.info."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv.commands import list_cmd, info as info_cmd  # noqa: E402


@pytest.fixture
def home_with_repos(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "home"))
    repos = tmp_path / "home" / "repos"
    for name in ("alpha", "beta"):
        (repos / name).mkdir(parents=True)
        (repos / name / "index.sqlite").write_bytes(b"")
    return repos


def test_list_prints_repo_names(home_with_repos, capsys):
    rc = list_cmd.run(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" in out


def test_list_handles_empty(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CODEBASE_VECTORIZER_HOME", str(tmp_path / "empty"))
    rc = list_cmd.run(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    assert "No indexed repos" in out


def test_info_prints_paths(home_with_repos, capsys):
    rc = info_cmd.run(argparse.Namespace())
    assert rc == 0
    out = capsys.readouterr().out
    for k in ("data_home:", "python_env:", "repos_dir:", "indexed_repos:"):
        assert k in out
    assert "alpha" in out
    assert "beta" in out
