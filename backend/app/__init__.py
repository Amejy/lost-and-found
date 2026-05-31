import os
from pathlib import Path

from flask import Flask, redirect, render_template, request, send_from_directory, url_for

from backend.app.config import config_by_name
from backend.app.extensions import csrf, db, login_manager
from backend.app.models import User, UserRole
from backend.app.routes import admin_bp, api_bp, auth_bp, claims_bp, items_bp, main_bp


def register_cli_commands(app):
    @app.cli.command("init-db")
    def init_db():
        db.create_all()
        print("Database tables created.")

    @app.cli.command("seed-admin")
    def seed_admin():
        admin_email = os.getenv("ADMIN_EMAIL", "admin@lostfound.local").lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "Admin12345!")
        admin_name = os.getenv("ADMIN_NAME", "System Admin")

        existing_admin = User.query.filter_by(email=admin_email).first()
        if existing_admin:
            print(f"Admin already exists for {admin_email}.")
            return

        admin_user = User(full_name=admin_name, email=admin_email, role=UserRole.ADMIN)
        admin_user.set_password(admin_password)
        db.session.add(admin_user)
        db.session.commit()
        print(f"Admin user created: {admin_email}")


def initialize_database(app):
    with app.app_context():
        db.create_all()


def create_app(config_name=None, test_config=None):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_by_name[config_name or os.getenv("FLASK_ENV", "default")])
    if test_config:
        app.config.update(test_config)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    if not app.config.get("TESTING"):
        initialize_database(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    csrf.exempt(api_bp)

    register_cli_commands(app)

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return {"error": "Authentication required."}, 401
        return redirect(url_for("auth.login", next=request.url))

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        return render_template("errors/500.html"), 500

    return app
