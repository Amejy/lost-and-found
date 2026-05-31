from decimal import Decimal

from backend.app.extensions import db
from backend.app.models.item import FoundItem, ItemMatch, ItemStatus, LostItem, MatchStatus
from backend.app.models.notification import NotificationType
from backend.app.services.item_state import MATCHABLE_ITEM_STATUSES
from backend.app.services.notifications import create_notification


def tokenize(text):
    return {token.strip(".,!?").lower() for token in text.split() if len(token.strip()) > 2}


def jaccard_similarity(left_text, right_text):
    left_tokens = tokenize(left_text)
    right_tokens = tokenize(right_text)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


def location_similarity(left_location, right_location):
    return jaccard_similarity(left_location, right_location)


def date_similarity(date_a, date_b):
    day_diff = abs((date_a - date_b).days)
    if day_diff > 30:
        return 0.0
    return max(0.0, 1 - (day_diff / 30))


def compute_match_details(lost_item, found_item):
    description_score = jaccard_similarity(
        f"{lost_item.title} {lost_item.description}",
        f"{found_item.title} {found_item.description}",
    )
    location_score = location_similarity(lost_item.location, found_item.location)
    category_score = 1.0 if lost_item.category.lower() == found_item.category.lower() else 0.0
    date_score = date_similarity(lost_item.date_lost, found_item.date_found)

    weighted_score = (
        description_score * 0.45
        + category_score * 0.25
        + location_score * 0.15
        + date_score * 0.15
    )

    reasons = []
    if category_score:
        reasons.append("same category")
    if description_score >= 0.25:
        reasons.append("descriptions overlap")
    if location_score >= 0.20:
        reasons.append("locations are similar")
    if date_score >= 0.40:
        reasons.append("dates are close")
    if not reasons:
        reasons.append("basic similarity detected")

    return round(weighted_score, 2), ", ".join(reasons)


def get_candidate_pairs(item, item_kind):
    if item_kind == "lost":
        return db.session.get(LostItem, item.id), FoundItem.query.filter(
            FoundItem.status.in_(MATCHABLE_ITEM_STATUSES)
        ).all()

    return db.session.get(FoundItem, item.id), LostItem.query.filter(
        LostItem.status.in_(MATCHABLE_ITEM_STATUSES)
    ).all()


def refresh_matches_for_item(item, item_kind, threshold):
    subject, candidates = get_candidate_pairs(item, item_kind)
    if not subject:
        return []

    updated_matches = []
    for candidate in candidates:
        lost_item = subject if item_kind == "lost" else candidate
        found_item = candidate if item_kind == "lost" else subject

        if lost_item.reporter_id == found_item.reporter_id:
            continue

        score, reasons = compute_match_details(lost_item, found_item)
        if score <= 0:
            continue

        match = ItemMatch.query.filter_by(
            lost_item_id=lost_item.id,
            found_item_id=found_item.id,
        ).first()

        if not match:
            match = ItemMatch(
                lost_item=lost_item,
                found_item=found_item,
                score=Decimal(str(score)),
                reasons=reasons,
            )
            db.session.add(match)
        else:
            match.score = Decimal(str(score))
            match.reasons = reasons

        if score >= threshold and not match.notifications_sent:
            lost_item.status = ItemStatus.MATCHED
            found_item.status = ItemStatus.MATCHED

            lost_url = f"/lost/{lost_item.id}"
            found_url = f"/found/{found_item.id}"
            create_notification(
                lost_item.reporter,
                "Possible match found",
                f"We found a possible match for your lost item '{lost_item.title}'.",
                NotificationType.MATCH,
                lost_url,
            )
            create_notification(
                found_item.reporter,
                "Potential owner match found",
                f"A lost-item report may match your found item '{found_item.title}'.",
                NotificationType.MATCH,
                found_url,
            )
            match.notifications_sent = True

        updated_matches.append(match)

    return updated_matches


def active_suggested_matches_query():
    return (
        ItemMatch.query.filter_by(status=MatchStatus.SUGGESTED)
        .filter(ItemMatch.lost_item.has(LostItem.status.in_(MATCHABLE_ITEM_STATUSES)))
        .filter(ItemMatch.found_item.has(FoundItem.status.in_(MATCHABLE_ITEM_STATUSES)))
    )
