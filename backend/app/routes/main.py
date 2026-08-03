from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from backend.app.decorators import permission_required
from backend.app.extensions import db
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemMatch, ItemStatus, LostItem
from backend.app.models.notification import Notification
from backend.app.models.support_request import SupportRequest, SupportRequestStatus
from backend.app.models.user import User, UserRole
from backend.app.forms.support import SupportRequestForm, SupportResolveForm
from backend.app.forms.workspace import SupportTicketUpdateForm
from backend.app.services.item_state import ACTIVE_ITEM_STATUSES
from backend.app.services.audit import log_audit_event
from backend.app.services.matching import active_suggested_matches_query
from backend.app.services.notifications import create_notification
from backend.app.services.webhooks import dispatch_webhook_event
from backend.app.services.validation import parse_date
from backend.app.services.tenant import get_current_organization, scope_query
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


def build_onboarding_checklist(user, workspace, stats, suggested_matches_count, pending_claims_count):
    if user.is_admin:
        items = [
            {
                "label": "Invite a teammate",
                "detail": "Bring reviewers, support staff, or managers into the workspace.",
                "done": workspace.invites.filter_by(accepted_at=None, revoked_at=None).count() > 0,
                "href": url_for("admin.workspaces"),
                "action": "Manage invites",
            },
            {
                "label": "Create an API key",
                "detail": "Connect an external script, dashboard, or automation.",
                "done": user.api_keys.filter_by(revoked_at=None).count() > 0,
                "href": url_for("auth.settings"),
                "action": "Open settings",
            },
            {
                "label": "Set up a webhook",
                "detail": "Forward item, claim, or support events to another system.",
                "done": workspace.webhook_endpoints.filter_by(is_active=True).count() > 0,
                "href": url_for("admin.workspaces"),
                "action": "Configure webhooks",
            },
            {
                "label": "Review a claim",
                "detail": "Clear the claim queue to keep the recovery workflow moving.",
                "done": pending_claims_count == 0 and stats.get("claims_total", 0) > 0,
                "href": url_for("admin.claims"),
                "action": "Open claims",
            },
        ]
    else:
        items = [
            {
                "label": "Create a lost report",
                "detail": "Add the item you misplaced so it can surface in matches.",
                "done": stats["my_lost_reports"] > 0,
                "href": url_for("items.report_lost_item"),
                "action": "Report lost item",
            },
            {
                "label": "Create a found report",
                "detail": "Log anything recovered so owners can find it faster.",
                "done": stats["my_found_reports"] > 0,
                "href": url_for("items.report_found_item"),
                "action": "Report found item",
            },
            {
                "label": "Submit a claim",
                "detail": "Claim an item when you find a likely match.",
                "done": stats["my_claims"] > 0,
                "href": url_for("claims.my_claims"),
                "action": "Open claims",
            },
            {
                "label": "Review suggested matches",
                "detail": "Check whether the system has already surfaced a likely match.",
                "done": suggested_matches_count > 0,
                "href": url_for("main.dashboard"),
                "action": "Inspect matches",
            },
        ]

    completed = sum(1 for item in items if item["done"])
    return {"items": items, "completed": completed, "total": len(items), "progress": round((completed / len(items)) * 100) if items else 0}


@main_bp.app_context_processor
def inject_globals():
    current_workspace = get_current_organization()
    unread_count = 0
    portal_home_url = url_for("main.index")
    portal_home_label = "Dashboard"
    if current_user.is_authenticated:
        unread_count = current_user.notifications.filter_by(is_read=False).count()
        portal_home_url = url_for(dashboard_endpoint_for(current_user))
        portal_home_label = "Admin overview" if current_user.is_admin else "Dashboard"
    return {
        "image_url": image_url,
        "current_workspace": current_workspace,
        "unread_notification_count": unread_count,
        "portal_home_url": portal_home_url,
        "portal_home_label": portal_home_label,
    }


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    current_workspace = get_current_organization()
    stats = {
        "lost_items": scope_query(
            LostItem.query.filter(LostItem.status.in_(ACTIVE_ITEM_STATUSES[:-1])),
            LostItem,
            current_workspace.id,
        ).count(),
        "found_items": scope_query(
            FoundItem.query.filter(FoundItem.status.in_(ACTIVE_ITEM_STATUSES[:-1])),
            FoundItem,
            current_workspace.id,
        ).count(),
        "claims": scope_query(Claim.query, Claim, current_workspace.id).count(),
        "matches": active_suggested_matches_query(current_workspace.id).count(),
    }
    recent_lost = (
        scope_query(
            LostItem.query.filter(LostItem.status.in_(ACTIVE_ITEM_STATUSES[:-1])),
            LostItem,
            current_workspace.id,
        )
        .order_by(LostItem.created_at.desc())
        .limit(3)
        .all()
    )
    recent_found = (
        scope_query(
            FoundItem.query.filter(FoundItem.status.in_(ACTIVE_ITEM_STATUSES[:-1])),
            FoundItem,
            current_workspace.id,
        )
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

    current_workspace = get_current_organization()
    page = request.args.get("page", default=1, type=int)
    per_page = current_app.config["ITEMS_PER_PAGE"]
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    location = request.args.get("location", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    item_kind = request.args.get("kind", "all").strip()

    lost_query = scope_query(
        LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED),
        LostItem,
        current_workspace.id,
    )
    found_query = scope_query(
        FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED),
        FoundItem,
        current_workspace.id,
    )

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

    suggested_matches_query = active_suggested_matches_query(current_workspace.id)
    suggested_matches = (
        suggested_matches_query.order_by(ItemMatch.score.desc(), ItemMatch.created_at.desc()).limit(6).all()
    )

    stats = {
        "my_lost_reports": current_user.lost_items.filter(
            LostItem.status != ItemStatus.ARCHIVED,
            LostItem.organization_id == current_workspace.id,
        ).count(),
        "my_found_reports": current_user.found_items.filter(
            FoundItem.status != ItemStatus.ARCHIVED,
            FoundItem.organization_id == current_workspace.id,
        ).count(),
        "my_claims": current_user.claims.filter(Claim.organization_id == current_workspace.id).count(),
        "notifications": current_user.notifications.filter(Notification.organization_id == current_workspace.id).count(),
    }

    recent_window = datetime.now(timezone.utc) - timedelta(days=6)
    activity = {
        "lost": build_activity_series(
            scope_query(
                LostItem.query.filter(
                    LostItem.created_at >= recent_window,
                    LostItem.status != ItemStatus.ARCHIVED,
                ),
                LostItem,
                current_workspace.id,
            )
            .all(),
            "created_at",
        ),
        "found": build_activity_series(
            scope_query(
                FoundItem.query.filter(
                    FoundItem.created_at >= recent_window,
                    FoundItem.status != ItemStatus.ARCHIVED,
                ),
                FoundItem,
                current_workspace.id,
            )
            .all(),
            "created_at",
        ),
        "claims": build_activity_series(
            scope_query(Claim.query.filter(Claim.created_at >= recent_window), Claim, current_workspace.id)
            .all(),
            "created_at",
        ),
    }
    approved_claims = scope_query(Claim.query.filter_by(status=ClaimStatus.APPROVED), Claim, current_workspace.id).count()
    total_claims = scope_query(Claim.query, Claim, current_workspace.id).count()
    resolution_rate = round((approved_claims / total_claims) * 100, 1) if total_claims else 0
    workflow_health = {
        "resolution_rate": resolution_rate,
        "open_matches": suggested_matches_query.count(),
        "active_reports": current_user.lost_items.filter(
            LostItem.status != ItemStatus.ARCHIVED,
            LostItem.organization_id == current_workspace.id,
        ).count()
        + current_user.found_items.filter(
            FoundItem.status != ItemStatus.ARCHIVED,
            FoundItem.organization_id == current_workspace.id,
        ).count(),
    }
    onboarding = build_onboarding_checklist(
        current_user,
        current_workspace,
        stats,
        len(suggested_matches),
        workflow_health["open_matches"],
    )

    return render_template(
        "dashboard/index.html",
        stats=stats,
        lost_items=lost_items,
        found_items=found_items,
        suggested_matches=suggested_matches,
        activity=activity,
        workflow_health=workflow_health,
        item_kind=item_kind,
        onboarding=onboarding,
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
    workspace = get_current_organization()
    notifications = (
        current_user.notifications.filter(Notification.organization_id == workspace.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template("dashboard/notifications.html", notifications=notifications)


@main_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    workspace = get_current_organization()
    notification = current_user.notifications.filter_by(id=notification_id).first()
    if notification is None:
        abort(404)
    if notification.organization_id != workspace.id:
        abort(404)
    notification.is_read = True
    log_audit_event(
        "update",
        "notification",
        entity_id=notification.id,
        before_data={"is_read": False},
        after_data={"is_read": True},
        organization=workspace,
    )
    db.session.commit()
    return redirect(request.referrer or url_for("main.notifications"))


@main_bp.route("/help", methods=["GET", "POST"])
@login_required
def help_center():
    workspace = get_current_organization()
    form = SupportRequestForm()

    if form.validate_on_submit():
        request_record = SupportRequest(
            organization=workspace,
            requester=current_user,
            subject=form.subject.data.strip(),
            category=form.category.data,
            message=form.message.data.strip(),
        )
        db.session.add(request_record)
        db.session.flush()

        support_staff = scope_query(
            User.query.filter(User.role.in_([UserRole.ADMIN, UserRole.SUPPORT, UserRole.MANAGER])),
            User,
            workspace.id,
        ).all()
        for staff in support_staff:
            create_notification(
                staff,
                "New support request",
                f"{current_user.full_name} opened a {form.category.data} request: {request_record.subject}",
                related_url=url_for("main.support_inbox"),
            )

        log_audit_event(
            "create",
            "support_request",
            entity_id=request_record.id,
            after_data={
                "subject": request_record.subject,
                "category": request_record.category,
                "message_length": len(request_record.message),
            },
            organization=workspace,
        )
        dispatch_webhook_event(
            "support.created",
            {
                "id": request_record.id,
                "subject": request_record.subject,
                "category": request_record.category,
                "status": request_record.status.value,
                "requester": current_user.email,
            },
            workspace.id,
        )
        db.session.commit()
        flash("Your support request was submitted.", "success")
        return redirect(url_for("main.help_center"))

    faq_items = [
        {
            "question": "How do I report a lost item?",
            "answer": "Use the Report Lost Item action, add a clear title, location, and date, then save the report.",
        },
        {
            "question": "Who can review a claim?",
            "answer": "Users with review or admin permissions can review claims from the queue.",
        },
        {
            "question": "Can I change my theme?",
            "answer": "Yes. Open Account Settings and choose system, light, or dark mode.",
        },
    ]
    return render_template("dashboard/help.html", form=form, faq_items=faq_items)


@main_bp.route("/integrations")
@login_required
def integrations():
    return redirect(url_for("auth.settings"))


@main_bp.route("/support/inbox")
@login_required
@permission_required("view_support_queue")
def support_inbox():
    workspace = get_current_organization()
    status_filter = request.args.get("status", "open").strip().lower()
    query = scope_query(SupportRequest.query, SupportRequest, workspace.id)
    if status_filter in {"open", "in_progress", "resolved", "closed"}:
        query = query.filter(SupportRequest.status == SupportRequestStatus(status_filter))
    else:
        status_filter = "all"
    requests = scope_query(
        query,
        SupportRequest,
        workspace.id,
    ).order_by(SupportRequest.created_at.desc()).all()
    status_counts = {
        "all": scope_query(SupportRequest.query, SupportRequest, workspace.id).count(),
        "open": scope_query(SupportRequest.query.filter_by(status=SupportRequestStatus.OPEN), SupportRequest, workspace.id).count(),
        "in_progress": scope_query(SupportRequest.query.filter_by(status=SupportRequestStatus.IN_PROGRESS), SupportRequest, workspace.id).count(),
        "resolved": scope_query(SupportRequest.query.filter_by(status=SupportRequestStatus.RESOLVED), SupportRequest, workspace.id).count(),
        "closed": scope_query(SupportRequest.query.filter_by(status=SupportRequestStatus.CLOSED), SupportRequest, workspace.id).count(),
    }
    return render_template(
        "dashboard/support_inbox.html",
        support_requests=requests,
        ticket_form=SupportTicketUpdateForm(),
        status_filter=status_filter,
        status_counts=status_counts,
    )


def _apply_support_update(support_request, next_status, notes, workspace):
    before_status = support_request.status.value
    support_request.status = next_status
    if notes:
        support_request.resolution_notes = notes
    support_request.resolver = current_user
    if next_status in {SupportRequestStatus.RESOLVED, SupportRequestStatus.CLOSED}:
        support_request.resolved_at = datetime.now(timezone.utc)
    log_audit_event(
        "update",
        "support_request",
        entity_id=support_request.id,
        before_data={"status": before_status},
        after_data={"status": support_request.status.value, "notes": support_request.resolution_notes},
        organization=workspace,
    )
    dispatch_webhook_event(
        "support.updated",
        {
            "id": support_request.id,
            "subject": support_request.subject,
            "status": support_request.status.value,
            "notes": support_request.resolution_notes,
        },
        workspace.id,
    )
    if next_status == SupportRequestStatus.IN_PROGRESS:
        notification_title = "Support request in progress"
        notification_message = f"Your request '{support_request.subject}' is now being worked on."
    elif next_status == SupportRequestStatus.RESOLVED:
        notification_title = "Support request resolved"
        notification_message = f"Your request '{support_request.subject}' has been resolved."
    elif next_status == SupportRequestStatus.CLOSED:
        notification_title = "Support request closed"
        notification_message = f"Your request '{support_request.subject}' has been closed."
    else:
        notification_title = "Support request updated"
        notification_message = f"Your request '{support_request.subject}' was updated."

    create_notification(
        support_request.requester,
        notification_title,
        notification_message,
        related_url=url_for("main.help_center"),
    )


@main_bp.route("/support/<int:request_id>/update", methods=["POST"])
@login_required
@permission_required("view_support_queue")
def update_support_request(request_id):
    workspace = get_current_organization()
    support_request = db.session.get(SupportRequest, request_id)
    if support_request is None or support_request.organization_id != workspace.id:
        abort(404)

    form = SupportTicketUpdateForm()
    if not form.validate_on_submit():
        flash("Please complete the ticket update form.", "danger")
        return redirect(url_for("main.support_inbox"))

    next_status = SupportRequestStatus(form.status.data)
    notes = (form.resolution_notes.data or "").strip()
    if next_status in {SupportRequestStatus.RESOLVED, SupportRequestStatus.CLOSED} and not notes:
        flash("Add notes before resolving or closing a ticket.", "danger")
        return redirect(url_for("main.support_inbox"))

    _apply_support_update(support_request, next_status, notes, workspace)
    db.session.commit()
    flash("Support request updated.", "success")
    return redirect(url_for("main.support_inbox"))


@main_bp.route("/support/<int:request_id>/resolve", methods=["POST"])
@login_required
@permission_required("view_support_queue")
def resolve_support_request(request_id):
    workspace = get_current_organization()
    support_request = db.session.get(SupportRequest, request_id)
    if support_request is None or support_request.organization_id != workspace.id:
        abort(404)

    notes = request.form.get("resolution_notes", "").strip()
    if not notes:
        flash("Please add resolution notes before resolving a ticket.", "danger")
        return redirect(url_for("main.support_inbox"))

    _apply_support_update(support_request, SupportRequestStatus.RESOLVED, notes, workspace)
    db.session.commit()
    flash("Support request resolved.", "success")
    return redirect(url_for("main.support_inbox"))
