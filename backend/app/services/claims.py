from datetime import datetime, timezone

from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import ItemStatus
from backend.app.models.notification import NotificationType
from backend.app.services.matching import jaccard_similarity, location_similarity
from backend.app.services.notifications import create_notification


def _format_similarity(score):
    if score >= 0.75:
        return "strong"
    if score >= 0.45:
        return "moderate"
    if score >= 0.2:
        return "weak"
    return "none"


def build_claim_review_payload(claim):
    found_item = claim.found_item
    lost_item = claim.lost_item
    proof_length = len((claim.proof_text or "").strip())

    evidence_checks = [
        {
            "label": "Linked lost report",
            "state": "yes" if lost_item else "no",
            "detail": "The claimant attached an earlier lost-item report." if lost_item else "The claim relies only on the written proof and optional image.",
        },
        {
            "label": "Supporting image",
            "state": "yes" if claim.supporting_image else "no",
            "detail": "An image was uploaded with the claim." if claim.supporting_image else "No image evidence was uploaded with the claim.",
        },
        {
            "label": "Detailed proof text",
            "state": "yes" if proof_length >= 100 else "partial" if proof_length >= 40 else "no",
            "detail": f"The ownership narrative is {proof_length} characters long.",
        },
    ]

    comparison_rows = []
    positive_signals = sum(1 for check in evidence_checks if check["state"] in {"yes", "partial"})
    total_signals = len(evidence_checks)

    if lost_item:
        title_score = jaccard_similarity(found_item.title, lost_item.title)
        description_score = jaccard_similarity(found_item.description, lost_item.description)
        location_score = location_similarity(found_item.location, lost_item.location)
        date_gap = abs((found_item.date_found - lost_item.date_lost).days)
        category_match = found_item.category.lower() == lost_item.category.lower()

        comparison_rows = [
            {
                "label": "Category",
                "found": found_item.category,
                "lost": lost_item.category,
                "state": "yes" if category_match else "no",
                "detail": "Exact category match." if category_match else "Categories do not match.",
            },
            {
                "label": "Location overlap",
                "found": found_item.location,
                "lost": lost_item.location,
                "state": _format_similarity(location_score),
                "detail": f"Location similarity score: {int(location_score * 100)}%.",
            },
            {
                "label": "Date proximity",
                "found": found_item.date_found.strftime("%b %d, %Y"),
                "lost": lost_item.date_lost.strftime("%b %d, %Y"),
                "state": "yes" if date_gap <= 3 else "partial" if date_gap <= 10 else "no",
                "detail": f"The reports are {date_gap} day{'s' if date_gap != 1 else ''} apart.",
            },
            {
                "label": "Title overlap",
                "found": found_item.title,
                "lost": lost_item.title,
                "state": _format_similarity(title_score),
                "detail": f"Keyword overlap score: {int(title_score * 100)}%.",
            },
            {
                "label": "Description overlap",
                "found": found_item.description,
                "lost": lost_item.description,
                "state": _format_similarity(description_score),
                "detail": f"Description similarity score: {int(description_score * 100)}%.",
            },
        ]

        positive_signals += sum(
            1 for row in comparison_rows if row["state"] in {"yes", "strong", "moderate", "partial"}
        )
        total_signals += len(comparison_rows)

    evidence_ratio = round((positive_signals / total_signals) * 100) if total_signals else 0
    recommendation = (
        "High confidence"
        if evidence_ratio >= 75
        else "Needs manual judgment"
        if evidence_ratio >= 45
        else "Low confidence"
    )

    return {
        "evidence_ratio": evidence_ratio,
        "recommendation": recommendation,
        "evidence_checks": evidence_checks,
        "comparison_rows": comparison_rows,
        "queue_snapshot": {
            "pending_for_item": Claim.query.filter_by(
                found_item_id=claim.found_item_id,
                status=ClaimStatus.PENDING,
            ).count(),
            "has_linked_report": bool(lost_item),
            "has_supporting_image": bool(claim.supporting_image),
        },
    }


def apply_claim_review(claim, decision, reviewer, notes):
    notes = (notes or "").strip()
    if not notes:
        notes = (
            "Ownership verified by admin review."
            if decision == "approve"
            else "Claim reviewed and rejected by admin."
        )

    timestamp = datetime.now(timezone.utc)
    claim.status = ClaimStatus.APPROVED if decision == "approve" else ClaimStatus.REJECTED
    claim.admin_notes = notes
    claim.reviewed_by = reviewer
    claim.reviewed_at = timestamp

    pending_siblings = Claim.query.filter(
        Claim.found_item_id == claim.found_item_id,
        Claim.id != claim.id,
        Claim.status == ClaimStatus.PENDING,
    ).all()

    if decision == "approve":
        claim.found_item.status = ItemStatus.RESOLVED
        if claim.lost_item:
            claim.lost_item.status = ItemStatus.RESOLVED

        for sibling in pending_siblings:
            sibling.status = ClaimStatus.REJECTED
            sibling.admin_notes = sibling.admin_notes or "Another ownership claim for this item was approved."
            sibling.reviewed_by = reviewer
            sibling.reviewed_at = timestamp
            create_notification(
                sibling.claimant,
                "Claim update",
                f"Your claim for '{sibling.found_item.title}' was closed because another ownership claim was approved.",
                NotificationType.CLAIM,
                "/claims",
            )

        message = f"Your claim for '{claim.found_item.title}' was approved."
    else:
        claim.found_item.status = ItemStatus.CLAIMED if pending_siblings else ItemStatus.MATCHED
        message = f"Your claim for '{claim.found_item.title}' was rejected."

    create_notification(
        claim.claimant,
        "Claim update",
        message,
        NotificationType.CLAIM,
        "/claims",
    )

    return {
        "closed_other_claims": len(pending_siblings) if decision == "approve" else 0,
        "remaining_pending_claims": len(pending_siblings) if decision == "reject" else 0,
    }
