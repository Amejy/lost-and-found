from backend.app.extensions import db
from backend.app.models.notification import Notification, NotificationType


def create_notification(user, title, message, notification_type=NotificationType.SYSTEM, related_url=None):
    notification = Notification(
        user=user,
        title=title,
        message=message,
        type=notification_type,
        related_url=related_url,
    )
    db.session.add(notification)
    return notification
