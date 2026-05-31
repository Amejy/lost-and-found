from datetime import datetime

import bleach


def sanitize_text(value):
    text = str(value).strip() if value is not None else ""
    cleaned = bleach.clean(text, tags=[], attributes={}, strip=True)
    return " ".join(cleaned.split())


def parse_date(value, field_name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format.") from exc


def validate_required_payload(payload, required_fields):
    missing = [field for field in required_fields if not sanitize_text(payload.get(field))]  # type: ignore[arg-type]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


def serialize_user(user):
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.value,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
    }


def serialize_lost_item(item):
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "category": item.category,
        "location": item.location,
        "date_lost": item.date_lost.isoformat(),
        "image_filename": item.image_filename,
        "status": item.status.value,
        "reporter": serialize_user(item.reporter),
        "created_at": item.created_at.isoformat(),
    }


def serialize_found_item(item):
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "category": item.category,
        "location": item.location,
        "date_found": item.date_found.isoformat(),
        "image_filename": item.image_filename,
        "status": item.status.value,
        "reporter": serialize_user(item.reporter),
        "created_at": item.created_at.isoformat(),
    }


def serialize_claim(claim):
    return {
        "id": claim.id,
        "proof_text": claim.proof_text,
        "supporting_image": claim.supporting_image,
        "status": claim.status.value,
        "admin_notes": claim.admin_notes,
        "claimant": serialize_user(claim.claimant),
        "found_item_id": claim.found_item_id,
        "lost_item_id": claim.lost_item_id,
        "reviewed_at": claim.reviewed_at.isoformat() if claim.reviewed_at else None,
        "created_at": claim.created_at.isoformat(),
    }
