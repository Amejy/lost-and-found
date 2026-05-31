from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from backend.app.extensions import db
from backend.app.forms.auth import LoginForm, RegistrationForm
from backend.app.models.user import User


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


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
