"""
app/auth/routes.py — Authentication routes.

Routes:
  GET/POST  /auth/register          → create a new account
  GET/POST  /auth/login             → log in
  GET       /auth/logout            → log out
  GET/POST  /auth/forgot-password   → request reset email
  GET/POST  /auth/reset/<token>     → reset password with token
"""

from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user

from app import db, bcrypt
from app.models import User
from app.auth.forms import (
    RegistrationForm,
    LoginForm,
    ForgotPasswordForm,
    ResetPasswordForm,
)
from app.auth.tokens import generate_reset_token, verify_reset_token
from app.auth.email import send_password_reset_email

auth_bp = Blueprint("auth", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Create a new user account."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.overview"))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_pw = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
        user = User(
            full_name=form.full_name.data.strip(),
            agency_name=form.agency_name.data.strip() or None,
            email=form.email.data.lower().strip(),
            password_hash=hashed_pw,
            plan="trial",
            subscription_status="active",
        )
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f"Welcome, {user.full_name}! Your account is ready.", "success")
        return redirect(url_for("dashboard.overview"))

    return render_template("auth/register.html", form=form)


# ─────────────────────────────────────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Log in an existing user."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.overview"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()

        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            # Update last login timestamp
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()

            login_user(user, remember=form.remember_me.data)
            flash("Logged in successfully.", "success")

            # Redirect to the page the user originally tried to visit
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard.overview"))

        flash("Invalid email or password. Please try again.", "danger")

    return render_template("auth/login.html", form=form)


# ─────────────────────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/logout")
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


# ─────────────────────────────────────────────────────────────────────────────
# Forgot password
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Send a password reset link to the user's email."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.overview"))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user:
            token = generate_reset_token(user.email)
            send_password_reset_email(user, token)

        # Always show the same message to prevent email enumeration
        flash(
            "If that email is registered, you will receive a reset link shortly.",
            "info",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html", form=form)


# ─────────────────────────────────────────────────────────────────────────────
# Reset password
# ─────────────────────────────────────────────────────────────────────────────

@auth_bp.route("/reset/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    """Validate the reset token and let the user set a new password."""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.overview"))

    email = verify_reset_token(token)
    if not email:
        flash("The reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    user = User.query.filter_by(email=email).first_or_404()

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.password_hash = bcrypt.generate_password_hash(
            form.password.data
        ).decode("utf-8")
        db.session.commit()
        flash("Your password has been updated. Please log in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", form=form)
