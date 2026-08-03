from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from backend.app.extensions import db
from backend.app.forms.auth import (
    ApiKeyCreateForm,
    LoginForm,
    PasswordResetForm,
    PasswordResetRequestForm,
    ProfileSettingsForm,
    RegistrationForm,
    SecuritySettingsForm,
)
from backend.app.models.api_key import ApiKey
from backend.app.models.organization import Organization
from backend.app.models.organization_invite import OrganizationInvite
from backend.app.models.user import User, UserRole
from backend.app.services.audit import log_audit_event
from backend.app.services.api_keys import create_api_key
from backend.app.services.mailer import send_password_reset_email
from backend.app.services.tenant import get_current_organization, slugify_workspace_name


auth_bp = Blueprint("auth", __name__)


def dashboard_endpoint_for(user):
    return "admin.dashboard" if user.is_authenticated and user.is_admin else "main.dashboard"


def build_workspace_slug(name, custom_slug=""):
    if custom_slug and custom_slug.strip():
        return slugify_workspace_name(custom_slug)
    return slugify_workspace_name(name)


def find_user_by_email(email):
    normalized_email = (email or "").strip().lower()
    return User.query.filter(func.lower(User.email) == normalized_email).first()


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    form = RegistrationForm()
    invite_token = request.args.get("invite") or request.form.get("invite")
    invite = OrganizationInvite.verify_token(invite_token) if invite_token else None
    if invite_token and invite is None:
        flash("That workspace invite is invalid or has expired.", "danger")
        return redirect(url_for("auth.register"))

    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        existing_user = find_user_by_email(email)
        if existing_user:
            if invite:
                flash("An account with that email already exists. Sign in to accept the invite.", "warning")
                return redirect(url_for("auth.login", next=url_for("auth.invite_details", token=invite_token, _external=False)))
            flash("An account with that email already exists.", "danger")
            return render_template("auth/register.html", form=form, invite=invite, invite_token=invite_token)

        workspace = None
        created_workspace = False
        if invite:
            if email != invite.email.lower().strip():
                flash("Use the invited email address to accept this workspace invite.", "danger")
                return render_template("auth/register.html", form=form, invite=invite, invite_token=invite_token)
            workspace = invite.organization
        else:
            workspace_name = (form.workspace_name.data or "").strip()
            if workspace_name:
                workspace_slug = build_workspace_slug(workspace_name, form.workspace_slug.data)
                if Organization.query.filter_by(slug=workspace_slug).first():
                    flash("That workspace slug is already in use.", "danger")
                    return render_template("auth/register.html", form=form, invite=invite, invite_token=invite_token)
                workspace = Organization(name=workspace_name, slug=workspace_slug)
                db.session.add(workspace)
                db.session.flush()
                created_workspace = True
            else:
                workspace = get_current_organization()

        user = User(
            organization=workspace,
            full_name=form.full_name.data.strip(),
            email=email,
            role=UserRole.ADMIN if created_workspace else (UserRole(invite.role) if invite else UserRole.USER),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()
        if invite:
            invite.accepted_at = datetime.now(timezone.utc)
            invite.accepted_by = user
        log_audit_event(
            "create",
            "user",
            entity_id=user.id,
            after_data={
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role.value,
                "workspace": workspace.name,
                "created_workspace": created_workspace,
            },
            organization=workspace,
        )
        db.session.commit()

        flash(
            "Workspace created successfully. Please sign in." if created_workspace else "Account created successfully. Please sign in.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form, invite=invite, invite_token=invite_token)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    form = LoginForm()
    if form.validate_on_submit():
        user = find_user_by_email(form.email.data)
        if not user or not user.check_password(form.password.data):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(user, remember=form.remember.data if hasattr(form, 'remember') else False)
        log_audit_event(
            "login",
            "session",
            entity_id=user.id,
            after_data={"email": user.email},
            organization=user.organization,
        )
        db.session.commit()
        flash("Welcome back to FoundIT @ IBBU.", "success")
        next_url = request.args.get("next")
        return redirect(next_url or url_for(dashboard_endpoint_for(user)))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    form = PasswordResetRequestForm()
    reset_url = None
    reset_email = None

    if form.validate_on_submit():
        user = find_user_by_email(form.email.data)
        if user:
            reset_url = url_for("auth.reset_password", token=user.generate_reset_token(), _external=True)
            reset_email = user.email
            email_sent = send_password_reset_email(user, reset_url)
            if email_sent:
                flash("If that account exists, we sent a password reset email.", "success")
                return render_template(
                    "auth/password_reset_requested.html",
                    form=form,
                    reset_url=None,
                    reset_email=reset_email,
                    email_sent=True,
                )

        return render_template(
            "auth/password_reset_requested.html",
            form=form,
            reset_url=reset_url,
            reset_email=reset_email,
            email_sent=False,
        )

    return render_template("auth/password_reset_request.html", form=form)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    user = User.verify_reset_token(token)
    if user is None:
        flash("That password reset link is invalid or has expired.", "danger")
        return redirect(url_for("auth.forgot_password"))

    form = PasswordResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash("Password updated successfully. Please sign in again.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/password_reset.html", form=form, user=user, token=token)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_audit_event(
        "logout",
        "session",
        entity_id=current_user.id,
        after_data={"email": current_user.email},
        organization=get_current_organization(),
    )
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/invites/<token>", methods=["GET"])
def invite_details(token):
    invite = OrganizationInvite.verify_token(token)
    if invite is None:
        flash("That workspace invite is invalid or has expired.", "danger")
        return redirect(url_for("auth.login"))
    return render_template("auth/invite_details.html", invite=invite, token=token)


@auth_bp.route("/invites/<token>/accept", methods=["POST"])
@login_required
def accept_invite(token):
    invite = OrganizationInvite.verify_token(token)
    if invite is None:
        flash("That workspace invite is invalid or has expired.", "danger")
        return redirect(url_for("auth.login"))
    if invite.email.lower().strip() != current_user.email.lower().strip():
        flash("Sign in with the invited email address to accept this workspace invite.", "warning")
        return redirect(url_for("auth.settings"))
    if invite.organization_id == current_user.organization_id and current_user.role.value == invite.role:
        flash("You already belong to this workspace.", "info")
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    current_user.organization = invite.organization
    try:
        current_user.role = UserRole(invite.role)
    except ValueError:
        current_user.role = UserRole.USER
    invite.accepted_at = datetime.now(timezone.utc)
    invite.accepted_by = current_user
    log_audit_event(
        "accept",
        "workspace_invite",
        entity_id=invite.id,
        after_data={"workspace": invite.organization.name, "email": current_user.email},
        organization=invite.organization,
    )
    db.session.commit()
    flash(f"You joined {invite.organization.name}.", "success")
    return redirect(url_for(dashboard_endpoint_for(current_user)))


@auth_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    profile_form = ProfileSettingsForm(obj=current_user)
    profile_form.theme_preference.data = current_user.theme_preference or "system"
    profile_form.email_notifications_enabled.data = current_user.email_notifications_enabled
    profile_form.claim_notifications_enabled.data = current_user.claim_notifications_enabled
    profile_form.match_notifications_enabled.data = current_user.match_notifications_enabled
    security_form = SecuritySettingsForm()
    api_key_form = ApiKeyCreateForm()
    api_keys = current_user.api_keys.order_by(ApiKey.created_at.desc()).all()
    new_api_key = None

    if request.method == "POST":
        form_type = request.form.get("form_type", "profile")
        workspace = get_current_organization()

        if form_type == "profile" and profile_form.validate():
            email = profile_form.email.data.lower().strip()
            email_owner = User.query.filter(func.lower(User.email) == email, User.id != current_user.id).first()
            if email_owner:
                profile_form.email.errors.append("That email is already in use.")
            else:
                before_data = {
                    "full_name": current_user.full_name,
                    "email": current_user.email,
                    "theme_preference": current_user.theme_preference,
                    "email_notifications_enabled": current_user.email_notifications_enabled,
                    "claim_notifications_enabled": current_user.claim_notifications_enabled,
                    "match_notifications_enabled": current_user.match_notifications_enabled,
                }
                current_user.full_name = profile_form.full_name.data.strip()
                current_user.email = email
                current_user.theme_preference = profile_form.theme_preference.data
                current_user.email_notifications_enabled = bool(profile_form.email_notifications_enabled.data)
                current_user.claim_notifications_enabled = bool(profile_form.claim_notifications_enabled.data)
                current_user.match_notifications_enabled = bool(profile_form.match_notifications_enabled.data)
                log_audit_event(
                    "update",
                    "user_profile",
                    entity_id=current_user.id,
                    before_data=before_data,
                    after_data={
                        "full_name": current_user.full_name,
                        "email": current_user.email,
                        "theme_preference": current_user.theme_preference,
                        "email_notifications_enabled": current_user.email_notifications_enabled,
                        "claim_notifications_enabled": current_user.claim_notifications_enabled,
                        "match_notifications_enabled": current_user.match_notifications_enabled,
                    },
                    organization=workspace,
                )
                db.session.commit()
                flash("Profile settings saved.", "success")
                return redirect(url_for("auth.settings"))

        if form_type == "security" and security_form.validate():
            if not current_user.check_password(security_form.current_password.data):
                security_form.current_password.errors.append("Current password is incorrect.")
            else:
                current_user.set_password(security_form.new_password.data)
                log_audit_event(
                    "update",
                    "user_security",
                    entity_id=current_user.id,
                    after_data={"password_changed": True},
                    organization=workspace,
                )
                db.session.commit()
                flash("Password updated successfully.", "success")
                return redirect(url_for("auth.settings"))

        if form_type == "api_key" and api_key_form.validate():
            api_key, secret = create_api_key(current_user, api_key_form.name.data)
            log_audit_event(
                "create",
                "api_key",
                entity_id=api_key.id,
                after_data={"name": api_key.name, "prefix": api_key.prefix},
                organization=workspace,
            )
            db.session.commit()
            new_api_key = secret
            flash("API key created. Copy the secret now; it will not be shown again.", "success")
            api_keys = current_user.api_keys.order_by(ApiKey.created_at.desc()).all()

    return render_template(
        "auth/settings.html",
        profile_form=profile_form,
        security_form=security_form,
        api_key_form=api_key_form,
        api_keys=api_keys,
        new_api_key=new_api_key,
    )


@auth_bp.route("/settings/api-keys/<int:key_id>/revoke", methods=["POST"])
@login_required
def revoke_api_key(key_id):
    api_key = db.session.get(ApiKey, key_id)
    if api_key is None or api_key.user_id != current_user.id:
        flash("API key not found.", "danger")
        return redirect(url_for("auth.settings"))

    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        log_audit_event(
            "revoke",
            "api_key",
            entity_id=api_key.id,
            before_data={"name": api_key.name, "prefix": api_key.prefix},
            after_data={"revoked_at": api_key.revoked_at.isoformat()},
            organization=get_current_organization(),
        )
        db.session.commit()
        flash("API key revoked.", "info")

    return redirect(url_for("auth.settings"))
