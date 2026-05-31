from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from backend.app.decorators import admin_required
from backend.app.extensions import db
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemStatus, LostItem
from backend.app.models.notification import NotificationType
from backend.app.models.user import User, UserRole
from backend.app.services.claims import apply_claim_review, build_claim_review_payload
from backend.app.services.notifications import create_notification


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def get_or_404(model, object_id):
    instance = db.session.get(model, object_id)
    if instance is None:
        abort(404)
    return instance


def build_claim_series(claims, days=7):
    today = datetime.now(timezone.utc).date()
    buckets = OrderedDict()
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        buckets[day] = 0

    for claim in claims:
        claim_date = claim.created_at.date()
        if claim_date in buckets:
            buckets[claim_date] += 1

    return {
        "labels": [day.strftime("%b %d") for day in buckets],
        "values": list(buckets.values()),
    }


@admin_bp.route("/")
@admin_required
def dashboard():
    stats = {
        "users": User.query.count(),
        "lost_items": LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED).count(),
        "found_items": FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED).count(),
        "pending_claims": Claim.query.filter_by(status=ClaimStatus.PENDING).count(),
    }
    pending_claims = Claim.query.filter_by(status=ClaimStatus.PENDING).order_by(Claim.created_at.asc()).all()
    recent_users = User.query.order_by(User.created_at.desc()).limit(6).all()
    recent_claims = Claim.query.filter(Claim.created_at >= datetime.now(timezone.utc) - timedelta(days=6)).all()
    claim_mix = {
        "pending": Claim.query.filter_by(status=ClaimStatus.PENDING).count(),
        "approved": Claim.query.filter_by(status=ClaimStatus.APPROVED).count(),
        "rejected": Claim.query.filter_by(status=ClaimStatus.REJECTED).count(),
    }
    return render_template(
        "admin/index.html",
        stats=stats,
        pending_claims=pending_claims,
        recent_users=recent_users,
        claim_activity=build_claim_series(recent_claims),
        claim_mix=claim_mix,
    )


@admin_bp.route("/claims")
@admin_required
def claims():
    claims = Claim.query.order_by(Claim.created_at.desc()).all()
    return render_template("admin/claims.html", claims=claims)


@admin_bp.route("/claims/<int:claim_id>/archive", methods=["POST"])
@admin_required
def archive_claim_records(claim_id):
    claim = get_or_404(Claim, claim_id)
    if claim.status != ClaimStatus.APPROVED:
        flash("Only verified claims can be archived after handoff.", "warning")
        return redirect(url_for("admin.review_claim", claim_id=claim.id))
    if claim.found_item.status == ItemStatus.ARCHIVED and (
        not claim.lost_item or claim.lost_item.status == ItemStatus.ARCHIVED
    ):
        flash("These records were already archived after handoff.", "info")
        return redirect(url_for("admin.claims"))

    claim.found_item.status = ItemStatus.ARCHIVED
    if claim.lost_item:
        claim.lost_item.status = ItemStatus.ARCHIVED

    archive_note = "Owner collected the item. The case was archived and removed from active queues."
    if claim.admin_notes:
        if archive_note not in claim.admin_notes:
            claim.admin_notes = f"{claim.admin_notes}\n\n{archive_note}"
    else:
        claim.admin_notes = archive_note

    create_notification(
        claim.claimant,
        "Claim archived",
        f"Your verified claim for '{claim.found_item.title}' was marked as collected and archived.",
        NotificationType.CLAIM,
        "/claims",
    )
    db.session.commit()
    flash("Handoff recorded. The recovered records were archived and removed from the active queues.", "success")
    return redirect(url_for("admin.claims"))


@admin_bp.route("/claims/<int:claim_id>", methods=["GET", "POST"])
@admin_required
def review_claim(claim_id):
    claim = get_or_404(Claim, claim_id)

    if request.method == "POST":
        decision = request.form.get("decision")
        notes = request.form.get("admin_notes", "").strip()
        if decision not in {"approve", "reject"}:
            flash("Invalid review action.", "danger")
            return redirect(url_for("admin.review_claim", claim_id=claim.id))
        if claim.status != ClaimStatus.PENDING:
            flash("This claim has already been finalized. Use the archived review record for reference only.", "warning")
            return redirect(url_for("admin.review_claim", claim_id=claim.id))

        outcome = apply_claim_review(claim, decision, current_user, notes)
        db.session.commit()
        if outcome["closed_other_claims"]:
            flash(
                f"Claim approved and {outcome['closed_other_claims']} competing pending claim(s) were closed automatically.",
                "success",
            )
        elif outcome["remaining_pending_claims"]:
            flash(
                "Claim rejected. The item remains claimed because other pending claims still need review.",
                "info",
            )
        else:
            flash("Claim review saved.", "success")
        return redirect(url_for("admin.claims"))

    return render_template(
        "admin/claim_review.html",
        claim=claim,
        review_payload=build_claim_review_payload(claim),
    )


@admin_bp.route("/items")
@admin_required
def items():
    lost_items = (
        LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED)
        .order_by(LostItem.created_at.desc())
        .all()
    )
    found_items = (
        FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED)
        .order_by(FoundItem.created_at.desc())
        .all()
    )
    return render_template("admin/items.html", lost_items=lost_items, found_items=found_items)


@admin_bp.route("/users")
@admin_required
def users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/users/<int:user_id>/toggle-role", methods=["POST"])
@admin_required
def toggle_role(user_id):
    user = get_or_404(User, user_id)
    if user.id == current_user.id and user.role == UserRole.ADMIN:
        flash("Use another admin account to change your own access level.", "warning")
        return redirect(url_for("admin.users"))
    if user.role == UserRole.ADMIN and User.query.filter_by(role=UserRole.ADMIN).count() == 1:
        flash("You cannot remove the last admin account from the system.", "warning")
        return redirect(url_for("admin.users"))
    user.role = UserRole.USER if user.role == UserRole.ADMIN else UserRole.ADMIN
    db.session.commit()
    flash("User role updated.", "success")
    return redirect(url_for("admin.users"))
