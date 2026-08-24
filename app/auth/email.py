"""
app/auth/email.py — Transactional emails for authentication.
"""

from flask import render_template, url_for, current_app
from flask_mail import Message

from app import mail


def send_password_reset_email(user, token: str) -> None:
    """
    Send a password reset link to the user.

    Args:
        user:  User model instance.
        token: Signed reset token from generate_reset_token().
    """
    reset_url = url_for("auth.reset_password", token=token, _external=True)
    app_name = current_app.config["APP_NAME"]

    msg = Message(
        subject=f"[{app_name}] Reset your password",
        recipients=[user.email],
        body=render_template(
            "emails/reset_password.txt",
            user=user,
            reset_url=reset_url,
            app_name=app_name,
        ),
    )
    mail.send(msg)
