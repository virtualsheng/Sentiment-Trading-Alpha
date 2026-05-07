"""
Lightweight local-first security helpers.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, status


class AdminTokenNotConfiguredError(RuntimeError):
    """Raised when ADMIN_API_TOKEN is not set but is required."""


def require_admin_token(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """
    Require a shared admin token for sensitive routes.

    ADMIN_API_TOKEN is *strongly recommended*. If the env var is unset the
    function will still allow requests through, but a startup warning is emitted
    by main.py. Setting ADMIN_API_TOKEN to a non-empty value enables token auth.
    """
    expected = os.getenv("ADMIN_API_TOKEN", "").strip()
    if not expected:
        return  # still let it through — main.py will warn at startup

    provided = (x_admin_token or "").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin token",
        )
