from flask import has_request_context, request
from flask_login import current_user

from backend.app.extensions import db
from backend.app.models.audit_log import AuditLog
from backend.app.services.tenant import get_current_organization, get_or_create_default_organization


def log_audit_event(action, entity_type, entity_id=None, before_data=None, after_data=None, organization=None):
    if organization is None:
        if current_user.is_authenticated and getattr(current_user, "organization", None):
            organization = current_user.organization
        else:
            organization = get_or_create_default_organization()

    actor = current_user if current_user.is_authenticated else None
    audit_log = AuditLog(
        organization=organization,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr) if has_request_context() else None,
        user_agent=request.headers.get("User-Agent") if has_request_context() else None,
    )
    db.session.add(audit_log)
    return audit_log
