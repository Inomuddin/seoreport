"""
app/reports/routes.py — Report routes.

Routes:
  POST /reports/generate/<client_id>  → run analysis, save report
  GET  /reports/<report_id>           → view report
  GET  /reports/<report_id>/download  → download PDF
  POST /reports/<report_id>/delete    → delete report
"""

import os
from datetime import datetime, timezone

import requests
from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    send_file,
    abort,
    current_app,
)
from flask_login import login_required, current_user

from app import db
from app.models import Client, Report, ReportItem
from app.analyzer.seo_analyzer import SEOAnalyzer
from app.reports.pdf_generator import save_pdf, get_pdf_path

reports_bp = Blueprint("reports", __name__)


# ─────────────────────────────────────────────────────────────────────────────
# Generate
# ─────────────────────────────────────────────────────────────────────────────

@reports_bp.route("/generate/<int:client_id>", methods=["POST"])
@login_required
def generate(client_id: int):
    """Run an SEO analysis for a client and save the results."""
    client = Client.query.filter_by(
        id=client_id, user_id=current_user.id
    ).first_or_404()

    # Create a pending report record
    report = Report(client_id=client.id, status="running")
    db.session.add(report)
    db.session.commit()

    # Use try/finally to guarantee the report is never left stuck in 'running'.
    # Even if a DB operation fails in the except block we still attempt cleanup.
    try:
        # Run the analysis
        analyzer = SEOAnalyzer(
            url=client.website_url,
            api_key=current_app.config.get("GOOGLE_PAGESPEED_API_KEY", ""),
        )
        result = analyzer.run()

        if not result.success:
            report.status = "failed"
            report.error_message = result.error
            db.session.commit()
            flash(_user_friendly_error(result.error), "danger")
            return redirect(url_for("dashboard.client_detail", client_id=client.id))

        # Map results onto the Report model
        _populate_report(report, result)

        # Save individual check items
        for check in result.checks:
            item = ReportItem(
                report_id=report.id,
                category=check.category,
                check_name=check.check_name,
                status=check.status,
                severity=check.severity,
                detail=check.detail,
                recommendation=check.recommendation,
            )
            db.session.add(item)

        db.session.flush()  # Give items IDs before generating PDF

        # Generate and save PDF
        pdf_filename = save_pdf(report=report, user=current_user)
        report.pdf_filename = pdf_filename
        report.status = "complete"
        report.completed_at = datetime.now(timezone.utc)
        db.session.commit()

        flash("SEO report generated successfully.", "success")
        return redirect(url_for("reports.view", report_id=report.id))

    except requests.exceptions.SSLError as exc:
        current_app.logger.error(
            "SSL error generating report for client %s: %s", client_id, exc, exc_info=True
        )
        flash("SSL certificate error on this website.", "danger")

    except requests.exceptions.ConnectionError as exc:
        current_app.logger.error(
            "Connection error generating report for client %s: %s", client_id, exc, exc_info=True
        )
        flash("Unable to reach this website. Check the URL is correct and the site is accessible.", "danger")

    except requests.exceptions.Timeout as exc:
        current_app.logger.error(
            "Timeout generating report for client %s: %s", client_id, exc, exc_info=True
        )
        flash("The website took too long to respond.", "danger")

    except ValueError as exc:
        # Raised by validate_url() for invalid or SSRF-blocked URLs
        current_app.logger.error(
            "Invalid URL generating report for client %s: %s", client_id, exc, exc_info=True
        )
        flash("The URL is invalid.", "danger")

    except Exception as exc:
        current_app.logger.error(
            "Unexpected error generating report for client %s: %s", client_id, exc, exc_info=True
        )
        flash("An unexpected error occurred while generating the report.", "danger")

    finally:
        # Always ensure the report is not left stuck in 'running' state.
        # Re-fetch from DB in case the session was rolled back and the object is detached.
        try:
            db.session.rollback()
            # Re-query to get a fresh, attached instance
            fresh_report = db.session.get(Report, report.id)
            if fresh_report and fresh_report.status == "running":
                fresh_report.status = "failed"
                db.session.commit()
        except Exception as cleanup_exc:
            current_app.logger.error(
                "Failed to mark report %s as failed during cleanup: %s",
                report.id, cleanup_exc, exc_info=True
            )

    return redirect(url_for("dashboard.client_detail", client_id=client.id))


# ─────────────────────────────────────────────────────────────────────────────
# View
# ─────────────────────────────────────────────────────────────────────────────

@reports_bp.route("/<int:report_id>")
@login_required
def view(report_id: int):
    """View a report in the browser."""
    report = _get_report_or_404(report_id)
    checks_by_category = _group_checks(report)
    return render_template(
        "reports/view.html",
        report=report,
        client=report.client,
        checks_by_category=checks_by_category,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Download PDF
# ─────────────────────────────────────────────────────────────────────────────

@reports_bp.route("/<int:report_id>/download")
@login_required
def download(report_id: int):
    """Send the PDF file to the browser."""
    # _get_report_or_404 already enforces ownership — the filename check below
    # is therefore redundant for auth but kept as defence-in-depth.
    report = _get_report_or_404(report_id)

    if not report.pdf_filename:
        flash("PDF not available for this report.", "warning")
        return redirect(url_for("reports.view", report_id=report.id))

    pdf_path = get_pdf_path(report.pdf_filename)
    if not os.path.exists(pdf_path):
        flash("PDF file not found. Try regenerating the report.", "danger")
        return redirect(url_for("reports.view", report_id=report.id))

    download_name = (
        f"seo-report-{report.client.name}-{report.created_at.strftime('%Y-%m-%d')}.pdf"
    )
    return send_file(pdf_path, as_attachment=True, download_name=download_name)


# ─────────────────────────────────────────────────────────────────────────────
# Delete
# ─────────────────────────────────────────────────────────────────────────────

@reports_bp.route("/<int:report_id>/delete", methods=["POST"])
@login_required
def delete(report_id: int):
    """Delete a report and its PDF file."""
    report = _get_report_or_404(report_id)
    client_id = report.client_id

    # Remove PDF from disk
    if report.pdf_filename:
        pdf_path = get_pdf_path(report.pdf_filename)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

    db.session.delete(report)
    db.session.commit()
    flash("Report deleted.", "info")
    return redirect(url_for("dashboard.client_detail", client_id=client_id))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_report_or_404(report_id: int) -> Report:
    """
    Return a report that belongs to the current user, or 404.

    Using a JOIN + filter ensures a user cannot access another user's report
    by guessing its ID.  This also protects the download endpoint — since the
    PDF filename (report_{id}_{client_id}.pdf) is guessable, we must verify
    ownership before serving any file.
    """
    report = (
        Report.query
        .join(Client)
        .filter(Report.id == report_id, Client.user_id == current_user.id)
        .first_or_404()
    )
    return report


def _user_friendly_error(error_msg: str) -> str:
    """Map internal error messages to user-friendly strings."""
    if error_msg is None:
        return "Analysis failed for an unknown reason."
    msg = error_msg.lower()
    if "ssl" in msg or "certificate" in msg:
        return "SSL certificate error on this website."
    if "timed out" in msg or "timeout" in msg:
        return "The website took too long to respond."
    if "connection" in msg or "refused" in msg or "unreachable" in msg:
        return "Unable to reach this website. Check the URL is correct and the site is accessible."
    return "Analysis failed. Check the URL and try again."


def _populate_report(report: Report, result) -> None:
    """Copy fields from AnalysisResult onto a Report model instance."""
    report.overall_score = result.overall_score
    report.performance_score = result.performance_score
    report.seo_score = result.seo_score
    report.accessibility_score = result.accessibility_score
    report.page_speed_mobile = result.page_speed_mobile
    report.page_speed_desktop = result.page_speed_desktop
    report.load_time_seconds = result.load_time_seconds
    report.page_size_kb = result.page_size_kb
    report.has_title = result.has_title
    report.title_text = result.title_text
    report.has_meta_description = result.has_meta_description
    report.meta_description_text = result.meta_description_text
    report.has_h1 = result.has_h1
    report.h1_count = result.h1_count
    report.is_https = result.is_https
    report.has_robots_txt = result.has_robots_txt
    report.has_sitemap = result.has_sitemap
    report.is_mobile_friendly = result.is_mobile_friendly
    report.broken_links_count = result.broken_links_count
    report.images_missing_alt = result.images_missing_alt


def _group_checks(report: Report) -> dict:
    groups: dict = {"performance": [], "seo": [], "technical": [], "content": []}
    for item in report.items.all():
        groups.setdefault(item.category, []).append(item)
    return groups
