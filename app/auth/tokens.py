"""
app/auth/tokens.py — Signed tokens for password reset.

Uses Flask's built-in itsdangerous URLSafeTimedSerializer so tokens:
  - Are cryptographically signed with the app's SECRET_KEY
  - Expire after a configurable number of seconds (default 1 hour)
  - Cannot be tampered with
"""

from typing import Optional

from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import current_app

# Token expires after 1 hour
RESET_TOKEN_MAX_AGE = 3600


def generate_reset_token(email: str) -> str:
    """
    Create a signed, time-limited token encoding the user's email.

    Args:
        email: The user's email address to encode.

    Returns:
        URL-safe signed token string.
    """
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    return s.dumps(email, salt="password-reset")


def verify_reset_token(token: str) -> Optional[str]:
    """
    Validate a reset token and return the encoded email.

    Args:
        token: The token string from the reset URL.

    Returns:
        The email address if valid, or None if expired / tampered.
    """
    s = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = s.loads(token, salt="password-reset", max_age=RESET_TOKEN_MAX_AGE)
    except (SignatureExpired, BadSignature):
        return None
    return email
