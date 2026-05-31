from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from backend.app.extensions import db
from backend.app.forms.claim import ClaimForm
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemStatus, LostItem
from backend.app.models.notification import NotificationType
from backend.app.services.item_state import is_claimable_found_status, is_claim_linkable_lost_status
from backend.app.services.notifications import create_notification
from backend.app.utils import save_image


claims_bp = Blueprint("claims", __name__)


def get_or_404(model, object_id):
    instance = db.session.get(model, object_id)
    if instance is None:
        abort(404)
    return instance


@claims_bp.route("/found/<int:item_id>/claim", methods=["GET", "POST"])
@login_required
def create_claim(item_id):
    found_item = get_or_404(FoundItem, item_id)
    if found_item.reporter_id == current_user.id:
        flash("You cannot submit a claim for an item you reported as found.", "warning")
        return redirect(url_for("items.view_found_item", item_id=found_item.id))
    if not is_claimable_found_status(found_item.status):
        flash("This found item is no longer accepting claims.", "warning")
        return redirect(url_for("items.view_found_item", item_id=found_item.id))
    approved_claim = Claim.query.filter_by(
        found_item_id=found_item.id,
        status=ClaimStatus.APPROVED,
    ).first()
    if approved_claim:
        flash("This item already has a verified ownership claim.", "warning")
        return redirect(url_for("items.view_found_item", item_id=found_item.id))

    form = ClaimForm()
    user_lost_items = (
        current_user.lost_items.filter(
            LostItem.status.in_([
                ItemStatus.OPEN,
                ItemStatus.MATCHED,
                ItemStatus.CLAIMED,
            ])
        )
        .order_by(LostItem.created_at.desc())
        .all()
    )
    allowed_lost_item_ids = {item.id for item in user_lost_items}
    form.lost_item_id.choices = [(0, "No related lost report")] + [
        (item.id, f"{item.title} - {item.date_lost.isoformat()}") for item in user_lost_items
    ]

    submitted_lost_item_id = request.form.get("lost_item_id", type=int) if request.method == "POST" else None
    if submitted_lost_item_id and submitted_lost_item_id not in allowed_lost_item_ids:
        requested_lost_item = db.session.get(LostItem, submitted_lost_item_id)
        if requested_lost_item and requested_lost_item.reporter_id != current_user.id:
            flash("You can only attach your own lost item reports to a claim.", "danger")
        else:
            flash("That lost report is no longer eligible to be linked to a new claim.", "danger")
        return render_template(
            "dashboard/claim_form.html",
            form=form,
            found_item=found_item,
            user_lost_items=user_lost_items,
        )

    if form.validate_on_submit():
        existing_claim = Claim.query.filter_by(
            claimant_id=current_user.id,
            found_item_id=found_item.id,
        ).first()
        if existing_claim:
            flash("You already submitted a claim for this item.", "warning")
            return redirect(url_for("items.view_found_item", item_id=found_item.id))

        try:
            supporting_image = (
                save_image(form.supporting_image.data) if form.supporting_image.data else None
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template(
                "dashboard/claim_form.html",
                form=form,
                found_item=found_item,
                user_lost_items=user_lost_items,
            )
        linked_lost_item = db.session.get(LostItem, form.lost_item_id.data) if form.lost_item_id.data else None
        if linked_lost_item and linked_lost_item.reporter_id != current_user.id:
            flash("You can only attach your own lost item reports to a claim.", "danger")
            return render_template(
                "dashboard/claim_form.html",
                form=form,
                found_item=found_item,
                user_lost_items=user_lost_items,
            )
        if linked_lost_item and not is_claim_linkable_lost_status(linked_lost_item.status):
            flash("That lost report is no longer eligible to be linked to a new claim.", "danger")
            return render_template(
                "dashboard/claim_form.html",
                form=form,
                found_item=found_item,
                user_lost_items=user_lost_items,
            )
        claim = Claim(
            claimant=current_user,
            found_item=found_item,
            lost_item=linked_lost_item,
            proof_text=form.proof_text.data.strip(),
            supporting_image=supporting_image,
        )
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
        flash("Claim submitted. An admin will review it shortly.", "success")
        return redirect(url_for("claims.my_claims"))

    return render_template(
        "dashboard/claim_form.html",
        form=form,
        found_item=found_item,
        user_lost_items=user_lost_items,
    )


@claims_bp.route("/claims")
@login_required
def my_claims():
    claims = current_user.claims.order_by(Claim.created_at.desc()).all()
    return render_template("dashboard/claims.html", claims=claims)
