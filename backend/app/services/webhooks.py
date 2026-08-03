from datetime import datetime, timezone
import hashlib
import hmac
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.app.extensions import db
from backend.app.models.webhook import WebhookEndpoint


def _matching_endpoints(organization_id, event_name):
    return WebhookEndpoint.query.filter(
        WebhookEndpoint.organization_id == organization_id,
        WebhookEndpoint.is_active.is_(True),
    ).all()


def dispatch_webhook_event(event_name, payload, organization_id):
    delivered = 0
    body = json.dumps(
        {
            "event": event_name,
            "payload": payload,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    ).encode("utf-8")

    for endpoint in _matching_endpoints(organization_id, event_name):
        if event_name not in (endpoint.events or []):
            continue

        signature = hmac.new(
            endpoint.signing_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        request = Request(
            endpoint.url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-FoundIT-Event": event_name,
                "X-FoundIT-Signature": f"sha256={signature}",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=10) as response:
                endpoint.last_status_code = response.status
                endpoint.last_error = None
                endpoint.last_delivered_at = datetime.now(timezone.utc)
                delivered += 1
        except HTTPError as exc:
            endpoint.last_status_code = exc.code
            endpoint.last_error = str(exc)
            endpoint.last_delivered_at = datetime.now(timezone.utc)
        except URLError as exc:
            endpoint.last_status_code = None
            endpoint.last_error = str(exc)
            endpoint.last_delivered_at = datetime.now(timezone.utc)

    return delivered
