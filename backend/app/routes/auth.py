from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from backend.app.extensions import db
from backend.app.forms.auth import (
    LoginForm,
    PasswordResetForm,
    PasswordResetRequestForm,
    RegistrationForm,
)
from backend.app.models.user import User
from backend.app.services.mailer import send_password_reset_email


auth_bp = Blueprint("auth", __name__)


def dashboard_endpoint_for(user):
    return "admin.dashboard" if user.is_authenticated and user.is_admin else "main.dashboard"


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    form = RegistrationForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(email=form.email.data.lower()).first()
        if existing_user:
            flash("An account with that email already exists.", "danger")
            return render_template("auth/register.html", form=form)

        user = User(
            full_name=form.full_name.data.strip(),
            email=form.email.data.lower().strip(),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        flash("Account created successfully. Please sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if not user or not user.check_password(form.password.data):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(user)
        flash("Welcome back.", "success")
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
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
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
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
