from datetime import datetime, timezone

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.app.extensions import db
from backend.app.services.time import as_naive_utc


class OrganizationInvite(db.Model):
    __tablename__ = "organization_invites"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(40), nullable=False, default="user")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    accepted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    accepted_at = db.Column(db.DateTime(timezone=True), index=True)
    revoked_at = db.Column(db.DateTime(timezone=True), index=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    organization = db.relationship("Organization", back_populates="invites")
    creator = db.relationship("User", foreign_keys=[created_by_id])
    accepter = db.relationship("User", foreign_keys=[accepted_by_id])

    @property
    def is_active(self):
        expires_at = as_naive_utc(self.expires_at)
        return self.accepted_at is None and self.revoked_at is None and expires_at > datetime.utcnow()

    def generate_token(self):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        return serializer.dumps({"invite_id": self.id, "email": self.email}, salt="workspace-invite")

    @staticmethod
    def verify_token(token, max_age=604800):
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            payload = serializer.loads(token, salt="workspace-invite", max_age=max_age)
        except (BadSignature, SignatureExpired):
            return None
        invite_id = payload.get("invite_id")
        if not invite_id:
            return None
        invite = db.session.get(OrganizationInvite, invite_id)
        if invite is None or invite.email != payload.get("email"):
            return None
        return invite
