from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Enum as SqlEnum

from backend.app.extensions import db


class NotificationType(str, Enum):
    MATCH = "match"
    CLAIM = "claim"
    SYSTEM = "system"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(SqlEnum(NotificationType), nullable=False, default=NotificationType.SYSTEM)
    related_url = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    user = db.relationship("User", back_populates="notifications")
