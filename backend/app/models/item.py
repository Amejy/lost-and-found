from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import CheckConstraint, Enum as SqlEnum, UniqueConstraint

from backend.app.extensions import db


class ItemStatus(str, Enum):
    OPEN = "open"
    MATCHED = "matched"
    CLAIMED = "claimed"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class MatchStatus(str, Enum):
    SUGGESTED = "suggested"
    REVIEWED = "reviewed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class TimestampMixin:
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LostItem(TimestampMixin, db.Model):
    __tablename__ = "lost_items"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=False, index=True)
    location = db.Column(db.String(150), nullable=False, index=True)
    date_lost = db.Column(db.Date, nullable=False, index=True)
    image_filename = db.Column(db.String(255))
    status = db.Column(SqlEnum(ItemStatus), nullable=False, default=ItemStatus.OPEN, index=True)

    reporter = db.relationship("User", back_populates="lost_items")
    claims = db.relationship("Claim", back_populates="lost_item", lazy="dynamic")
    match_links = db.relationship(
        "ItemMatch",
        back_populates="lost_item",
        lazy="dynamic",
        cascade="all, delete-orphan",
        foreign_keys="ItemMatch.lost_item_id",
    )

    __table_args__ = (
        CheckConstraint("length(title) > 2", name="ck_lost_items_title_length"),
    )


class FoundItem(TimestampMixin, db.Model):
    __tablename__ = "found_items"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=False, index=True)
    location = db.Column(db.String(150), nullable=False, index=True)
    date_found = db.Column(db.Date, nullable=False, index=True)
    image_filename = db.Column(db.String(255))
    status = db.Column(SqlEnum(ItemStatus), nullable=False, default=ItemStatus.OPEN, index=True)

    reporter = db.relationship("User", back_populates="found_items")
    claims = db.relationship("Claim", back_populates="found_item", lazy="dynamic")
    match_links = db.relationship(
        "ItemMatch",
        back_populates="found_item",
        lazy="dynamic",
        cascade="all, delete-orphan",
        foreign_keys="ItemMatch.found_item_id",
    )

    __table_args__ = (
        CheckConstraint("length(title) > 2", name="ck_found_items_title_length"),
    )


class ItemMatch(TimestampMixin, db.Model):
    __tablename__ = "item_matches"

    id = db.Column(db.Integer, primary_key=True)
    lost_item_id = db.Column(
        db.Integer, db.ForeignKey("lost_items.id", ondelete="CASCADE"), nullable=False
    )
    found_item_id = db.Column(
        db.Integer, db.ForeignKey("found_items.id", ondelete="CASCADE"), nullable=False
    )
    score = db.Column(db.Numeric(5, 2), nullable=False, index=True)
    reasons = db.Column(db.Text, nullable=False)
    status = db.Column(SqlEnum(MatchStatus), nullable=False, default=MatchStatus.SUGGESTED)
    notifications_sent = db.Column(db.Boolean, nullable=False, default=False)

    lost_item = db.relationship("LostItem", back_populates="match_links", foreign_keys=[lost_item_id])
    found_item = db.relationship("FoundItem", back_populates="match_links", foreign_keys=[found_item_id])

    __table_args__ = (
        UniqueConstraint("lost_item_id", "found_item_id", name="uq_item_matches_pair"),
    )
