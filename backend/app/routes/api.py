from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from backend.app.decorators import api_admin_required, api_login_required, owner_or_admin
from backend.app.extensions import db
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemStatus, LostItem
from backend.app.models.notification import NotificationType
from backend.app.models.user import User
from backend.app.services.claims import apply_claim_review
from backend.app.services.item_state import (
    is_claimable_found_status,
    is_claim_linkable_lost_status,
    is_editable_item_status,
)
from backend.app.services.items import delete_item_with_dependencies
from backend.app.services.matching import refresh_matches_for_item
from backend.app.services.notifications import create_notification
from backend.app.services.validation import (
    parse_date,
    sanitize_text,
    serialize_claim,
    serialize_found_item,
    serialize_lost_item,
    serialize_user,
    validate_required_payload,
)


api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


def get_or_404(model, object_id):
    instance = db.session.get(model, object_id)
    if instance is None:
        abort(404)
    return instance


def paginated_response(query, serializer):
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get(
        "per_page",
        default=current_app.config["ITEMS_PER_PAGE"],
        type=int,
    )
    pagination = query.paginate(page=page, per_page=min(per_page, 50), error_out=False)
    return jsonify(
        {
            "items": [serializer(item) for item in pagination.items],
            "pagination": {
                "page": pagination.page,
                "pages": pagination.pages,
                "total": pagination.total,
                "per_page": pagination.per_page,
            },
        }
    )


@api_bp.route("/auth/register", methods=["POST"])
def api_register():
    payload = request.get_json(silent=True) or {}
    try:
        validate_required_payload(payload, ["full_name", "email", "password"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    email = sanitize_text(payload["email"]).lower()
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User already exists."}), 409

    user = User(full_name=sanitize_text(payload["full_name"]), email=email)
    user.set_password(payload["password"])
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "User created successfully.", "user": serialize_user(user)}), 201


@api_bp.route("/auth/login", methods=["POST"])
def api_login():
    payload = request.get_json(silent=True) or {}
    try:
        validate_required_payload(payload, ["email", "password"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    user = User.query.filter_by(email=sanitize_text(payload["email"]).lower()).first()
    if not user or not user.check_password(payload["password"]):
        return jsonify({"error": "Invalid email or password."}), 401

    login_user(user)
    return jsonify({"message": "Login successful.", "user": serialize_user(user)})


@api_bp.route("/auth/logout", methods=["POST"])
@api_login_required
def api_logout():
    logout_user()
    return jsonify({"message": "Logout successful."})


@api_bp.route("/auth/me", methods=["GET"])
@api_login_required
def api_me():
    return jsonify({"user": serialize_user(current_user)})


def apply_item_filters(query, model, keyword_field_names, date_field):
    keyword = sanitize_text(request.args.get("q", ""))
    category = sanitize_text(request.args.get("category", ""))
    location = sanitize_text(request.args.get("location", ""))
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    if keyword:
        filters = [getattr(model, field).ilike(f"%{keyword}%") for field in keyword_field_names]
        query = query.filter(or_(*filters))
    if category:
        query = query.filter(model.category == category)
    if location:
        query = query.filter(model.location.ilike(f"%{location}%"))
    if date_from:
        query = query.filter(getattr(model, date_field) >= parse_date(date_from, "date_from"))
    if date_to:
        query = query.filter(getattr(model, date_field) <= parse_date(date_to, "date_to"))

    return query


@api_bp.route("/lost-items", methods=["GET"])
def api_list_lost_items():
    query = LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED).order_by(LostItem.created_at.desc())
    try:
        query = apply_item_filters(query, LostItem, ["title", "description"], "date_lost")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return paginated_response(query, serialize_lost_item)


@api_bp.route("/lost-items", methods=["POST"])
@api_login_required
def api_create_lost_item():
    payload = request.get_json(silent=True) or {}
    try:
        validate_required_payload(payload, ["title", "description", "category", "location", "date_lost"])
        item = LostItem(
            reporter=current_user,
            title=sanitize_text(payload["title"]),
            description=sanitize_text(payload["description"]),
            category=sanitize_text(payload["category"]),
            location=sanitize_text(payload["location"]),
            date_lost=parse_date(payload["date_lost"], "date_lost"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db.session.add(item)
    db.session.flush()
    refresh_matches_for_item(item, "lost", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
    db.session.commit()
    return jsonify({"message": "Lost item created.", "item": serialize_lost_item(item)}), 201


@api_bp.route("/lost-items/<int:item_id>", methods=["GET"])
def api_get_lost_item(item_id):
    item = get_or_404(LostItem, item_id)
    return jsonify({"item": serialize_lost_item(item)})


@api_bp.route("/lost-items/<int:item_id>", methods=["PUT"])
@api_login_required
def api_update_lost_item(item_id):
    item = get_or_404(LostItem, item_id)
    if not owner_or_admin(item.reporter_id):
        return jsonify({"error": "Permission denied."}), 403
    if not is_editable_item_status(item.status):
        return jsonify({"error": "This lost item record is locked because the case has already been finalized."}), 409

    payload = request.get_json(silent=True) or {}
    for field in ["title", "description", "category", "location"]:
        if field in payload:
            setattr(item, field, sanitize_text(payload[field]))
    if "date_lost" in payload:
        item.date_lost = parse_date(payload["date_lost"], "date_lost")

    refresh_matches_for_item(item, "lost", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
    db.session.commit()
    return jsonify({"message": "Lost item updated.", "item": serialize_lost_item(item)})


@api_bp.route("/lost-items/<int:item_id>", methods=["DELETE"])
@api_login_required
def api_delete_lost_item(item_id):
    item = get_or_404(LostItem, item_id)
    if not owner_or_admin(item.reporter_id):
        return jsonify({"error": "Permission denied."}), 403
    try:
        outcome = delete_item_with_dependencies(item)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Could not delete this lost item right now."}), 500
    return jsonify(
        {
            "message": "Lost item deleted.",
            "deleted_claims": outcome["deleted_claims"],
        }
    )


@api_bp.route("/found-items", methods=["GET"])
def api_list_found_items():
    query = FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED).order_by(FoundItem.created_at.desc())
    try:
        query = apply_item_filters(query, FoundItem, ["title", "description"], "date_found")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return paginated_response(query, serialize_found_item)


@api_bp.route("/found-items", methods=["POST"])
@api_login_required
def api_create_found_item():
    payload = request.get_json(silent=True) or {}
    try:
        validate_required_payload(payload, ["title", "description", "category", "location", "date_found"])
        item = FoundItem(
            reporter=current_user,
            title=sanitize_text(payload["title"]),
            description=sanitize_text(payload["description"]),
            category=sanitize_text(payload["category"]),
            location=sanitize_text(payload["location"]),
            date_found=parse_date(payload["date_found"], "date_found"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db.session.add(item)
    db.session.flush()
    refresh_matches_for_item(item, "found", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
    db.session.commit()
    return jsonify({"message": "Found item created.", "item": serialize_found_item(item)}), 201


@api_bp.route("/found-items/<int:item_id>", methods=["GET"])
def api_get_found_item(item_id):
    item = get_or_404(FoundItem, item_id)
    return jsonify({"item": serialize_found_item(item)})


@api_bp.route("/found-items/<int:item_id>", methods=["PUT"])
@api_login_required
def api_update_found_item(item_id):
    item = get_or_404(FoundItem, item_id)
    if not owner_or_admin(item.reporter_id):
        return jsonify({"error": "Permission denied."}), 403
    if not is_editable_item_status(item.status):
        return jsonify({"error": "This found item record is locked because the case has already been finalized."}), 409

    payload = request.get_json(silent=True) or {}
    for field in ["title", "description", "category", "location"]:
        if field in payload:
            setattr(item, field, sanitize_text(payload[field]))
    if "date_found" in payload:
        item.date_found = parse_date(payload["date_found"], "date_found")

    refresh_matches_for_item(item, "found", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
    db.session.commit()
    return jsonify({"message": "Found item updated.", "item": serialize_found_item(item)})


@api_bp.route("/found-items/<int:item_id>", methods=["DELETE"])
@api_login_required
def api_delete_found_item(item_id):
    item = get_or_404(FoundItem, item_id)
    if not owner_or_admin(item.reporter_id):
        return jsonify({"error": "Permission denied."}), 403
    try:
        outcome = delete_item_with_dependencies(item)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({"error": "Could not delete this found item right now."}), 500
    return jsonify(
        {
            "message": "Found item deleted.",
            "deleted_claims": outcome["deleted_claims"],
        }
    )


@api_bp.route("/claims", methods=["GET"])
@api_login_required
def api_list_claims():
    query = Claim.query.order_by(Claim.created_at.desc())
    if not current_user.is_admin:
        query = query.filter_by(claimant_id=current_user.id)
    return paginated_response(query, serialize_claim)


@api_bp.route("/claims", methods=["POST"])
@api_login_required
def api_create_claim():
    payload = request.get_json(silent=True) or {}
    try:
        validate_required_payload(payload, ["found_item_id", "proof_text"])
        found_item = get_or_404(FoundItem, int(payload["found_item_id"]))
        if found_item.reporter_id == current_user.id:
            raise ValueError("You cannot submit a claim for an item you reported as found.")
        if not is_claimable_found_status(found_item.status):
            raise ValueError("This found item is no longer accepting claims.")
        approved_claim = Claim.query.filter_by(
            found_item_id=found_item.id,
            status=ClaimStatus.APPROVED,
        ).first()
        if approved_claim:
            raise ValueError("This item already has a verified ownership claim.")
        lost_item = db.session.get(LostItem, int(payload["lost_item_id"])) if payload.get("lost_item_id") else None
        if lost_item and lost_item.reporter_id != current_user.id:
            raise ValueError("You can only attach your own lost item reports to a claim.")
        if lost_item and not is_claim_linkable_lost_status(lost_item.status):
            raise ValueError("That lost report is no longer eligible to be linked to a new claim.")
        existing_claim = Claim.query.filter_by(
            claimant_id=current_user.id,
            found_item_id=found_item.id,
        ).first()
        if existing_claim:
            raise ValueError("You already submitted a claim for this item.")
        claim = Claim(
            claimant=current_user,
            found_item=found_item,
            lost_item=lost_item,
            proof_text=sanitize_text(payload["proof_text"]),
        )
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    found_item.status = ItemStatus.CLAIMED
    db.session.add(claim)
    db.session.flush()
    create_notification(
        found_item.reporter,
        "New claim submitted",
        f"{current_user.full_name} submitted a claim for your found item '{found_item.title}'.",
        NotificationType.CLAIM,
        f"/found/{found_item.id}",
    )
    db.session.commit()
    return jsonify({"message": "Claim created.", "claim": serialize_claim(claim)}), 201


@api_bp.route("/claims/<int:claim_id>", methods=["GET"])
@api_login_required
def api_get_claim(claim_id):
    claim = get_or_404(Claim, claim_id)
    if not current_user.is_admin and claim.claimant_id != current_user.id:
        return jsonify({"error": "Permission denied."}), 403
    return jsonify({"claim": serialize_claim(claim)})


@api_bp.route("/claims/<int:claim_id>/review", methods=["PATCH"])
@api_admin_required
def api_review_claim(claim_id):
    claim = get_or_404(Claim, claim_id)
    payload = request.get_json(silent=True) or {}
    decision = sanitize_text(payload.get("decision", ""))
    notes = sanitize_text(payload.get("admin_notes", ""))

    if decision not in {"approve", "reject"}:
        return jsonify({"error": "Decision must be approve or reject."}), 400
    if claim.status != ClaimStatus.PENDING:
        return jsonify({"error": "This claim has already been finalized."}), 409

    apply_claim_review(claim, decision, current_user, notes)
    db.session.commit()
    return jsonify({"message": "Claim reviewed.", "claim": serialize_claim(claim)})


@api_bp.route("/admin/dashboard", methods=["GET"])
@api_admin_required
def api_admin_dashboard():
    return jsonify(
        {
            "stats": {
                "users": User.query.count(),
                "lost_items": LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED).count(),
                "found_items": FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED).count(),
                "claims": Claim.query.count(),
                "pending_claims": Claim.query.filter_by(status=ClaimStatus.PENDING).count(),
            }
        }
    )


@api_bp.route("/admin/users", methods=["GET"])
@api_admin_required
def api_admin_users():
    return paginated_response(User.query.order_by(User.created_at.desc()), serialize_user)
