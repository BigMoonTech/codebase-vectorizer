"""URL → handler routing for the toy app."""
from __future__ import annotations

from pkg.auth import authenticate_user


def route_request(method: str, path: str):
    """Return the handler for (method, path) or None."""
    if path == "/login" and method == "POST":
        return _handle_login
    if path.startswith("/api/"):
        return _api_dispatch
    return _static_handler


def _handle_login(req):
    return {"ok": authenticate_user(req["user"], req["pw_hash"])}


def _api_dispatch(req):
    return {"echo": req}


def _static_handler(req):
    return {"static": True}
