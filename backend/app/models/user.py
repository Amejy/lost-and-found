from datetime import datetime, timezone
from enum import Enum

from flask import current_app
from flask_login import UserMixin
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import Enum as SqlEnum
from werkzeug.security import check_password_hash, generate_password_hash

from backend.app.extensions import db, login_manager


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(SqlEnum(UserRole), nullable=False, default=UserRole.USER)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    lost_items = db.relationship("LostItem", back_populates="reporter", lazy="dynamic")
    found_items = db.relationship("FoundItem", back_populates="reporter", lazy="dynamic")
    claims = db.relationship(
        "Claim",
        foreign_keys="Claim.claimant_id",
        back_populates="claimant",
        lazy="dynamic",
    )
    reviewed_claims = db.relationship(
        "Claim",
        foreign_keys="Claim.reviewed_by_id",
        back_populates="reviewed_by",
        lazy="dynamic",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        return serializer.dumps({"user_id": self.id}, salt="password-reset")

    @staticmethod
    def verify_reset_token(token, max_age=3600):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            payload = serializer.loads(token, salt="password-reset", max_age=max_age)
        except (BadSignature, SignatureExpired):
            return None

        user_id = payload.get("user_id")
        if not user_id:
            return None
        return db.session.get(User, user_id)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
