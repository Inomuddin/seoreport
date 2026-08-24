"""
app/__init__.py — Application factory.

Using the factory pattern keeps the app flexible:
  - Easy to create multiple instances for testing
  - Extensions are initialised once and shared
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect

from config import get_config

# ── Extensions (created here, initialised in create_app) ──────────────────────
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
bcrypt = Bcrypt()
mail = Mail()
csrf = CSRFProtect()


def create_app(config_class=None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_class: Optional config class override. Defaults to the class
                      determined by the FLASK_ENV environment variable.

    Returns:
        Configured Flask application instance.
    """
    app = Flask(__name__)

    # ── Load configuration ─────────────────────────────────────────────────
    app.config.from_object(config_class or get_config())

    # ── Resolve folder paths to absolute (config stores relative strings) ──
    # Using app.root_path ensures paths are correct regardless of the working
    # directory the server process was started from.
    import os as _os
    for _key in ("UPLOAD_FOLDER", "REPORT_FOLDER"):
        _rel = app.config.get(_key)
        if _rel and not _os.path.isabs(_rel):
            app.config[_key] = _os.path.join(_os.path.dirname(app.root_path), _rel)

    # ── Initialise extensions ──────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)

    # ── Flask-Login settings ───────────────────────────────────────────────
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "info"

    # ── Register blueprints ────────────────────────────────────────────────
    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.reports.routes import reports_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(reports_bp, url_prefix="/reports")

    # ── Root redirect ──────────────────────────────────────────────────────
    from flask import redirect, url_for

    @app.route("/")
    def index():
        return redirect(url_for("dashboard.overview"))

    # ── Shell context for `flask shell` ───────────────────────────────────
    @app.shell_context_processor
    def make_shell_context():
        from app.models import User, Client, Report
        return {"db": db, "User": User, "Client": Client, "Report": Report}

    # ── Template context: inject current year ─────────────────────────────
    @app.context_processor
    def inject_now():
        from datetime import datetime, timezone
        return {"now": datetime.now(timezone.utc)}

    return app
