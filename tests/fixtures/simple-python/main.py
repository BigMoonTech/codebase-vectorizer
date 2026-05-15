"""Entry point for the simple-python fixture."""
from __future__ import annotations

from pkg.router import route_request


def main() -> int:
    handler = route_request("POST", "/login")
    if handler is None:
        return 1
    out = handler({"user": "alice", "pw_hash": "x"})
    return 0 if out["ok"] is False else 0  # demo only


if __name__ == "__main__":
    raise SystemExit(main())
