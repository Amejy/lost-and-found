from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import Enum as SqlEnum

from backend.app.extensions import db


class WebhookEvent(str, Enum):
    ITEM_CREATED = "item.created"
    ITEM_UPDATED = "item.updated"
    CLAIM_CREATED = "claim.created"
    CLAIM_REVIEWED = "claim.reviewed"
    SUPPORT_CREATED = "support.created"
    SUPPORT_UPDATED = "support.updated"
    INVITE_CREATED = "invite.created"


class WebhookEndpoint(db.Model):
    __tablename__ = "webhook_endpoints"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    events = db.Column(db.JSON, nullable=False, default=list)
    signing_secret = db.Column(db.String(64), nullable=False, default=lambda: uuid4().hex)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    last_delivered_at = db.Column(db.DateTime(timezone=True))
    last_status_code = db.Column(db.Integer)
    last_error = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    organization = db.relationship("Organization", back_populates="webhook_endpoints")

    @property
    def event_labels(self):
        return [WebhookEvent(event).value if event in WebhookEvent._value2member_map_ else event for event in self.events or []]
