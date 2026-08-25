"""
app/dashboard/routes.py — Dashboard and client management routes.

Routes:
  GET       /dashboard/               → overview (stats + recent reports)
  GET/POST  /dashboard/clients/add    → add new client
  GET       /dashboard/clients/<id>   → client detail + report history
  GET/POST  /dashboard/clients/<id>/edit   → edit client
  POST      /dashboard/clients/<id>/delete → delete client
  GET/POST  /dashboard/profile        → edit profile and logo
"""

import os
import uuid
from io import BytesIO
from typing import Optional

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_required, current_user
from PIL import Image, UnidentifiedImageError

from app import db
from app.models import Client, Report
from app.dashboard.forms import ClientForm, ProfileForm

# Maximum logo size: 2 MB
_LOGO_MAX_BYTES = 2 * 1024 * 1024

# Allowed logo extensions
_ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg"}

# Expected Pillow image formats for each allowed extension
_IMAGE_FORMAT_MAP = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
}

dashboard_bp = Blueprint("dashboard", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Overview
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/")
@dashboard_bp.route("")
@login_required
def overview():
    """Main dashboard: summary stats and recent activity."""
    clients = current_user.clients.all()
    client_count = len(clients)

    # Last 5 reports across all clients
    recent_reports = (
        Report.query
        .join(Client)
        .filter(Client.user_id == current_user.id)
        .order_by(Report.created_at.desc())
        .limit(5)
        .all()
    )

    # Average score across all completed reports
    all_reports = (
        Report.query
        .join(Client)
        .filter(
            Client.user_id == current_user.id,
            Report.status == "complete",
        )
        .all()
    )

    avg_score = (
        round(
            sum(
                r.overall_score
                for r in all_reports
                if r.overall_score is not None
            )
            / len(all_reports)
        )
        if all_reports
        else None
    )

    return render_template(
        "dashboard/overview.html",
        clients=clients,
        client_count=client_count,
        recent_reports=recent_reports,
        total_reports=len(all_reports),
        avg_score=avg_score,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Add client
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/clients/add", methods=["GET", "POST"])
@login_required
def add_client():
    """Add a new client website."""

    # Enforce plan limits
    client_limit = current_user.client_limit

    if (
        client_limit is not None
        and current_user.clients.count() >= client_limit
    ):
        flash(
            f"Your {current_user.plan.capitalize()} plan allows up to "
            f"{client_limit} clients. Upgrade to add more.",
            "warning",
        )
        return redirect(url_for("dashboard.overview"))

    form = ClientForm()

    if form.validate_on_submit():
        client = Client(
            user_id=current_user.id,
            name=form.name.data.strip(),
            website_url=form.website_url.data.strip(),
            contact_email=form.contact_email.data.strip() or None,
            notes=form.notes.data.strip() or None,
            auto_report_enabled=form.auto_report_enabled.data,
            auto_report_day=form.auto_report_day.data or 1,
        )

        db.session.add(client)
        db.session.commit()

        flash(
            f'Client "{client.name}" added successfully.',
            "success",
        )

        return redirect(
            url_for(
                "dashboard.client_detail",
                client_id=client.id,
            )
        )

    return render_template(
        "dashboard/client_form.html",
        form=form,
        title="Add Client",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Client detail
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route("/clients/<int:client_id>")
@login_required
def client_detail(client_id: int):
    """Show a client's details and report history."""

    client = Client.query.filter_by(
        id=client_id,
        user_id=current_user.id,
    ).first_or_404()

    reports = (
        client.reports
        .order_by(Report.created_at.desc())
        .all()
    )

    return render_template(
        "dashboard/client_detail.html",
        client=client,
        reports=reports,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Edit client
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route(
    "/clients/<int:client_id>/edit",
    methods=["GET", "POST"],
)
@login_required
def edit_client(client_id: int):
    """Edit an existing client."""

    client = Client.query.filter_by(
        id=client_id,
        user_id=current_user.id,
    ).first_or_404()

    form = ClientForm(obj=client)

    if form.validate_on_submit():
        client.name = form.name.data.strip()
        client.website_url = form.website_url.data.strip()
        client.contact_email = (
            form.contact_email.data.strip()
            or None
        )
        client.notes = (
            form.notes.data.strip()
            or None
        )
        client.auto_report_enabled = (
            form.auto_report_enabled.data
        )
        client.auto_report_day = (
            form.auto_report_day.data or 1
        )

        db.session.commit()

        flash(
            f'Client "{client.name}" updated.',
            "success",
        )

        return redirect(
            url_for(
                "dashboard.client_detail",
                client_id=client.id,
            )
        )

    return render_template(
        "dashboard/client_form.html",
        form=form,
        title="Edit Client",
        client=client,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Delete client
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route(
    "/clients/<int:client_id>/delete",
    methods=["POST"],
)
@login_required
def delete_client(client_id: int):
    """Delete a client and all their reports."""

    client = Client.query.filter_by(
        id=client_id,
        user_id=current_user.id,
    ).first_or_404()

    name = client.name

    db.session.delete(client)
    db.session.commit()

    flash(
        f'Client "{name}" and all their reports have been deleted.',
        "info",
    )

    return redirect(
        url_for("dashboard.overview")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Profile
# ─────────────────────────────────────────────────────────────────────────────

@dashboard_bp.route(
    "/profile",
    methods=["GET", "POST"],
)
@login_required
def profile():
    """View and update the user's profile and agency branding."""

    form = ProfileForm(obj=current_user)

    if form.validate_on_submit():
        current_user.full_name = (
            form.full_name.data.strip()
        )

        current_user.agency_name = (
            form.agency_name.data.strip()
            or None
        )

        current_user.brand_color = (
            form.brand_color.data
            or "#4F46E5"
        )

        # Handle logo upload
        if form.logo.data:
            logo_filename = _save_logo(form.logo.data)

            if logo_filename:
                # Remove old logo if it exists
                if current_user.logo_filename:
                    _delete_logo(
                        current_user.logo_filename
                    )

                current_user.logo_filename = logo_filename

        db.session.commit()

        flash(
            "Profile updated successfully.",
            "success",
        )

        return redirect(
            url_for("dashboard.profile")
        )

    return render_template(
        "dashboard/profile.html",
        form=form,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _save_logo(file_storage) -> Optional[str]:
    """
    Save an uploaded logo file and return its filename,
    or return None on failure.

    Security measures applied:
      1. Reject files exceeding _LOGO_MAX_BYTES (2 MB).
      2. Validate the declared extension against the allowlist.
      3. Validate the actual image format using Pillow.
      4. Always generate a UUID-based filename.
      5. Never use the original filename as a filesystem path.
    """

    upload_dir = current_app.config.get(
        "UPLOAD_FOLDER",
        os.path.join(
            current_app.static_folder,
            "uploads",
        ),
    )

    os.makedirs(
        upload_dir,
        exist_ok=True,
    )

    # ── 1. Read file content ───────────────────────────────────────────────

    content = file_storage.read()

    if len(content) > _LOGO_MAX_BYTES:
        flash(
            "Logo file is too large. Maximum size is 2 MB.",
            "danger",
        )
        return None

    # Rewind so subsequent reads/saves work correctly
    file_storage.seek(0)

    # ── 2. Extension validation ────────────────────────────────────────────

    original_name = file_storage.filename or ""

    if "." not in original_name:
        flash(
            "Logo file must have an extension (png, jpg, jpeg).",
            "danger",
        )
        return None

    declared_ext = (
        original_name
        .rsplit(".", 1)[-1]
        .lower()
    )

    if declared_ext not in _ALLOWED_LOGO_EXTENSIONS:
        flash(
            "Only PNG and JPEG images are accepted as logos.",
            "danger",
        )
        return None

    # ── 3. Actual image-format validation ─────────────────────────────────

    expected_format = _IMAGE_FORMAT_MAP.get(
        declared_ext
    )

    try:
        with Image.open(BytesIO(content)) as image:
            actual_format = image.format

            # Force Pillow to verify the image data.
            image.verify()

    except (UnidentifiedImageError, OSError):
        flash(
            "The uploaded file is not a valid PNG or JPEG image.",
            "danger",
        )
        return None

    except Exception:
        flash(
            "The uploaded image could not be validated.",
            "danger",
        )
        return None

    if actual_format != expected_format:
        flash(
            "File content does not match the declared image type.",
            "danger",
        )
        return None

    # ── 4. Generate a safe random filename ─────────────────────────────────

    filename = (
        f"logo_{current_user.id}_"
        f"{uuid.uuid4().hex}."
        f"{declared_ext}"
    )

    filepath = os.path.join(
        upload_dir,
        filename,
    )

    # ── 5. Save the validated file ─────────────────────────────────────────

    file_storage.seek(0)
    file_storage.save(filepath)

    return filename


def _delete_logo(filename: str) -> None:
    """Remove a logo file from disk if it exists."""

    path = os.path.join(
        current_app.static_folder,
        "uploads",
        filename,
    )

    if os.path.exists(path):
        os.remove(path)