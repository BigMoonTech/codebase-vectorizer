"""Tests for the auth module."""
from __future__ import annotations

import pytest

from pkg.auth import authenticate_user


def test_authenticate_user_returns_bool():
    assert isinstance(authenticate_user("u", "h"), bool)
