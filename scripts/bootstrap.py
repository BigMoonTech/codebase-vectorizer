#!/usr/bin/env python3
"""Bootstrap launcher: ensure venv + deps, then dispatch to the requested action.

Invoked by run.sh (POSIX) or run.ps1 (Windows). Those shims find a usable
Python 3.10-3.13 on PATH and call this script.

This script then:
  1. Creates the venv at <data_home>/python-env if missing.
  2. Installs deps into the venv with --only-binary=:all: (forces prebuilt wheels).
  3. Runs the requested subcommand (vectorize / query / list / info / setup)
     using the venv python by absolute path. The venv is never activated.

Stdlib-only — safe to run on Python 3.10-3.13.
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

from paths import (  # noqa: E402
    data_home,
    list_indexed_repos,
    python_env_dir,
    python_env_executable,
    repos_dir,
)

REQS = SCRIPT_DIR / "requirements.txt"
SUPPORTED_PY = {(3, 10), (3, 11), (3, 12), (3, 13)}


def check_python_version() -> None:
    cur = sys.version_info[:2]
    if cur not in SUPPORTED_PY:
        supported = ", ".join(f"{a}.{b}" for a, b in sorted(SUPPORTED_PY))
        print(
            f"ERROR: codebase-vectorizer needs Python 3.10-3.13 (got {cur[0]}.{cur[1]}).\n"
            f"Supported: {supported}\n"
            f"  Windows:        winget install Python.Python.3.12\n"
            f"  Debian/Ubuntu:  sudo apt install python3.12 python3.12-venv\n"
            f"  macOS:          brew install python@3.12",
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
    r = subprocess.run(
        [str(py), "-c", "import fastembed, sqlite_vec, requests"],
        capture_output=True,
    )
    return r.returncode == 0


def install_deps(py: Path) -> None:
    if not REQS.exists():
        print(f"ERROR: requirements.txt not found at {REQS}", file=sys.stderr)
        sys.exit(1)
    print(f"[bootstrap] installing deps into {python_env_dir()} (prebuilt wheels only)", flush=True)
    cmd = [
        str(py), "-m", "pip", "install",
        "-r", str(REQS),
        "--upgrade",
        "--only-binary=:all:",
        "--disable-pip-version-check",
    ]
    r = subprocess.run(cmd)
    if r.returncode == 0:
        return
    # Rare: no prebuilt wheel for the user's platform. Allow source build.
    print(
        "[bootstrap] binary-only install failed; retrying with source builds allowed.",
        flush=True,
    )
    cmd_src = [
        str(py), "-m", "pip", "install",
        "-r", str(REQS),
        "--upgrade",
        "--disable-pip-version-check",
    ]
    r = subprocess.run(cmd_src)
    if r.returncode != 0:
        print(
            "[bootstrap] FAILED. Most likely cause: your Python has no prebuilt wheel "
            "for one of the deps (typically py-rust-stemmers). Install Python 3.12 "
            "and re-run; the launcher will pick it up.",
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
    print(f"data_home:       {data_home()}")
    print(f"python_env:      {python_env_dir()}")
    print(f"python_env_bin:  {python_env_executable()}")
    print(f"python_env_ready: {python_env_executable().exists()}")
    print(f"repos_dir:       {repos_dir()}")
    repos = list_indexed_repos()
    print(f"indexed_repos:   {len(repos)}")
    for r in repos:
        print(f"  - {r.name}  @  {r}")
    return 0


def cmd_list() -> int:
    repos = list_indexed_repos()
    if not repos:
        print("No indexed repos found.")
        print(f"  Searched: {repos_dir()}")
        return 0
    for r in repos:
        print(f"{r.name}\t{r}")
    return 0


def usage() -> int:
    print(
        "Usage: bootstrap.py {setup|vectorize|query|list|info} [args...]\n"
        "  setup                  — create venv and install deps (idempotent)\n"
        "  vectorize <url|path>   — index a repo into <data_home>/repos/<name>/\n"
        "  query <name> <q>       — query an indexed repo (see query.py --help)\n"
        "  list                   — list every indexed repo\n"
        "  info                   — print all paths and readiness (debugging)",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    if len(sys.argv) < 2:
        return usage()

    subcmd = sys.argv[1]
    rest = sys.argv[2:]

    # `info` is read-only, doesn't need the venv.
    if subcmd == "info":
        return cmd_info()

    py = ensure_ready()

    if subcmd == "setup":
        print("[bootstrap] OK", flush=True)
        return 0
    if subcmd == "list":
        return cmd_list()

    target_map = {
        "vectorize": SCRIPT_DIR / "vectorize.py",
        "query": SCRIPT_DIR / "query.py",
    }
    target = target_map.get(subcmd)
    if target is None:
        print(f"Unknown subcommand: {subcmd}\n", file=sys.stderr)
        return usage()

    # Exec the target inside the venv by absolute path — no activation.
    r = subprocess.run([str(py), str(target), *rest])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
