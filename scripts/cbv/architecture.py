from __future__ import annotations

import json
import os
import subprocess
from abc import ABC, abstractmethod
from typing import Any


class ArchitectureWriter(ABC):
    @abstractmethod
    def write(self, payload: dict) -> str:
        """Return markdown architecture text for an indexed repository."""


class LocalLLMArchitectureWriter(ArchitectureWriter):
    def write(self, payload: dict) -> str:
        command = os.environ.get("CBV_ARCHITECTURE_COMMAND")
        if not command:
            raise RuntimeError("local LLM architecture writer is not configured")
        timeout = float(os.environ.get("CBV_ARCHITECTURE_TIMEOUT_SECONDS", "30"))

        try:
            result = subprocess.run(
                command,
                input=json.dumps(payload, sort_keys=True),
                text=True,
                capture_output=True,
                shell=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"local LLM architecture writer timed out after {timeout:g} seconds"
            ) from e
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise RuntimeError(f"local LLM architecture writer failed: {detail}")

        markdown = result.stdout.strip()
        if not markdown:
            raise RuntimeError("local LLM architecture writer returned empty output")
        return markdown + "\n"


def render_architecture(payload: dict, writer: ArchitectureWriter) -> tuple[str, str | None]:
    try:
        return writer.write(payload), None
    except Exception as e:
        return (
            _fallback(payload),
            f"LLM architecture generation failed; used deterministic fallback: {e}",
        )


def _fallback(payload: dict) -> str:
    repo_name = str(payload.get("repo_name") or "Repository")
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    top_nodes = payload.get("top_nodes")
    if not isinstance(top_nodes, list):
        top_nodes = []

    lines = [
        f"# {repo_name} Architecture",
        "",
        "## Index Summary",
        "",
        f"- Chunks: {_count(counts, 'chunks')}",
        f"- Symbol nodes: {_count(counts, 'nodes_symbol', 'symbol_nodes')}",
        f"- Symbol edges: {_count(counts, 'edges_symbol', 'symbol_edges')}",
        f"- Flow nodes: {_count(counts, 'nodes_block', 'flow_nodes')}",
        f"- Flow edges: {_count(counts, 'edges_flow', 'flow_edges')}",
        f"- Clusters: {_count(counts, 'clusters')}",
        "",
        "## Central Symbols",
        "",
    ]

    if top_nodes:
        for node in top_nodes[:20]:
            if isinstance(node, dict):
                lines.append(f"- {_node_label(node)}")
    else:
        lines.append("- No central symbols were indexed.")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "This deterministic fallback was generated from the index metadata.",
            "",
        ]
    )
    return "\n".join(lines)


def _count(counts: dict[str, Any], key: str, *aliases: str) -> int:
    for candidate in (key, *aliases):
        if candidate in counts:
            try:
                return int(counts.get(candidate, 0) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _node_label(node: dict[str, Any]) -> str:
    name = str(node.get("name") or "(unnamed)")
    kind = str(node.get("kind") or "symbol")
    pagerank = node.get("pagerank")
    if pagerank is None:
        return f"{name} ({kind})"
    try:
        return f"{name} ({kind}, pagerank {float(pagerank):.6f})"
    except (TypeError, ValueError):
        return f"{name} ({kind})"
