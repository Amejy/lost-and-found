from backend.app.extensions import db
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemMatch, ItemStatus, LostItem, MatchStatus
from backend.app.models.notification import Notification
from backend.app.services.item_state import MATCHABLE_ITEM_STATUSES


def _iter_relationship_items(relationship):
    if hasattr(relationship, "all"):
        return relationship.all()
    return list(relationship)


def _collect_related_items(item, linked_claims):
    related_items = {}
    match_links = _iter_relationship_items(item.match_links)

    if isinstance(item, FoundItem):
        for claim in linked_claims:
            if claim.lost_item:
                related_items[(LostItem, claim.lost_item.id)] = claim.lost_item
        for match in match_links:
            if match.lost_item:
                related_items[(LostItem, match.lost_item.id)] = match.lost_item
    else:
        for claim in linked_claims:
            if claim.found_item:
                related_items[(FoundItem, claim.found_item.id)] = claim.found_item
        for match in match_links:
            if match.found_item:
                related_items[(FoundItem, match.found_item.id)] = match.found_item

    return list(related_items.values())


def _resolve_item_status(item):
    if item.status == ItemStatus.ARCHIVED:
        return ItemStatus.ARCHIVED

    if isinstance(item, FoundItem):
        if Claim.query.filter_by(found_item_id=item.id, status=ClaimStatus.APPROVED).first():
            return ItemStatus.RESOLVED
        if Claim.query.filter_by(found_item_id=item.id, status=ClaimStatus.PENDING).first():
            return ItemStatus.CLAIMED
        has_live_match = (
            ItemMatch.query.filter(
                ItemMatch.found_item_id == item.id,
                ItemMatch.status == MatchStatus.SUGGESTED,
                ItemMatch.lost_item.has(LostItem.status.in_(MATCHABLE_ITEM_STATUSES)),
            ).first()
            is not None
        )
        return ItemStatus.MATCHED if has_live_match else ItemStatus.OPEN

    if Claim.query.filter_by(lost_item_id=item.id, status=ClaimStatus.APPROVED).first():
        return ItemStatus.RESOLVED

    has_live_match = (
        ItemMatch.query.filter(
            ItemMatch.lost_item_id == item.id,
            ItemMatch.status == MatchStatus.SUGGESTED,
            ItemMatch.found_item.has(FoundItem.status.in_(MATCHABLE_ITEM_STATUSES)),
        ).first()
        is not None
    )
    return ItemStatus.MATCHED if has_live_match else ItemStatus.OPEN


def _recalculate_related_item_statuses(related_items):
    updated = 0
    for related_item in related_items:
        model = type(related_item)
        fresh_item = db.session.get(model, related_item.id)
        if fresh_item is None or fresh_item.status == ItemStatus.ARCHIVED:
            continue

        next_status = _resolve_item_status(fresh_item)
        if fresh_item.status != next_status:
            fresh_item.status = next_status
            updated += 1

    return updated


def _cleanup_dead_link_notifications(item, linked_claims):
    related_urls = set()

    if hasattr(item, "date_found"):
        related_urls.add(f"/found/{item.id}")
    else:
        related_urls.add(f"/lost/{item.id}")

    for claim in linked_claims:
        related_urls.add(f"/admin/claims/{claim.id}")

    if not related_urls:
        return 0

    notifications = Notification.query.filter(Notification.related_url.in_(related_urls)).all()
    for notification in notifications:
        db.session.delete(notification)
    return len(notifications)


def delete_item_with_dependencies(item):
    linked_claims = _iter_relationship_items(item.claims)
    related_items = _collect_related_items(item, linked_claims)
    deleted_claims = len(linked_claims)
    deleted_notifications = _cleanup_dead_link_notifications(item, linked_claims)

    for claim in linked_claims:
        db.session.delete(claim)

    db.session.delete(item)
    db.session.flush()

    rebalanced_items = _recalculate_related_item_statuses(related_items)
    return {
        "deleted_claims": deleted_claims,
        "deleted_notifications": deleted_notifications,
        "rebalanced_items": rebalanced_items,
    }
