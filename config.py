"""
config.py — Application configuration.

Three environments:
  - DevelopmentConfig  (default, uses SQLite)
  - TestingConfig      (in-memory SQLite, no external calls)
  - ProductionConfig   (PostgreSQL, strict security)
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

# The default SECRET_KEY used in development.  If this value is detected in a
# production environment, create_app() will raise an error at startup.
_DEFAULT_SECRET_KEY = "dev-secret-change-in-production"


class BaseConfig:
    """Settings shared by every environment."""

    # ── Flask ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", _DEFAULT_SECRET_KEY)
    WTF_CSRF_ENABLED: bool = True

    # ── File uploads ───────────────────────────────────────────────────────
    # Maximum total request body size (3 MB).  Flask enforces this before any
    # route handler runs, protecting against large upload DoS attacks.
    MAX_CONTENT_LENGTH: int = 3 * 1024 * 1024  # 3 MB

    # These are resolved to absolute paths in create_app() using app.root_path.
    # Keeping them as relative strings here lets tests override them easily.
    UPLOAD_FOLDER: str = os.path.join("app", "static", "uploads")
    REPORT_FOLDER: str = os.path.join("app", "static", "reports")

    # ── SQLAlchemy ─────────────────────────────────────────────────────────
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # ── Flask-Login ────────────────────────────────────────────────────────
    # Must be a timedelta, not an integer.  An integer causes Flask-Login to
    # silently fall back to session-only cookies (breaks "remember me").
    REMEMBER_COOKIE_DURATION: timedelta = timedelta(days=30)

    # ── Session / Cookie security ──────────────────────────────────────────
    # Lax SameSite prevents the cookie from being sent with cross-site
    # top-level navigations initiated by third-party sites, which mitigates
    # login CSRF and reduces leakage even when WTF-CSRF is active.
    SESSION_COOKIE_SAMESITE: str = "Lax"

    # ── Google PageSpeed ───────────────────────────────────────────────────
    GOOGLE_PAGESPEED_API_KEY: str = os.getenv("GOOGLE_PAGESPEED_API_KEY", "")
    PAGESPEED_API_URL: str = (
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    )

    # ── Stripe ─────────────────────────────────────────────────────────────
    STRIPE_PUBLIC_KEY: str = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_STARTER_PRICE_ID: str = os.getenv("STRIPE_STARTER_PRICE_ID", "")
    STRIPE_AGENCY_PRICE_ID: str = os.getenv("STRIPE_AGENCY_PRICE_ID", "")
    STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "")

    # ── Email ──────────────────────────────────────────────────────────────
    MAIL_SERVER: str = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT: int = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS: bool = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER: str = os.getenv("MAIL_DEFAULT_SENDER", "")

    # ── App metadata ───────────────────────────────────────────────────────
    APP_NAME: str = os.getenv("APP_NAME", "SEO Report")
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:5000")

    # ── Subscription plans ─────────────────────────────────────────────────
    PLANS: dict = {
        "starter": {
            "name": "Starter",
            "price": 29,
            "client_limit": 5,
            "description": "Up to 5 clients",
        },
        "agency": {
            "name": "Agency",
            "price": 79,
            "client_limit": 25,
            "description": "Up to 25 clients",
        },
        "pro": {
            "name": "Pro",
            "price": 149,
            "client_limit": None,  # unlimited
            "description": "Unlimited clients",
        },
    }


class DevelopmentConfig(BaseConfig):
    """Local development — SQLite, debug mode on."""

    DEBUG: bool = True
    SQLALCHEMY_DATABASE_URI: str = os.getenv(
        "DATABASE_URL", "sqlite:///seoreport.db"
    )


class TestingConfig(BaseConfig):
    """Automated tests — in-memory database, CSRF off."""

    TESTING: bool = True
    WTF_CSRF_ENABLED: bool = False
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"


class ProductionConfig(BaseConfig):
    """Production — PostgreSQL required, debug off."""

    DEBUG: bool = False
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "")

    # Force secure cookies in production
    SESSION_COOKIE_SECURE: bool = True
    REMEMBER_COOKIE_SECURE: bool = True
    SESSION_COOKIE_HTTPONLY: bool = True


# Map names to classes for easy lookup
config_by_name: dict = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config() -> BaseConfig:
    """
    Return the correct config class based on FLASK_ENV.

    Safety check: if running in production with the default (insecure) SECRET_KEY,
    raise an error immediately so the problem is caught at startup rather than
    silently running with a known-public key.
    """
    env = os.getenv("FLASK_ENV", "development")
    cfg = config_by_name.get(env, DevelopmentConfig)

    if env == "production" and cfg.SECRET_KEY == _DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "FATAL: SECRET_KEY is set to the default development value in a "
            "production environment.  Set a strong, random SECRET_KEY in your "
            "environment or .env file before starting the application."
        )

    return cfg
