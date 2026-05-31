from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from backend.app.extensions import db
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemMatch, ItemStatus, LostItem
from backend.app.models.notification import Notification
from backend.app.services.item_state import ACTIVE_ITEM_STATUSES
from backend.app.services.matching import active_suggested_matches_query
from backend.app.services.validation import parse_date
from backend.app.utils import image_url


main_bp = Blueprint("main", __name__)


def dashboard_endpoint_for(user):
    return "admin.dashboard" if user.is_authenticated and user.is_admin else "main.dashboard"


def build_activity_series(records, attr_name, days=7):
    today = datetime.now(timezone.utc).date()
    buckets = OrderedDict()
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        buckets[day] = 0

    for record in records:
        date_value = getattr(record, attr_name)
        if date_value is None:
            continue
        if hasattr(date_value, "date"):
            date_value = date_value.date()
        if date_value in buckets:
            buckets[date_value] += 1

    labels = [day.strftime("%b %d") for day in buckets]
    values = list(buckets.values())
    return {"labels": labels, "values": values, "total": sum(values)}


@main_bp.app_context_processor
def inject_globals():
    unread_count = 0
    portal_home_url = url_for("main.index")
    portal_home_label = "Dashboard"
    if current_user.is_authenticated:
        unread_count = current_user.notifications.filter_by(is_read=False).count()
        portal_home_url = url_for(dashboard_endpoint_for(current_user))
        portal_home_label = "Admin overview" if current_user.is_admin else "Dashboard"
    return {
        "image_url": image_url,
        "unread_notification_count": unread_count,
        "portal_home_url": portal_home_url,
        "portal_home_label": portal_home_label,
    }


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    stats = {
        "lost_items": LostItem.query.filter(LostItem.status.in_(ACTIVE_ITEM_STATUSES[:-1])).count(),
        "found_items": FoundItem.query.filter(FoundItem.status.in_(ACTIVE_ITEM_STATUSES[:-1])).count(),
        "claims": Claim.query.count(),
        "matches": active_suggested_matches_query().count(),
    }
    recent_lost = (
        LostItem.query.filter(LostItem.status.in_(ACTIVE_ITEM_STATUSES[:-1]))
        .order_by(LostItem.created_at.desc())
        .limit(3)
        .all()
    )
    recent_found = (
        FoundItem.query.filter(FoundItem.status.in_(ACTIVE_ITEM_STATUSES[:-1]))
        .order_by(FoundItem.created_at.desc())
        .limit(3)
        .all()
    )
    return render_template("dashboard/landing.html", stats=stats, recent_lost=recent_lost, recent_found=recent_found)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for("admin.dashboard"))

    page = request.args.get("page", default=1, type=int)
    per_page = current_app.config["ITEMS_PER_PAGE"]
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    location = request.args.get("location", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    item_kind = request.args.get("kind", "all").strip()

    lost_query = LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED)
    found_query = FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED)

    if query:
        lost_query = lost_query.filter(
            or_(LostItem.title.ilike(f"%{query}%"), LostItem.description.ilike(f"%{query}%"))
        )
        found_query = found_query.filter(
            or_(FoundItem.title.ilike(f"%{query}%"), FoundItem.description.ilike(f"%{query}%"))
        )

    if category:
        lost_query = lost_query.filter(LostItem.category == category)
        found_query = found_query.filter(FoundItem.category == category)

    if location:
        lost_query = lost_query.filter(LostItem.location.ilike(f"%{location}%"))
        found_query = found_query.filter(FoundItem.location.ilike(f"%{location}%"))

    try:
        if date_from:
            parsed_date_from = parse_date(date_from, "date_from")
            lost_query = lost_query.filter(LostItem.date_lost >= parsed_date_from)
            found_query = found_query.filter(FoundItem.date_found >= parsed_date_from)

        if date_to:
            parsed_date_to = parse_date(date_to, "date_to")
            lost_query = lost_query.filter(LostItem.date_lost <= parsed_date_to)
            found_query = found_query.filter(FoundItem.date_found <= parsed_date_to)
    except ValueError as exc:
        flash(str(exc), "danger")

    lost_items = lost_query.order_by(LostItem.created_at.desc()).paginate(page=page, per_page=per_page)
    found_items = found_query.order_by(FoundItem.created_at.desc()).paginate(page=page, per_page=per_page)

    suggested_matches_query = active_suggested_matches_query()
    suggested_matches = (
        suggested_matches_query.order_by(ItemMatch.score.desc(), ItemMatch.created_at.desc()).limit(6).all()
    )

    stats = {
        "my_lost_reports": current_user.lost_items.filter(LostItem.status != ItemStatus.ARCHIVED).count(),
        "my_found_reports": current_user.found_items.filter(FoundItem.status != ItemStatus.ARCHIVED).count(),
        "my_claims": current_user.claims.count(),
        "notifications": current_user.notifications.count(),
    }

    recent_window = datetime.now(timezone.utc) - timedelta(days=6)
    activity = {
        "lost": build_activity_series(
            LostItem.query.filter(
                LostItem.created_at >= recent_window,
                LostItem.status != ItemStatus.ARCHIVED,
            ).all(),
            "created_at",
        ),
        "found": build_activity_series(
            FoundItem.query.filter(
                FoundItem.created_at >= recent_window,
                FoundItem.status != ItemStatus.ARCHIVED,
            ).all(),
            "created_at",
        ),
        "claims": build_activity_series(
            Claim.query.filter(Claim.created_at >= recent_window).all(),
            "created_at",
        ),
    }
    approved_claims = Claim.query.filter_by(status=ClaimStatus.APPROVED).count()
    total_claims = Claim.query.count()
    resolution_rate = round((approved_claims / total_claims) * 100, 1) if total_claims else 0
    workflow_health = {
        "resolution_rate": resolution_rate,
        "open_matches": suggested_matches_query.count(),
        "active_reports": current_user.lost_items.filter(LostItem.status != ItemStatus.ARCHIVED).count()
        + current_user.found_items.filter(FoundItem.status != ItemStatus.ARCHIVED).count(),
    }

    return render_template(
        "dashboard/index.html",
        stats=stats,
        lost_items=lost_items,
        found_items=found_items,
        suggested_matches=suggested_matches,
        activity=activity,
        workflow_health=workflow_health,
        item_kind=item_kind,
        current_filters={
            "q": query,
            "category": category,
            "location": location,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@main_bp.route("/notifications")
@login_required
def notifications():
    notifications = current_user.notifications.order_by(Notification.created_at.desc()).all()
    return render_template("dashboard/notifications.html", notifications=notifications)


@main_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    notification = current_user.notifications.filter_by(id=notification_id).first()
    if notification is None:
        abort(404)
    notification.is_read = True
    db.session.commit()
    return redirect(request.referrer or url_for("main.notifications"))
