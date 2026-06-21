from backend.app.extensions import db
from backend.app.models.claim import Claim
from backend.app.models.notification import Notification
from backend.app.services.items import delete_item_with_dependencies


def delete_user_with_dependencies(user):
    deleted_counts = {
        "notifications": 0,
        "claims": 0,
        "items": 0,
        "reviewed_claims_cleared": 0,
    }

    for item in list(user.lost_items.all()) + list(user.found_items.all()):
        outcome = delete_item_with_dependencies(item)
        deleted_counts["items"] += 1
        deleted_counts["claims"] += outcome["deleted_claims"]
        deleted_counts["notifications"] += outcome["deleted_notifications"]

    direct_claims = Claim.query.filter_by(claimant_id=user.id).all()
    for claim in direct_claims:
        db.session.delete(claim)
    deleted_counts["claims"] += len(direct_claims)

    reviewed_claims = Claim.query.filter_by(reviewed_by_id=user.id).all()
    for claim in reviewed_claims:
        claim.reviewed_by = None
        claim.reviewed_at = None
    deleted_counts["reviewed_claims_cleared"] = len(reviewed_claims)

    notifications = Notification.query.filter_by(user_id=user.id).all()
    for notification in notifications:
        db.session.delete(notification)
    deleted_counts["notifications"] += len(notifications)

    db.session.delete(user)
    return deleted_counts
