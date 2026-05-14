"""Resolve a URL or a local path into a populated <repo>/source/ dir.

is_git_url    — heuristic URL classifier
derive_repo_name — last segment without .git suffix
populate_from_url   — git clone --depth 1 into dest
populate_from_local — copytree skipping .git, capture commit_sha if avail
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

_URL_RE = re.compile(r"^(?:https?://|git@|ssh://|git://)")


def is_git_url(s: str) -> bool:
    return bool(_URL_RE.match(s.strip()))


def derive_repo_name(spec: str) -> str:
    """Last path segment without trailing .git."""
    s = spec.strip().rstrip("/")
    if is_git_url(s):
        if s.endswith(".git"):
            s = s[:-4]
        return s.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return Path(s).name


def populate_from_url(url: str, dest: Path) -> str:
    """git clone --depth 1 into dest, return HEAD commit_sha.

    The caller is responsible for ensuring `dest` does not already exist;
    we refuse rather than silently destroy data. On partial failure
    (e.g. clone succeeds but `rev-parse HEAD` does not), any partially
    populated `dest` is cleaned up so a retry starts from a known state.
    """
    if dest.exists():
        raise FileExistsError(
            f"dest already exists: {dest}. Remove it before re-cloning."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", url, str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"git clone failed for {url!r}:\n{r.stderr.strip()}"
        )
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(dest), "rev-parse", "HEAD"], text=True
        ).strip()
        # Remove .git/ — we don't need history; it's just bytes from now on.
        shutil.rmtree(dest / ".git", ignore_errors=True)
        return sha
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def populate_from_local(src: Path, dest: Path) -> str:
    """Recursive copy of src into dest, skipping .git/. Return commit_sha if
    src was a git repo and HEAD resolves; else empty string.

    The caller is responsible for ensuring `dest` does not already exist;
    we refuse rather than silently destroy data.
    """
    src = src.resolve()
    if not src.is_dir():
        raise NotADirectoryError(src)
    if dest.exists():
        raise FileExistsError(
            f"dest already exists: {dest}. Remove it before re-copying."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)

    def ignore(_root: str, names: list[str]) -> list[str]:
        return [".git"] if ".git" in names else []

    shutil.copytree(src, dest, ignore=ignore, symlinks=False)

    sha = ""
    if (src / ".git").exists():
        try:
            sha = subprocess.check_output(
                ["git", "-C", str(src), "rev-parse", "HEAD"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            sha = ""
    return sha
