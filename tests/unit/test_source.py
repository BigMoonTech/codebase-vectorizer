"""Tests for cbv.source — resolving a URL or local path into source/.

Git clone tests are network-bound and slow; they're gated by an env var.
Local-copy tests are pure-stdlib and always run.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import source  # noqa: E402


def test_is_git_url_recognizes_https():
    assert source.is_git_url("https://github.com/x/y.git")
    assert source.is_git_url("https://github.com/x/y")
    assert source.is_git_url("git@github.com:x/y.git")


def test_is_git_url_rejects_local_paths(tmp_path):
    assert not source.is_git_url(str(tmp_path))
    assert not source.is_git_url(".")
    assert not source.is_git_url("relative/path/here")


def test_derive_repo_name_from_url():
    assert source.derive_repo_name("https://github.com/owner/myrepo.git") == "myrepo"
    assert source.derive_repo_name("https://github.com/owner/myrepo") == "myrepo"
    assert source.derive_repo_name("git@github.com:owner/myrepo.git") == "myrepo"


def test_derive_repo_name_from_local_path(tmp_path):
    src = tmp_path / "myproject"
    src.mkdir()
    assert source.derive_repo_name(str(src)) == "myproject"


def test_copy_local_into_source(tmp_path):
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    (src / ".git").mkdir()
    (src / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (src / "sub").mkdir()
    (src / "sub" / "b.py").write_text("y=2\n")

    dest = tmp_path / "repo" / "source"
    sha = source.populate_from_local(src, dest)

    assert (dest / "a.py").read_text() == "x=1\n"
    assert (dest / "sub" / "b.py").read_text() == "y=2\n"
    assert not (dest / ".git").exists(), ".git should be skipped on local copy"
    assert sha == "", "local copy without git metadata yields no commit_sha"


def test_copy_local_captures_commit_sha_if_git_present(tmp_path):
    # Init a real git repo with one commit
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(src), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(src), "add", "a.py"], check=True)
    subprocess.run(["git", "-C", str(src), "commit", "-qm", "init"], check=True)
    expected_sha = subprocess.check_output(
        ["git", "-C", str(src), "rev-parse", "HEAD"], text=True).strip()

    dest = tmp_path / "repo" / "source"
    sha = source.populate_from_local(src, dest)
    assert sha == expected_sha
    assert not (dest / ".git").exists()


@pytest.mark.skipif(
    os.environ.get("CBV_RUN_NETWORK_TESTS") != "1",
    reason="network test; set CBV_RUN_NETWORK_TESTS=1 to enable",
)
def test_clone_url(tmp_path):
    dest = tmp_path / "repo" / "source"
    sha = source.populate_from_url(
        "https://github.com/octocat/Hello-World.git", dest
    )
    assert dest.is_dir()
    assert (dest / "README").exists()
    assert len(sha) == 40
