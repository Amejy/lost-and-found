from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Enum as SqlEnum

from backend.app.extensions import db


class SupportRequestStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class SupportRequest(db.Model):
    __tablename__ = "support_requests"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    subject = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50), nullable=False, index=True)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(SqlEnum(SupportRequestStatus), nullable=False, default=SupportRequestStatus.OPEN, index=True)
    resolution_notes = db.Column(db.Text)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    resolved_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    requester = db.relationship("User", foreign_keys=[requester_id])
    resolver = db.relationship("User", foreign_keys=[resolved_by_id])
    organization = db.relationship("Organization", back_populates="support_requests")
