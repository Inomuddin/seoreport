"""
app/models.py — Database models.

Tables:
  - User      → agency owner account
  - Client    → a website the agency manages
  - Report    → one SEO analysis run for a client
  - ReportItem → individual check result within a report
"""

from datetime import datetime, timezone
from typing import Optional

from flask_login import UserMixin

from app import db, login_manager


# ── User loader (required by Flask-Login) ─────────────────────────────────────

@login_manager.user_loader
def load_user(user_id: str) -> Optional["User"]:
    return db.session.get(User, int(user_id))


# ─────────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────────

class User(db.Model, UserMixin):
    """
    An agency that uses the platform.

    Subscription plans: starter / agency / pro / none (trial)
    """

    __tablename__ = "users"

    id: int = db.Column(db.Integer, primary_key=True)

    # ── Identity ───────────────────────────────────────────────────────────
    email: str = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash: str = db.Column(db.String(255), nullable=False)
    full_name: str = db.Column(db.String(120), nullable=False)
    agency_name: str = db.Column(db.String(120), nullable=True)

    # ── Branding (white-label) ─────────────────────────────────────────────
    logo_filename: Optional[str] = db.Column(db.String(255), nullable=True)
    brand_color: str = db.Column(db.String(7), default="#4F46E5")  # hex colour

    # ── Subscription ───────────────────────────────────────────────────────
    plan: str = db.Column(
        db.String(20),
        nullable=False,
        default="trial",
    )  # trial | starter | agency | pro
    stripe_customer_id: Optional[str] = db.Column(db.String(255), nullable=True)
    stripe_subscription_id: Optional[str] = db.Column(db.String(255), nullable=True)
    subscription_status: str = db.Column(
        db.String(20), nullable=False, default="inactive"
    )  # active | inactive | past_due | canceled

    # ── Timestamps ─────────────────────────────────────────────────────────
    created_at: datetime = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_login_at: Optional[datetime] = db.Column(db.DateTime, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────
    clients = db.relationship(
        "Client", backref="owner", lazy="dynamic", cascade="all, delete-orphan"
    )

    # ── Properties ────────────────────────────────────────────────────────
    @property
    def client_limit(self) -> Optional[int]:
        """Return the max number of clients allowed on this plan."""
        limits = {"trial": 1, "starter": 5, "agency": 25, "pro": None}
        return limits.get(self.plan, 1)

    @property
    def is_subscription_active(self) -> bool:
        """True if the user has an active paid subscription or trial."""
        return self.subscription_status == "active" or self.plan == "trial"

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# ─────────────────────────────────────────────────────────────────────────────
# Client
# ─────────────────────────────────────────────────────────────────────────────

class Client(db.Model):
    """
    A website / client that belongs to a User (agency).
    """

    __tablename__ = "clients"

    id: int = db.Column(db.Integer, primary_key=True)
    user_id: int = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )

    # ── Details ────────────────────────────────────────────────────────────
    name: str = db.Column(db.String(120), nullable=False)
    website_url: str = db.Column(db.String(2048), nullable=False)
    contact_email: Optional[str] = db.Column(db.String(254), nullable=True)
    notes: Optional[str] = db.Column(db.Text, nullable=True)

    # ── Auto-report schedule ───────────────────────────────────────────────
    auto_report_enabled: bool = db.Column(db.Boolean, default=False)
    auto_report_day: int = db.Column(db.Integer, default=1)  # day of month (1-28)

    # ── Timestamps ─────────────────────────────────────────────────────────
    created_at: datetime = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # ── Relationships ──────────────────────────────────────────────────────
    reports = db.relationship(
        "Report", backref="client", lazy="dynamic", cascade="all, delete-orphan"
    )

    @property
    def latest_report(self) -> Optional["Report"]:
        """Return the most recent report for this client."""
        return (
            self.reports.order_by(Report.created_at.desc()).first()
        )

    @property
    def report_count(self) -> int:
        return self.reports.count()

    def __repr__(self) -> str:
        return f"<Client {self.name} ({self.website_url})>"


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

class Report(db.Model):
    """
    One SEO analysis run for a client.

    status: pending → running → complete | failed
    """

    __tablename__ = "reports"

    id: int = db.Column(db.Integer, primary_key=True)
    client_id: int = db.Column(
        db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True
    )

    # ── Status ─────────────────────────────────────────────────────────────
    status: str = db.Column(
        db.String(20), nullable=False, default="pending"
    )  # pending | running | complete | failed
    error_message: Optional[str] = db.Column(db.Text, nullable=True)

    # ── Overall scores (0-100) ─────────────────────────────────────────────
    overall_score: Optional[int] = db.Column(db.Integer, nullable=True)
    performance_score: Optional[int] = db.Column(db.Integer, nullable=True)
    seo_score: Optional[int] = db.Column(db.Integer, nullable=True)
    accessibility_score: Optional[int] = db.Column(db.Integer, nullable=True)

    # ── Key metrics ────────────────────────────────────────────────────────
    page_speed_mobile: Optional[int] = db.Column(db.Integer, nullable=True)
    page_speed_desktop: Optional[int] = db.Column(db.Integer, nullable=True)
    load_time_seconds: Optional[float] = db.Column(db.Float, nullable=True)
    page_size_kb: Optional[int] = db.Column(db.Integer, nullable=True)

    # ── Meta checks ────────────────────────────────────────────────────────
    has_title: Optional[bool] = db.Column(db.Boolean, nullable=True)
    title_text: Optional[str] = db.Column(db.String(512), nullable=True)
    has_meta_description: Optional[bool] = db.Column(db.Boolean, nullable=True)
    meta_description_text: Optional[str] = db.Column(db.String(512), nullable=True)
    has_h1: Optional[bool] = db.Column(db.Boolean, nullable=True)
    h1_count: Optional[int] = db.Column(db.Integer, nullable=True)

    # ── Technical checks ───────────────────────────────────────────────────
    is_https: Optional[bool] = db.Column(db.Boolean, nullable=True)
    has_robots_txt: Optional[bool] = db.Column(db.Boolean, nullable=True)
    has_sitemap: Optional[bool] = db.Column(db.Boolean, nullable=True)
    is_mobile_friendly: Optional[bool] = db.Column(db.Boolean, nullable=True)
    broken_links_count: Optional[int] = db.Column(db.Integer, nullable=True)
    images_missing_alt: Optional[int] = db.Column(db.Integer, nullable=True)

    # ── PDF ────────────────────────────────────────────────────────────────
    pdf_filename: Optional[str] = db.Column(db.String(255), nullable=True)

    # ── Timestamps ─────────────────────────────────────────────────────────
    created_at: datetime = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Optional[datetime] = db.Column(db.DateTime, nullable=True)

    # ── Relationships ──────────────────────────────────────────────────────
    items = db.relationship(
        "ReportItem", backref="report", lazy="dynamic", cascade="all, delete-orphan"
    )

    @property
    def score_label(self) -> str:
        """Human-readable label for the overall score."""
        if self.overall_score is None:
            return "N/A"
        if self.overall_score >= 80:
            return "Good"
        if self.overall_score >= 50:
            return "Needs Work"
        return "Poor"

    @property
    def score_color(self) -> str:
        """CSS colour class based on score."""
        if self.overall_score is None:
            return "gray"
        if self.overall_score >= 80:
            return "green"
        if self.overall_score >= 50:
            return "yellow"
        return "red"

    def __repr__(self) -> str:
        return f"<Report {self.id} for client {self.client_id} — {self.status}>"


# ─────────────────────────────────────────────────────────────────────────────
# ReportItem
# ─────────────────────────────────────────────────────────────────────────────

class ReportItem(db.Model):
    """
    Individual check result within a report.

    Each row represents one SEO check (e.g. 'Missing meta description').
    severity: info | warning | error
    """

    __tablename__ = "report_items"

    id: int = db.Column(db.Integer, primary_key=True)
    report_id: int = db.Column(
        db.Integer, db.ForeignKey("reports.id"), nullable=False, index=True
    )

    category: str = db.Column(db.String(50), nullable=False)
    # e.g. 'performance', 'seo', 'technical', 'content'

    check_name: str = db.Column(db.String(120), nullable=False)
    # e.g. 'Meta Description'

    status: str = db.Column(db.String(10), nullable=False)
    # pass | fail | warning

    severity: str = db.Column(db.String(10), nullable=False, default="info")
    # info | warning | error

    detail: Optional[str] = db.Column(db.Text, nullable=True)
    # Human-readable explanation

    recommendation: Optional[str] = db.Column(db.Text, nullable=True)
    # What to do about it

    def __repr__(self) -> str:
        return f"<ReportItem {self.check_name}: {self.status}>"
