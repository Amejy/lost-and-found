from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from backend.app.decorators import owner_or_admin
from backend.app.extensions import db
from backend.app.forms.item import FoundItemForm, LostItemForm
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemMatch, ItemStatus, LostItem
from backend.app.services.item_state import MATCHABLE_ITEM_STATUSES, is_editable_item_status
from backend.app.services.items import delete_item_with_dependencies
from backend.app.services.matching import refresh_matches_for_item
from backend.app.services.validation import parse_date
from backend.app.utils import save_image


items_bp = Blueprint("items", __name__)


def get_or_404(model, object_id):
    instance = db.session.get(model, object_id)
    if instance is None:
        abort(404)
    return instance


def _apply_listing_filters(query, model, date_field_name):
    keyword = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    location = request.args.get("location", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    if keyword:
        query = query.filter(
            or_(model.title.ilike(f"%{keyword}%"), model.description.ilike(f"%{keyword}%"))
        )
    if category:
        query = query.filter(model.category == category)
    if location:
        query = query.filter(model.location.ilike(f"%{location}%"))

    if date_from:
        query = query.filter(getattr(model, date_field_name) >= parse_date(date_from, "date_from"))
    if date_to:
        query = query.filter(getattr(model, date_field_name) <= parse_date(date_to, "date_to"))

    return query


def _status_breakdown(model):
    active_query = model.query.filter(model.status != ItemStatus.ARCHIVED)
    return {
        "total": active_query.count(),
        "open": active_query.filter_by(status=ItemStatus.OPEN).count(),
        "matched": active_query.filter_by(status=ItemStatus.MATCHED).count(),
        "resolved": active_query.filter_by(status=ItemStatus.RESOLVED).count(),
    }


@items_bp.route("/lost-items")
@login_required
def list_lost_items():
    page = request.args.get("page", default=1, type=int)
    per_page = current_app.config["ITEMS_PER_PAGE"]
    query = LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED).order_by(LostItem.created_at.desc())

    try:
        query = _apply_listing_filters(query, LostItem, "date_lost")
    except ValueError as exc:
        flash(str(exc), "danger")

    items = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "dashboard/item_list.html",
        item_kind="lost",
        items=items,
        stats=_status_breakdown(LostItem),
        current_filters={
            "q": request.args.get("q", "").strip(),
            "category": request.args.get("category", "").strip(),
            "location": request.args.get("location", "").strip(),
            "date_from": request.args.get("date_from", "").strip(),
            "date_to": request.args.get("date_to", "").strip(),
        },
    )


@items_bp.route("/found-items")
@login_required
def list_found_items():
    page = request.args.get("page", default=1, type=int)
    per_page = current_app.config["ITEMS_PER_PAGE"]
    query = FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED).order_by(FoundItem.created_at.desc())

    try:
        query = _apply_listing_filters(query, FoundItem, "date_found")
    except ValueError as exc:
        flash(str(exc), "danger")

    items = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "dashboard/item_list.html",
        item_kind="found",
        items=items,
        stats=_status_breakdown(FoundItem),
        current_filters={
            "q": request.args.get("q", "").strip(),
            "category": request.args.get("category", "").strip(),
            "location": request.args.get("location", "").strip(),
            "date_from": request.args.get("date_from", "").strip(),
            "date_to": request.args.get("date_to", "").strip(),
        },
    )


@items_bp.route("/lost/report", methods=["GET", "POST"])
@login_required
def report_lost_item():
    form = LostItemForm()
    if form.validate_on_submit():
        try:
            image_filename = save_image(form.image.data) if form.image.data else None
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("dashboard/report_item.html", form=form, item_kind="lost")
        item = LostItem(
            reporter=current_user,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            category=form.category.data,
            location=form.location.data.strip(),
            date_lost=form.date_lost.data,
            image_filename=image_filename,
        )
        db.session.add(item)
        db.session.flush()
        refresh_matches_for_item(item, "lost", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
        db.session.commit()
        flash("Lost item report submitted successfully.", "success")
        return redirect(url_for("items.view_lost_item", item_id=item.id))

    return render_template("dashboard/report_item.html", form=form, item_kind="lost")


@items_bp.route("/found/report", methods=["GET", "POST"])
@login_required
def report_found_item():
    form = FoundItemForm()
    if form.validate_on_submit():
        try:
            image_filename = save_image(form.image.data) if form.image.data else None
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("dashboard/report_item.html", form=form, item_kind="found")
        item = FoundItem(
            reporter=current_user,
            title=form.title.data.strip(),
            description=form.description.data.strip(),
            category=form.category.data,
            location=form.location.data.strip(),
            date_found=form.date_found.data,
            image_filename=image_filename,
        )
        db.session.add(item)
        db.session.flush()
        refresh_matches_for_item(item, "found", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
        db.session.commit()
        flash("Found item report submitted successfully.", "success")
        return redirect(url_for("items.view_found_item", item_id=item.id))

    return render_template("dashboard/report_item.html", form=form, item_kind="found")


@items_bp.route("/lost/<int:item_id>")
@login_required
def view_lost_item(item_id):
    item = get_or_404(LostItem, item_id)
    matches = (
        item.match_links.filter(
            ItemMatch.found_item.has(FoundItem.status.in_(MATCHABLE_ITEM_STATUSES))
        )
        .order_by(ItemMatch.score.desc())
        .all()
    )
    return render_template("dashboard/item_detail.html", item=item, item_kind="lost", matches=matches)


@items_bp.route("/found/<int:item_id>")
@login_required
def view_found_item(item_id):
    item = get_or_404(FoundItem, item_id)
    matches = (
        item.match_links.filter(
            ItemMatch.lost_item.has(LostItem.status.in_(MATCHABLE_ITEM_STATUSES))
        )
        .order_by(ItemMatch.score.desc())
        .all()
    )
    claims = []
    if current_user.is_admin or current_user.id == item.reporter_id:
        claims = item.claims.order_by(Claim.created_at.desc()).all()
    return render_template(
        "dashboard/item_detail.html",
        item=item,
        item_kind="found",
        matches=matches,
        claims=claims,
    )


@items_bp.route("/lost/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_lost_item(item_id):
    item = get_or_404(LostItem, item_id)
    if not owner_or_admin(item.reporter_id):
        flash("You do not have permission to edit this record.", "danger")
        return redirect(url_for("items.view_lost_item", item_id=item.id))
    if not is_editable_item_status(item.status):
        flash("This lost item record is locked because the case has already been finalized.", "warning")
        return redirect(url_for("items.view_lost_item", item_id=item.id))

    form = LostItemForm(obj=item)
    if form.validate_on_submit():
        try:
            if form.image.data:
                item.image_filename = save_image(form.image.data)
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("dashboard/report_item.html", form=form, item_kind="lost", item=item, is_edit=True)

        item.title = form.title.data.strip()
        item.description = form.description.data.strip()
        item.category = form.category.data
        item.location = form.location.data.strip()
        item.date_lost = form.date_lost.data
        refresh_matches_for_item(item, "lost", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
        db.session.commit()
        flash("Lost item updated successfully.", "success")
        return redirect(url_for("items.view_lost_item", item_id=item.id))

    return render_template("dashboard/report_item.html", form=form, item_kind="lost", item=item, is_edit=True)


@items_bp.route("/found/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_found_item(item_id):
    item = get_or_404(FoundItem, item_id)
    if not owner_or_admin(item.reporter_id):
        flash("You do not have permission to edit this record.", "danger")
        return redirect(url_for("items.view_found_item", item_id=item.id))
    if not is_editable_item_status(item.status):
        flash("This found item record is locked because the case has already been finalized.", "warning")
        return redirect(url_for("items.view_found_item", item_id=item.id))

    form = FoundItemForm(obj=item)
    if form.validate_on_submit():
        try:
            if form.image.data:
                item.image_filename = save_image(form.image.data)
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("dashboard/report_item.html", form=form, item_kind="found", item=item, is_edit=True)

        item.title = form.title.data.strip()
        item.description = form.description.data.strip()
        item.category = form.category.data
        item.location = form.location.data.strip()
        item.date_found = form.date_found.data
        refresh_matches_for_item(item, "found", current_app.config["NOTIFICATION_MATCH_THRESHOLD"])
        db.session.commit()
        flash("Found item updated successfully.", "success")
        return redirect(url_for("items.view_found_item", item_id=item.id))

    return render_template("dashboard/report_item.html", form=form, item_kind="found", item=item, is_edit=True)


@items_bp.route("/lost/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_lost_item(item_id):
    item = get_or_404(LostItem, item_id)
    if not owner_or_admin(item.reporter_id):
        flash("You do not have permission to delete this record.", "danger")
        return redirect(url_for("items.view_lost_item", item_id=item.id))

    try:
        outcome = delete_item_with_dependencies(item)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("We could not delete this lost item right now. Please try again.", "danger")
        return redirect(url_for("items.view_lost_item", item_id=item.id))

    if outcome["deleted_claims"]:
        flash(
            f"Lost item deleted. {outcome['deleted_claims']} linked claim(s) were removed as part of the cleanup.",
            "info",
        )
    elif outcome["deleted_notifications"]:
        flash(
            f"Lost item deleted. {outcome['deleted_notifications']} stale notification link(s) were cleaned up.",
            "info",
        )
    else:
        flash("Lost item deleted.", "info")
    return redirect(url_for("admin.dashboard" if current_user.is_admin else "main.dashboard"))


@items_bp.route("/found/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_found_item(item_id):
    item = get_or_404(FoundItem, item_id)
    if not owner_or_admin(item.reporter_id):
        flash("You do not have permission to delete this record.", "danger")
        return redirect(url_for("items.view_found_item", item_id=item.id))

    try:
        outcome = delete_item_with_dependencies(item)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("We could not delete this found item right now. Please try again.", "danger")
        return redirect(url_for("items.view_found_item", item_id=item.id))

    if outcome["deleted_claims"]:
        flash(
            f"Found item deleted. {outcome['deleted_claims']} linked claim(s) were removed as part of the cleanup.",
            "info",
        )
    elif outcome["deleted_notifications"]:
        flash(
            f"Found item deleted. {outcome['deleted_notifications']} stale notification link(s) were cleaned up.",
            "info",
        )
    else:
        flash("Found item deleted.", "info")
    return redirect(url_for("admin.dashboard" if current_user.is_admin else "main.dashboard"))
