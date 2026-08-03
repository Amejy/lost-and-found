from datetime import datetime, timezone
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from backend.app.extensions import db


class ApiKey(db.Model):
    __tablename__ = "api_keys"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    prefix = db.Column(db.String(24), nullable=False, unique=True, index=True)
    secret_hash = db.Column(db.String(255), nullable=False)
    last_used_at = db.Column(db.DateTime(timezone=True))
    revoked_at = db.Column(db.DateTime(timezone=True), index=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    organization = db.relationship("Organization", back_populates="api_keys")
    user = db.relationship("User", back_populates="api_keys")

    @property
    def is_active(self):
        return self.revoked_at is None

    @property
    def display_prefix(self):
        return self.prefix[:8]

    @staticmethod
    def generate_secret():
        return f"lfk_{secrets.token_urlsafe(32)}"

    def set_secret(self, secret):
        self.secret_hash = generate_password_hash(secret)
        self.prefix = secret[:24]

    def check_secret(self, secret):
        return check_password_hash(self.secret_hash, secret)
