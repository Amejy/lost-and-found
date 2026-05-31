from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import CheckConstraint, Enum as SqlEnum

from backend.app.extensions import db


class ClaimStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Claim(db.Model):
    __tablename__ = "claims"

    id = db.Column(db.Integer, primary_key=True)
    claimant_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    found_item_id = db.Column(db.Integer, db.ForeignKey("found_items.id"), nullable=False, index=True)
    lost_item_id = db.Column(db.Integer, db.ForeignKey("lost_items.id"), index=True)
    proof_text = db.Column(db.Text, nullable=False)
    supporting_image = db.Column(db.String(255))
    status = db.Column(SqlEnum(ClaimStatus), nullable=False, default=ClaimStatus.PENDING, index=True)
    admin_notes = db.Column(db.Text)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    claimant = db.relationship("User", foreign_keys=[claimant_id], back_populates="claims")
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id], back_populates="reviewed_claims")
    found_item = db.relationship("FoundItem", back_populates="claims")
    lost_item = db.relationship("LostItem", back_populates="claims")

    __table_args__ = (
        CheckConstraint("length(proof_text) >= 10", name="ck_claims_proof_length"),
    )
