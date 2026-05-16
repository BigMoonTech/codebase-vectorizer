"""Tests for the verb dispatcher's argument parsing only.

The actual command implementations are tested in their own modules.
This test asserts that `python -m cbv <verb> ...` parses without
error and dispatches to a function registered by the verb name.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from cbv import cli  # noqa: E402
import bootstrap  # noqa: E402


def test_cli_known_verbs():
    """All Slice 1 verbs are registered on the parser."""
    parser = cli.build_parser()
    actions = {a.dest: a for a in parser._actions}
    sub = next(a for a in parser._actions if a.dest == "verb")
    choices = set(sub.choices.keys())
    assert {"vectorize", "query", "stats", "list", "info", "relate", "graph", "flow", "bench"} <= choices


def test_cli_dispatch_table_has_all_verbs():
    """Every parser choice has a callable in the dispatch table."""
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "verb")
    for verb in sub.choices.keys():
        assert verb in cli.DISPATCH, f"missing dispatcher for {verb!r}"
        assert callable(cli.DISPATCH[verb])


def test_cli_parses_vectorize_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["vectorize", "https://github.com/x/y"])
    assert ns.verb == "vectorize"
    assert ns.source == "https://github.com/x/y"
    assert ns.no_cache is False


def test_cli_parses_vectorize_no_cache_flag():
    parser = cli.build_parser()
    ns = parser.parse_args(["vectorize", "https://github.com/x/y", "--no-cache"])
    assert ns.verb == "vectorize"
    assert ns.source == "https://github.com/x/y"
    assert ns.no_cache is True


def test_cli_parses_vectorize_bench_flag():
    parser = cli.build_parser()
    ns = parser.parse_args(["vectorize", "https://github.com/x/y", "--bench"])
    assert ns.verb == "vectorize"
    assert ns.source == "https://github.com/x/y"
    assert ns.bench is True


def test_cli_parses_query_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["query", "myrepo", "how does auth work", "--top-k", "5"])
    assert ns.verb == "query"
    assert ns.repo == "myrepo"
    assert ns.question == "how does auth work"
    assert ns.top_k == 5


def test_cli_query_top_k_default():
    parser = cli.build_parser()
    ns = parser.parse_args(["query", "r", "q"])
    assert ns.top_k == 10


def test_cli_parses_stats_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["stats", "myrepo", "--top-k", "5"])
    assert ns.verb == "stats"
    assert ns.repo == "myrepo"
    assert ns.top_k == 5


def test_cli_parses_bench_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["bench", "myrepo"])
    assert ns.verb == "bench"
    assert ns.repo == "myrepo"


def test_cli_parses_relate_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["relate", "myrepo", "callers", "authenticate_user", "--top-k", "5"])
    assert ns.verb == "relate"
    assert ns.repo == "myrepo"
    assert ns.relate_verb == "callers"
    assert ns.query == "authenticate_user"
    assert ns.top_k == 5


def test_cli_parses_graph_alias_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["graph", "myrepo", "authenticate_user", "--hops", "2"])
    assert ns.verb == "graph"
    assert ns.repo == "myrepo"
    assert ns.query == "authenticate_user"
    assert ns.hops == 2


def test_cli_parses_flow_alias_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["flow", "myrepo", "authenticate_user"])
    assert ns.verb == "flow"
    assert ns.repo == "myrepo"
    assert ns.query == "authenticate_user"


def test_bootstrap_usage_and_allowlist_include_stats(capsys):
    assert "stats" in bootstrap.ALLOWED_SUBCOMMANDS
    assert "relate" in bootstrap.ALLOWED_SUBCOMMANDS
    assert "graph" in bootstrap.ALLOWED_SUBCOMMANDS
    assert "flow" in bootstrap.ALLOWED_SUBCOMMANDS
    assert "bench" in bootstrap.ALLOWED_SUBCOMMANDS
    bootstrap.usage()
    err = capsys.readouterr().err
    assert "stats <name>" in err
    assert "relate <name>" in err
    assert "graph <name>" in err
    assert "flow <name>" in err
    assert "bench <name>" in err


def test_bootstrap_core_dependency_probe_includes_networkx():
    assert "networkx" in bootstrap.CORE_DEPENDENCY_PROBE


def test_cli_unknown_verb_errors(capsys):
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["nonsense"])


def test_cli_parses_llm_payload_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["llm-payload", "myrepo"])
    assert ns.verb == "llm-payload"
    assert ns.repo == "myrepo"


def test_cli_parses_apply_llm_artifacts_args():
    parser = cli.build_parser()
    ns = parser.parse_args(["apply-llm-artifacts", "myrepo", "result.json"])
    assert ns.verb == "apply-llm-artifacts"
    assert ns.repo == "myrepo"
    assert ns.result_path == "result.json"


def test_bootstrap_allowlist_includes_llm_verbs():
    assert "llm-payload" in bootstrap.ALLOWED_SUBCOMMANDS
    assert "apply-llm-artifacts" in bootstrap.ALLOWED_SUBCOMMANDS


# --- GPU-aware bootstrap install plan -------------------------------------


class _FakeProc:
    def __init__(self, returncode):
        self.returncode = returncode


def test_detect_gpu_false_when_force_cpu(monkeypatch):
    """CBV_FORCE_CPU=1 forces the CPU stack even if a GPU is present."""
    monkeypatch.setenv("CBV_FORCE_CPU", "1")
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    assert bootstrap.detect_gpu() is False


def test_detect_gpu_false_when_no_nvidia_smi(monkeypatch):
    monkeypatch.delenv("CBV_FORCE_CPU", raising=False)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: None)
    assert bootstrap.detect_gpu() is False


def test_detect_gpu_true_when_nvidia_smi_succeeds(monkeypatch):
    monkeypatch.delenv("CBV_FORCE_CPU", raising=False)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: _FakeProc(0))
    assert bootstrap.detect_gpu() is True


def test_detect_gpu_false_when_nvidia_smi_errors(monkeypatch):
    monkeypatch.delenv("CBV_FORCE_CPU", raising=False)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: _FakeProc(9))
    assert bootstrap.detect_gpu() is False


def test_torch_index_url_gpu_vs_cpu(monkeypatch):
    monkeypatch.delenv("CBV_TORCH_INDEX_URL", raising=False)
    assert "cu128" in bootstrap.torch_index_url(gpu=True)
    assert bootstrap.torch_index_url(gpu=False).endswith("/cpu")


def test_torch_index_url_respects_override(monkeypatch):
    monkeypatch.setenv("CBV_TORCH_INDEX_URL", "https://example.invalid/whl/cu121")
    assert bootstrap.torch_index_url(gpu=True) == "https://example.invalid/whl/cu121"
    assert bootstrap.torch_index_url(gpu=False) == "https://example.invalid/whl/cu121"


def test_build_install_plan_gpu_skips_llama_and_uses_cuda_index(monkeypatch):
    monkeypatch.delenv("CBV_TORCH_INDEX_URL", raising=False)
    plan = bootstrap.build_install_plan(gpu=True)
    assert len(plan) == 2
    torch_step, core_step = plan
    assert torch_step[0] == "torch>=2.3"
    assert "--index-url" in torch_step
    assert bootstrap.CUDA_TORCH_INDEX in torch_step
    assert "-r" in core_step
    # llama-cpp-python is never installed on the GPU stack.
    assert not any("llama-cpp-python" in arg for step in plan for arg in step)


def test_build_install_plan_cpu_installs_llama_from_wheel_index(monkeypatch):
    monkeypatch.delenv("CBV_TORCH_INDEX_URL", raising=False)
    monkeypatch.delenv("CBV_LLAMA_INDEX_URL", raising=False)
    plan = bootstrap.build_install_plan(gpu=False)
    assert len(plan) == 3
    torch_step, _core_step, llama_step = plan
    assert bootstrap.CPU_TORCH_INDEX in torch_step
    assert llama_step[0] == "llama-cpp-python>=0.2.80"
    assert "--extra-index-url" in llama_step
    assert bootstrap.LLAMA_CPU_WHEEL_INDEX in llama_step
    # Wheel-only: the CPU stack never triggers a source build of llama-cpp-python.
    assert "--only-binary=:all:" in llama_step


def test_build_install_plan_cpu_respects_llama_index_override(monkeypatch):
    monkeypatch.setenv("CBV_LLAMA_INDEX_URL", "https://example.invalid/llama/whl")
    llama_step = bootstrap.build_install_plan(gpu=False)[-1]
    assert "https://example.invalid/llama/whl" in llama_step


def test_requirements_txt_excludes_torch_and_llama():
    """torch and llama-cpp-python must NOT be plain requirements — bootstrap
    installs them separately with platform-correct wheel indexes."""
    text = bootstrap.REQS.read_text(encoding="utf-8")
    requirement_lines = [
        ln.strip() for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    joined = "\n".join(requirement_lines)
    assert "torch" not in joined
    assert "llama" not in joined
    assert any(ln.startswith("transformers") for ln in requirement_lines)
