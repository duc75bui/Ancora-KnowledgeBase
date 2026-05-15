from __future__ import annotations

import hmac
import os


ADMIN_PASSWORD_ENV = "ADMIN_PASSWORD"
DEFAULT_ADMIN_PASSWORD = "admin123"


def admin_password_from_env() -> str:
    return os.getenv(ADMIN_PASSWORD_ENV, DEFAULT_ADMIN_PASSWORD)


def verify_admin_password(candidate: str | None, expected: str | None = None) -> bool:
    if candidate is None:
        return False
    configured = expected if expected is not None else admin_password_from_env()
    if not configured:
        return False
    return hmac.compare_digest(candidate, configured)
