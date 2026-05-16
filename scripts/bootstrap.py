#!/usr/bin/env python3
"""Bootstrap launcher: ensure venv + deps, then dispatch to `python -m cbv`.

Invoked by run.sh (POSIX) or run.ps1 (Windows). Those shims find a
usable Python 3.10-3.13 on PATH and call this script.

This script:
  1. Verifies the running interpreter is Python 3.10-3.13.
  2. Creates the venv at <data_home>/python-env if missing.
  3. Installs deps into the venv from prebuilt wheels: torch from a CUDA
     or CPU wheel index depending on NVIDIA-GPU detection, the core
     requirements, then (CPU stack only) llama-cpp-python.
  4. Runs `python -m cbv <verb> [args...]` inside the venv by absolute
     path. The venv is never activated, so the user's shell, $PATH,
     project venvs, and cwd are untouched.

Stdlib-only — safe to run on Python 3.10-3.13 before any dep is installed.
"""
from __future__ import annotations

import os
import shutil
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
ALLOWED_SUBCOMMANDS = {"vectorize", "query", "stats", "bench", "relate", "graph", "flow",
                       "llm-payload", "apply-llm-artifacts", "list"}
CORE_DEPENDENCY_PROBE = (
    "import sqlite_vec, transformers, sentence_transformers, numpy, pathspec, requests, "
    "huggingface_hub, tree_sitter, tree_sitter_language_pack, networkx, umap, hdbscan"
)
# torch wheel indexes. cu128 covers Blackwell (RTX 50-series) and older
# NVIDIA cards; CBV_TORCH_INDEX_URL overrides for other CUDA series / ROCm.
CUDA_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
# Prebuilt llama-cpp-python wheels (CPU embedder backend). PyPI has none
# for Windows; this index has wheels for every supported platform.
LLAMA_CPU_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"


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


def detect_gpu() -> bool:
    """True when an NVIDIA GPU is available for the CUDA torch path.

    CBV_FORCE_CPU=1 forces the CPU stack — the same flag the embedder
    honors at runtime, so install-time and run-time stay consistent.
    Otherwise probe `nvidia-smi`: present on PATH and exiting 0 means a
    working driver. Any probe failure is treated as "no GPU" so the
    bootstrap degrades to the CPU stack rather than erroring.
    """
    if os.environ.get("CBV_FORCE_CPU") == "1":
        return False
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False
    try:
        return subprocess.run(
            [nvidia_smi], capture_output=True, timeout=30
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def torch_index_url(gpu: bool) -> str:
    """pip index URL for the torch wheel. CBV_TORCH_INDEX_URL overrides
    (e.g. a different CUDA series, or a ROCm index)."""
    override = os.environ.get("CBV_TORCH_INDEX_URL")
    if override:
        return override
    return CUDA_TORCH_INDEX if gpu else CPU_TORCH_INDEX


def build_install_plan(gpu: bool) -> list[list[str]]:
    """Ordered pip-install arg lists (without the `pip install` prefix).

    torch is installed first and explicitly, from a platform-correct
    wheel index, so the later `-r requirements.txt` step cannot let
    transformers/sentence-transformers pin the wrong (CPU-only) build.

    The GPU stack stops there — the GPU embedder needs only torch +
    transformers. The CPU stack additionally installs llama-cpp-python
    (the CPU embedder backend) from a prebuilt-wheel index, so a C/C++
    compiler is never required on any platform.
    """
    common = ["--upgrade", "--disable-pip-version-check"]
    plan = [
        ["torch>=2.3", "--index-url", torch_index_url(gpu), *common],
        ["-r", str(REQS), "--only-binary=:all:", *common],
    ]
    if not gpu:
        llama_index = os.environ.get("CBV_LLAMA_INDEX_URL", LLAMA_CPU_WHEEL_INDEX)
        plan.append([
            "llama-cpp-python>=0.2.80",
            "--extra-index-url", llama_index,
            "--only-binary=:all:",
            *common,
        ])
    return plan


def install_deps(py: Path) -> None:
    if not REQS.exists():
        print(f"ERROR: requirements.txt not found at {REQS}", file=sys.stderr)
        sys.exit(1)
    gpu = detect_gpu()
    stack = "GPU/CUDA" if gpu else "CPU"
    print(f"[bootstrap] installing deps into {python_env_dir()} "
          f"({stack} stack, prebuilt wheels)", flush=True)
    for args in build_install_plan(gpu):
        cmd = [str(py), "-m", "pip", "install", *args]
        if subprocess.run(cmd).returncode == 0:
            continue
        # Only the core requirements step may legitimately need a source
        # build (a dep lacking a wheel on some unusual Python); retry it
        # once. torch and llama-cpp-python are wheel-only by design — a
        # source build of those is exactly the failure mode being avoided.
        if "-r" in args:
            print("[bootstrap] wheel-only core install failed; "
                  "retrying with source builds allowed.", flush=True)
            retry = [a for a in cmd if a != "--only-binary=:all:"]
            if subprocess.run(retry).returncode == 0:
                continue
        print(
            "[bootstrap] FAILED to install dependencies.\n"
            f"  Failed step: pip install {' '.join(args)}\n"
            "  This is almost always one of:\n"
            "    - Python is not 3.10-3.13 (prebuilt wheels must exist for it)\n"
            "    - no network access to PyPI or the PyTorch wheel index\n"
            "  Both the torch index and the llama-cpp-python index ship\n"
            "  prebuilt wheels, so a C/C++ compiler is NOT required.",
            file=sys.stderr,
        )
        sys.exit(1)


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
    print(f"gpu_detected:     {detect_gpu()}")
    print(f"repos_dir:        {repos_dir()}")
    repos = list_indexed_repos()
    print(f"indexed_repos:    {len(repos)}")
    for r in repos:
        print(f"  - {r.name}  @  {r}")
    return 0


def usage() -> int:
    print(
        "Usage: bootstrap.py {setup|vectorize|query|stats|bench|relate|graph|flow|list|info} [args...]\n"
        "  setup                       create venv and install deps (idempotent)\n"
        "  vectorize <url|path>        index a repo\n"
        "  query <name> <question>     query an indexed repo\n"
        "  stats <name>                print counts and top PageRank nodes\n"
        "  bench <name>                run retrieval benchmark queries\n"
        "  relate <name> <verb> ...    run graph relationship queries\n"
        "  graph <name> <symbol>       alias for relate neighbors\n"
        "  flow <name> <symbol>        alias for relate paths-through\n"
        "  llm-payload <name>          print the LLM input payload for a repo\n"
        "  apply-llm-artifacts <name> <file>  write agent-generated labels/architecture\n"
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
