from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email as EmailValidator, EqualTo, Length, Optional, ValidationError


class IBBUEmail(EmailValidator):
    def __call__(self, form, field):
        value = field.data.strip() if field.data else ""
        if value.lower().endswith(".local"):
            if "@" in value and value.split("@", 1)[0]:
                return
            raise ValidationError(field.gettext("Invalid email address."))
        super().__call__(form, field)


class RegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=3, max=120)])
    email = EmailField("Email", validators=[DataRequired(), IBBUEmail(), Length(min=3, max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    workspace_name = StringField("Workspace name", validators=[Optional(), Length(min=3, max=120)])
    workspace_slug = StringField("Workspace slug", validators=[Optional(), Length(min=3, max=120)])
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), IBBUEmail(), Length(min=3, max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    remember = BooleanField("Remember me")
    submit = SubmitField("Sign in")


class PasswordResetRequestForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), IBBUEmail(), Length(min=3, max=255)])
    submit = SubmitField("Send reset link")


class PasswordResetForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Update password")


class ProfileSettingsForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=3, max=120)])
    email = EmailField("Email", validators=[DataRequired(), IBBUEmail(), Length(min=3, max=255)])
    theme_preference = SelectField(
        "Theme preference",
        choices=[("system", "System"), ("light", "Light"), ("dark", "Dark")],
        validators=[DataRequired()],
    )
    email_notifications_enabled = BooleanField("Enable email notifications")
    claim_notifications_enabled = BooleanField("Claim updates by email")
    match_notifications_enabled = BooleanField("Match alerts by email")
    submit = SubmitField("Save changes")


class SecuritySettingsForm(FlaskForm):
    current_password = PasswordField("Current password", validators=[DataRequired(), Length(min=8, max=128)])
    new_password = PasswordField("New password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_new_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Update password")


class ApiKeyCreateForm(FlaskForm):
    name = StringField("Key name", validators=[DataRequired(), Length(min=3, max=120)])
    submit = SubmitField("Create API key")
