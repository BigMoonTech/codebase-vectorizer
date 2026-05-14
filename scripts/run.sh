#!/usr/bin/env bash
# POSIX shim: find a usable Python 3.10-3.13 and hand off to bootstrap.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      ver=$("$candidate" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
      case "$ver" in
        3.10|3.11|3.12|3.13) echo "$candidate"; return 0 ;;
      esac
    fi
  done
  return 1
}

PY="$(find_python || true)"
if [ -z "${PY:-}" ]; then
  echo "codebase-vectorizer needs Python 3.10-3.13 on PATH." >&2
  echo "  Debian/Ubuntu/WSL: sudo apt install python3.12 python3.12-venv" >&2
  echo "  macOS:             brew install python@3.12" >&2
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/bootstrap.py" "$@"
