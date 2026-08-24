"""
app/dashboard/forms.py — Dashboard forms for client and profile management.
"""

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, BooleanField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Email, URL, Optional, Length, NumberRange


class ClientForm(FlaskForm):
    """Add or edit a client."""

    name = StringField(
        "Client Name",
        validators=[DataRequired(), Length(max=120)],
    )
    website_url = StringField(
        "Website URL",
        validators=[DataRequired(), URL(message="Enter a valid URL (e.g. https://example.com)"), Length(max=2048)],
    )
    contact_email = StringField(
        "Contact Email (optional)",
        validators=[Optional(), Email(), Length(max=254)],
    )
    notes = TextAreaField(
        "Notes (optional)",
        validators=[Optional(), Length(max=1000)],
    )
    auto_report_enabled = BooleanField("Send automated monthly report")
    auto_report_day = IntegerField(
        "Day of month to send report",
        validators=[Optional(), NumberRange(min=1, max=28)],
        default=1,
    )
    submit = SubmitField("Save Client")


class ProfileForm(FlaskForm):
    """Update agency profile and branding."""

    full_name = StringField(
        "Full Name",
        validators=[DataRequired(), Length(max=120)],
    )
    agency_name = StringField(
        "Agency Name",
        validators=[Optional(), Length(max=120)],
    )
    brand_color = StringField(
        "Brand Colour (hex)",
        validators=[Optional(), Length(min=4, max=7)],
        default="#4F46E5",
    )
    logo = FileField(
        "Agency Logo (PNG or JPG, max 2MB)",
        validators=[Optional(), FileAllowed(["png", "jpg", "jpeg"], "Images only.")],
    )
    submit = SubmitField("Save Profile")
