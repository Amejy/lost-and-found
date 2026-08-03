from __future__ import annotations

import re
from sqlalchemy import inspect, text
from sqlalchemy import event
from flask_login import current_user

from backend.app.extensions import db

DEFAULT_ORGANIZATION_NAME = "FoundIT @ IBBU"
DEFAULT_ORGANIZATION_SLUG = "foundit-ibbu"


def slugify_workspace_name(value):
    text_value = (value or "").strip().lower()
    text_value = re.sub(r"[^a-z0-9]+", "-", text_value)
    text_value = re.sub(r"-+", "-", text_value).strip("-")
    return text_value or DEFAULT_ORGANIZATION_SLUG


def _organization_model():
    from backend.app.models.organization import Organization

    return Organization


def _user_model():
    from backend.app.models.user import User

    return User


def _item_models():
    from backend.app.models.claim import Claim
    from backend.app.models.item import FoundItem, ItemMatch, LostItem
    from backend.app.models.notification import Notification
    from backend.app.models.support_request import SupportRequest
    from backend.app.models.webhook import WebhookEndpoint

    return Claim, FoundItem, ItemMatch, LostItem, Notification, SupportRequest, WebhookEndpoint


def get_or_create_default_organization(session=None):
    session = session or db.session
    Organization = _organization_model()
    for pending in session.new:
        if isinstance(pending, Organization) and pending.slug == DEFAULT_ORGANIZATION_SLUG:
            return pending

    with session.no_autoflush:
        organization = session.query(Organization).filter_by(slug=DEFAULT_ORGANIZATION_SLUG).first()
    if organization:
        return organization

    organization = Organization(name=DEFAULT_ORGANIZATION_NAME, slug=DEFAULT_ORGANIZATION_SLUG)
    session.add(organization)
    session.flush()
    return organization


def get_current_organization():
    if current_user.is_authenticated and getattr(current_user, "organization", None):
        return current_user.organization
    return get_or_create_default_organization()


def current_organization_id():
    organization = get_current_organization()
    return organization.id if organization else None


def scope_query(query, model, organization_id=None):
    organization_id = organization_id or current_organization_id()
    if organization_id is None or not hasattr(model, "organization_id"):
        return query
    return query.filter(model.organization_id == organization_id)


def ensure_tenant_schema():
    inspector = inspect(db.engine)
    Organization = _organization_model()
    Organization.__table__.create(db.engine, checkfirst=True)

    required_columns = {
        "users": "organization_id INTEGER",
        "lost_items": "organization_id INTEGER",
        "found_items": "organization_id INTEGER",
        "claims": "organization_id INTEGER",
        "notifications": "organization_id INTEGER",
        "item_matches": "organization_id INTEGER",
        "audit_logs": "organization_id INTEGER",
        "support_requests": "organization_id INTEGER",
        "webhook_endpoints": "organization_id INTEGER",
    }

    user_extra_columns = {
        "users": {
            "theme_preference": "theme_preference VARCHAR(20) DEFAULT 'system'",
            "email_notifications_enabled": "email_notifications_enabled BOOLEAN DEFAULT 1",
            "claim_notifications_enabled": "claim_notifications_enabled BOOLEAN DEFAULT 1",
            "match_notifications_enabled": "match_notifications_enabled BOOLEAN DEFAULT 1",
        }
    }

    existing_columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }

    with db.engine.begin() as connection:
        for table, column_sql in required_columns.items():
            if table not in existing_columns:
                continue
            if "organization_id" in existing_columns[table]:
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_sql}"))

        for table, columns in user_extra_columns.items():
            if table not in existing_columns:
                continue
            for column_name, column_sql in columns.items():
                if column_name in existing_columns[table]:
                    continue
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_sql}"))


def backfill_default_organization():
    Organization = _organization_model()
    default_organization = get_or_create_default_organization()
    Claim, FoundItem, ItemMatch, LostItem, Notification, SupportRequest, WebhookEndpoint = _item_models()
    User = _user_model()

    for model in [User, LostItem, FoundItem, Claim, Notification, ItemMatch, SupportRequest, WebhookEndpoint]:
        if hasattr(model, "organization_id"):
            db.session.query(model).filter(model.organization_id.is_(None)).update(
                {model.organization_id: default_organization.id},
                synchronize_session=False,
            )
    db.session.commit()


def register_tenant_hooks():
    from backend.app.models.claim import Claim
    from backend.app.models.item import FoundItem, ItemMatch, LostItem
    from backend.app.models.notification import Notification
    from backend.app.models.organization import Organization
    from backend.app.models.support_request import SupportRequest
    from backend.app.models.webhook import WebhookEndpoint
    from backend.app.models.user import User

    @event.listens_for(db.session, "before_flush")
    def assign_organization_ids(session, _flush_context, _instances):
        default_organization = next(
            (
                obj
                for obj in session.new
                if isinstance(obj, Organization) and obj.slug == DEFAULT_ORGANIZATION_SLUG
            ),
            None,
        )
        if default_organization is None:
            with session.no_autoflush:
                default_organization = (
                    session.query(Organization).filter_by(slug=DEFAULT_ORGANIZATION_SLUG).first()
                )
        if default_organization is None:
            default_organization = Organization(
                name=DEFAULT_ORGANIZATION_NAME,
                slug=DEFAULT_ORGANIZATION_SLUG,
            )
            session.add(default_organization)

        for obj in session.new:
            if isinstance(obj, User) and obj.organization is None:
                obj.organization = default_organization
            elif isinstance(obj, LostItem) and obj.organization is None:
                obj.organization = getattr(obj.reporter, "organization", None) or default_organization
            elif isinstance(obj, FoundItem) and obj.organization is None:
                obj.organization = getattr(obj.reporter, "organization", None) or default_organization
            elif isinstance(obj, Claim) and obj.organization is None:
                obj.organization = (
                    getattr(obj.found_item, "organization", None)
                    or getattr(obj.claimant, "organization", None)
                    or default_organization
                )
            elif isinstance(obj, Notification) and obj.organization is None:
                obj.organization = getattr(obj.user, "organization", None) or default_organization
            elif isinstance(obj, ItemMatch) and obj.organization is None:
                obj.organization = (
                    getattr(obj.lost_item, "organization", None)
                    or getattr(obj.found_item, "organization", None)
                    or default_organization
                )
            elif isinstance(obj, SupportRequest) and obj.organization is None:
                obj.organization = getattr(obj.requester, "organization", None) or default_organization
            elif isinstance(obj, WebhookEndpoint) and obj.organization is None:
                obj.organization = default_organization
