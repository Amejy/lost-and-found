import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app, render_template


def send_email(*, to_email, subject, body_text, body_html=None):
    api_key = current_app.config.get("SENDGRID_API_KEY", "").strip()
    if not api_key:
        return False

    payload = {
        "personalizations": [
            {
                "to": [{"email": to_email}],
                "subject": subject,
            }
        ],
        "from": {"email": current_app.config["SENDGRID_FROM_EMAIL"]},
        "content": [
            {
                "type": "text/plain",
                "value": body_text,
            }
        ],
    }
    if body_html:
        payload["content"].append(
            {
                "type": "text/html",
                "value": body_html,
            }
        )

    request = Request(
        f"{current_app.config['SENDGRID_BASE_URL'].rstrip('/')}/mail/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=current_app.config["SENDGRID_TIMEOUT"]):
            pass
    except HTTPError as exc:
        current_app.logger.warning("SendGrid rejected email request: %s", exc)
        return False
    except URLError as exc:
        current_app.logger.warning("SendGrid email request failed: %s", exc)
        return False

    return True


def build_password_reset_email(user, reset_url):
    context = {
        "user": user,
        "reset_url": reset_url,
        "support_email": current_app.config["SUPPORT_EMAIL"],
        "app_name": "LostFound",
        "expires_hours": 1,
    }
    return {
        "subject": "Reset your Lost & Found password",
        "body_text": render_template("emails/password_reset.txt", **context),
        "body_html": render_template("emails/password_reset.html", **context),
    }


def send_password_reset_email(user, reset_url):
    message = build_password_reset_email(user, reset_url)
    return send_email(
        to_email=user.email,
        subject=message["subject"],
        body_text=message["body_text"],
        body_html=message["body_html"],
    )
