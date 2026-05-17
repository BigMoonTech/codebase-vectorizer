from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cbv.classify import classify  # noqa: E402


def test_classifies_the_concrete_pollution_examples():
    cases = {
        "scripts/cbv/clusters.py": "source",
        "src/app/main.go": "source",
        "tests/unit/test_clusters.py": "test",
        "tests/fixtures/simple-python/main.py": "test",
        "packages/web/src/Button.spec.tsx": "test",
        "docs/HANDOFF.md": "docs",
        "docs/plans/2026-05-16-intent.md": "docs",
        "README.md": "docs",
        "specs/2026-05-14-design.md": "docs",
        ".claude/skills/foo/SKILL.md": "meta",
        ".cursor/rules.md": "meta",
        "CLAUDE.md": "meta",
        ".github/workflows/ci.yml": "config",
        "package.json": "config",
        "frontend/package.json": "config",
        "Dockerfile": "config",
        "vite.config.ts": "config",
        "pyproject.toml": "config",
        "node_modules/react/index.js": "vendor",
        "vendor/github.com/pkg/errors.go": "vendor",
    }
    for path, expected in cases.items():
        assert classify(path) == expected, f"{path} -> {classify(path)}, want {expected}"
