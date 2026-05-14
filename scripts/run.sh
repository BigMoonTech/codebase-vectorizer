#!/usr/bin/env bash
# POSIX shim: find a usable Python 3.10-3.13 and hand off to bootstrap.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CANDIDATES=(python3.13 python3.12 python3.11 python3.10 python3 python)

PY=""
for cand in "${CANDIDATES[@]}"; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver=$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || true)
    case "$ver" in
      3.10|3.11|3.12|3.13)
        PY="$cand"
        break
        ;;
    esac
  fi
done

if [ -z "$PY" ]; then
  echo "ERROR: codebase-vectorizer needs Python 3.10-3.13 on PATH." >&2
  echo "  Debian/Ubuntu/WSL: sudo apt install python3.12 python3.12-venv" >&2
  echo "  macOS:             brew install python@3.12" >&2
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/bootstrap.py" "$@"
