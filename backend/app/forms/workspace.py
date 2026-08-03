from flask_wtf import FlaskForm
from wtforms import EmailField, SelectField, SelectMultipleField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email as EmailValidator, Length, Optional

from backend.app.forms.auth import IBBUEmail
from backend.app.models.webhook import WebhookEvent


class WorkspaceInviteForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), IBBUEmail(), Length(min=3, max=255)])
    role = SelectField(
        "Role",
        choices=[
            ("user", "User"),
            ("viewer", "Viewer"),
            ("reviewer", "Reviewer"),
            ("manager", "Manager"),
            ("support", "Support"),
        ],
        validators=[DataRequired()],
    )
    submit = SubmitField("Send invite")


class WebhookEndpointForm(FlaskForm):
    name = StringField("Webhook name", validators=[DataRequired(), Length(min=3, max=120)])
    url = StringField("Webhook URL", validators=[DataRequired(), Length(min=8, max=255)])
    events = SelectMultipleField(
        "Events",
        choices=[(event.value, event.value) for event in WebhookEvent],
        validators=[DataRequired()],
    )
    submit = SubmitField("Create webhook")


class SupportTicketUpdateForm(FlaskForm):
    status = SelectField(
        "Status",
        choices=[
            ("open", "Open"),
            ("in_progress", "In progress"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
        ],
        validators=[DataRequired()],
    )
    resolution_notes = TextAreaField("Update notes", validators=[Optional(), Length(min=0, max=4000)])
    submit = SubmitField("Update ticket")
