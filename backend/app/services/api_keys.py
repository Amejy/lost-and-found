from datetime import datetime, timezone

from backend.app.extensions import db
from backend.app.models.api_key import ApiKey
from backend.app.services.validation import sanitize_text


def create_api_key(user, name):
    secret = ApiKey.generate_secret()
    api_key = ApiKey(
        organization=user.organization,
        user=user,
        name=sanitize_text(name),
    )
    api_key.set_secret(secret)
    db.session.add(api_key)
    db.session.flush()
    return api_key, secret


def authenticate_api_key(secret):
    if not secret:
        return None

    prefix = secret[:24]
    candidate = ApiKey.query.filter_by(prefix=prefix, revoked_at=None).first()
    if candidate and candidate.check_secret(secret):
        candidate.last_used_at = datetime.now(timezone.utc)
        return candidate
    return None
