from datetime import datetime, timezone

from backend.app.extensions import db


class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    slug = db.Column(db.String(120), nullable=False, unique=True, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    users = db.relationship("User", back_populates="organization", lazy="dynamic")
    lost_items = db.relationship("LostItem", back_populates="organization", lazy="dynamic")
    found_items = db.relationship("FoundItem", back_populates="organization", lazy="dynamic")
    claims = db.relationship("Claim", back_populates="organization", lazy="dynamic")
    notifications = db.relationship("Notification", back_populates="organization", lazy="dynamic")
    item_matches = db.relationship("ItemMatch", back_populates="organization", lazy="dynamic")
    audit_logs = db.relationship("AuditLog", back_populates="organization", lazy="dynamic")
    support_requests = db.relationship("SupportRequest", back_populates="organization", lazy="dynamic")
    api_keys = db.relationship("ApiKey", back_populates="organization", lazy="dynamic")
    invites = db.relationship("OrganizationInvite", back_populates="organization", lazy="dynamic")
    webhook_endpoints = db.relationship("WebhookEndpoint", back_populates="organization", lazy="dynamic")
