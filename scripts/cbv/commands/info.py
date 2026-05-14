"""`info` verb — print plugin paths + readiness for debugging."""
from __future__ import annotations

import argparse

from cbv import paths


def run(_ns: argparse.Namespace) -> int:
    print(f"data_home:        {paths.data_home()}")
    print(f"python_env:       {paths.python_env_dir()}")
    print(f"python_env_bin:   {paths.python_env_executable()}")
    print(f"python_env_ready: {paths.python_env_executable().exists()}")
    print(f"repos_dir:        {paths.repos_dir()}")
    repos = paths.list_indexed_repos()
    print(f"indexed_repos:    {len(repos)}")
    for r in repos:
        print(f"  - {r.name}  @  {r}")
    return 0
