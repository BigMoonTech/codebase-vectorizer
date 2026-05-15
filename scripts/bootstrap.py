#!/usr/bin/env python3
"""Bootstrap launcher: ensure venv + deps, then dispatch to `python -m cbv`.

Invoked by run.sh (POSIX) or run.ps1 (Windows). Those shims find a
usable Python 3.10-3.13 on PATH and call this script.

This script:
  1. Verifies the running interpreter is Python 3.10-3.13.
  2. Creates the venv at <data_home>/python-env if missing.
  3. Installs deps into the venv with --only-binary=:all: where possible.
  4. Runs `python -m cbv <verb> [args...]` inside the venv by absolute
     path. The venv is never activated, so the user's shell, $PATH,
     project venvs, and cwd are untouched.

Stdlib-only — safe to run on Python 3.10-3.13 before any dep is installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cbv.paths import (  # noqa: E402
    data_home,
    list_indexed_repos,
    python_env_dir,
    python_env_executable,
    repos_dir,
)

REQS = SCRIPT_DIR / "requirements.txt"
SUPPORTED_PY = {(3, 10), (3, 11), (3, 12), (3, 13)}
ALLOWED_SUBCOMMANDS = {"vectorize", "query", "stats", "relate", "graph", "flow", "list"}
CORE_DEPENDENCY_PROBE = (
    "import sqlite_vec, transformers, sentence_transformers, numpy, pathspec, requests, "
    "huggingface_hub, tree_sitter, tree_sitter_language_pack, networkx"
)


def check_python_version() -> None:
    cur = sys.version_info[:2]
    if cur not in SUPPORTED_PY:
        supported = ", ".join(f"{a}.{b}" for a, b in sorted(SUPPORTED_PY))
        print(
            f"ERROR: codebase-vectorizer needs Python 3.10-3.13 "
            f"(got {cur[0]}.{cur[1]}).\n"
            f"Supported: {supported}\n"
            f"  Windows:       winget install Python.Python.3.12\n"
            f"  Debian/Ubuntu: sudo apt install python3.12 python3.12-venv\n"
            f"  macOS:         brew install python@3.12",
            file=sys.stderr,
        )
        sys.exit(2)


def ensure_venv() -> None:
    if python_env_executable().exists():
        return
    target = python_env_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"[bootstrap] creating Python env at {target}", flush=True)
    builder = venv.EnvBuilder(
        with_pip=True,
        clear=False,
        symlinks=(os.name != "nt"),
        upgrade_deps=False,
    )
    builder.create(target)


def deps_installed(py: Path) -> bool:
    """Quick smoke check: import the v1.0 minimums.

    `llama_cpp` is optional when CUDA + torch are available (the GPU path).
    Probe both stacks and accept either: at least one runtime embedder must
    be importable. Without this, the bootstrap thrashes pip install on every
    invocation when llama_cpp isn't installable (e.g. Windows without VS).
    """
    if subprocess.run([str(py), "-c", CORE_DEPENDENCY_PROBE], capture_output=True).returncode != 0:
        return False
    parser_probe = (
        "from tree_sitter_language_pack import get_parser; "
        "p = get_parser('python'); "
        "p.parse(b'x = 1')"
    )
    if subprocess.run([str(py), "-c", parser_probe], capture_output=True).returncode != 0:
        return False
    cpu_ok = subprocess.run([str(py), "-c", "import llama_cpp"],
                            capture_output=True).returncode == 0
    gpu_ok = subprocess.run([str(py), "-c", "import torch"],
                            capture_output=True).returncode == 0
    return cpu_ok or gpu_ok
    return r.returncode == 0


def install_deps(py: Path) -> None:
    if not REQS.exists():
        print(f"ERROR: requirements.txt not found at {REQS}", file=sys.stderr)
        sys.exit(1)
    print(f"[bootstrap] installing deps into {python_env_dir()} "
          f"(prebuilt wheels preferred)", flush=True)
    cmd = [str(py), "-m", "pip", "install",
           "-r", str(REQS),
           "--upgrade",
           "--only-binary=:all:",
           "--disable-pip-version-check"]
    r = subprocess.run(cmd)
    if r.returncode == 0:
        return
    print("[bootstrap] binary-only install failed; retrying allowing source builds.",
          flush=True)
    cmd_src = [str(py), "-m", "pip", "install",
               "-r", str(REQS),
               "--upgrade",
               "--disable-pip-version-check"]
    r = subprocess.run(cmd_src)
    if r.returncode != 0:
        print(
            "[bootstrap] FAILED. Likely cause: your Python has no prebuilt wheel "
            "for one of the deps (often llama-cpp-python or torch). Install Python "
            "3.12 and re-run; the launcher picks it up automatically.",
            file=sys.stderr,
        )
        sys.exit(r.returncode)


def ensure_ready() -> Path:
    check_python_version()
    ensure_venv()
    py = python_env_executable()
    if not deps_installed(py):
        install_deps(py)
    return py


def cmd_info() -> int:
    """Inlined here so `info` works before the venv exists.
    Mirrors cbv.commands.info; kept in sync by Task 12's tests."""
    print(f"data_home:        {data_home()}")
    print(f"python_env:       {python_env_dir()}")
    print(f"python_env_bin:   {python_env_executable()}")
    print(f"python_env_ready: {python_env_executable().exists()}")
    print(f"repos_dir:        {repos_dir()}")
    repos = list_indexed_repos()
    print(f"indexed_repos:    {len(repos)}")
    for r in repos:
        print(f"  - {r.name}  @  {r}")
    return 0


def usage() -> int:
    print(
        "Usage: bootstrap.py {setup|vectorize|query|stats|relate|graph|flow|list|info} [args...]\n"
        "  setup                       create venv and install deps (idempotent)\n"
        "  vectorize <url|path>        index a repo\n"
        "  query <name> <question>     query an indexed repo\n"
        "  stats <name>                print counts and top PageRank nodes\n"
        "  relate <name> <verb> ...    run graph relationship queries\n"
        "  graph <name> <symbol>       alias for relate neighbors\n"
        "  flow <name> <symbol>        alias for relate paths-through\n"
        "  list                        list every indexed repo\n"
        "  info                        print all paths and readiness",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    if len(sys.argv) < 2:
        return usage()

    subcmd = sys.argv[1]
    rest = sys.argv[2:]

    if subcmd == "info":
        return cmd_info()

    py = ensure_ready()

    if subcmd == "setup":
        print("[bootstrap] OK", flush=True)
        return 0

    if subcmd not in ALLOWED_SUBCOMMANDS:
        print(f"Unknown subcommand: {subcmd}\n", file=sys.stderr)
        return usage()

    r = subprocess.run([str(py), "-m", "cbv", subcmd, *rest],
                       env={**os.environ, "PYTHONPATH": str(SCRIPT_DIR)})
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
