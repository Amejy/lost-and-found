from collections import Counter, OrderedDict
import csv
import io
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError

from backend.app.decorators import admin_required
from backend.app.extensions import db
from backend.app.models.audit_log import AuditLog
from backend.app.models.claim import Claim, ClaimStatus
from backend.app.models.item import FoundItem, ItemStatus, LostItem
from backend.app.models.notification import NotificationType
from backend.app.models.organization_invite import OrganizationInvite
from backend.app.models.support_request import SupportRequest, SupportRequestStatus
from backend.app.models.webhook import WebhookEndpoint, WebhookEvent
from backend.app.models.user import User, UserRole
from backend.app.forms.workspace import WebhookEndpointForm, WorkspaceInviteForm
from backend.app.services.claims import apply_claim_review, build_claim_review_payload
from backend.app.services.audit import log_audit_event
from backend.app.services.mailer import send_workspace_invite_email
from backend.app.services.mailer import send_password_reset_email
from backend.app.services.notifications import create_notification
from backend.app.services.tenant import get_current_organization, scope_query
from backend.app.services.time import as_naive_utc
from backend.app.services.webhooks import dispatch_webhook_event
from backend.app.services.users import delete_user_with_dependencies


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def get_or_404(model, object_id):
    instance = db.session.get(model, object_id)
    if instance is None:
        abort(404)
    return instance


def reset_password_url(user):
    return url_for("auth.reset_password", token=user.generate_reset_token(), _external=True)


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


def build_date_series(records, attr_name, days=14):
    today = datetime.now(timezone.utc).date()
    buckets = OrderedDict()
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        buckets[day] = 0

    for record in records:
        date_value = getattr(record, attr_name, None)
        if date_value is None:
            continue
        if hasattr(date_value, "date"):
            date_value = date_value.date()
        if date_value in buckets:
            buckets[date_value] += 1

    return {
        "labels": [day.strftime("%b %d") for day in buckets],
        "values": list(buckets.values()),
        "total": sum(buckets.values()),
    }


def percent(numerator, denominator):
    if denominator <= 0:
        return 0
    return round((numerator / denominator) * 100)


def average_hours(records):
    durations = []
    for record in records:
        if not record.reviewed_at:
            continue
        reviewed_at = as_naive_utc(record.reviewed_at)
        created_at = as_naive_utc(record.created_at)
        durations.append((reviewed_at - created_at).total_seconds() / 3600)
    if not durations:
        return 0
    return round(sum(durations) / len(durations), 1)


@admin_bp.route("/")
@admin_required
def dashboard():
    workspace = get_current_organization()
    stats = {
        "users": scope_query(User.query, User, workspace.id).count(),
        "lost_items": scope_query(
            LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED),
            LostItem,
            workspace.id,
        ).count(),
        "found_items": scope_query(
            FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED),
            FoundItem,
            workspace.id,
        ).count(),
        "pending_claims": scope_query(
            Claim.query.filter_by(status=ClaimStatus.PENDING),
            Claim,
            workspace.id,
        ).count(),
    }
    pending_claims = scope_query(
        Claim.query.filter_by(status=ClaimStatus.PENDING),
        Claim,
        workspace.id,
    ).order_by(Claim.created_at.asc()).all()
    recent_users = scope_query(User.query, User, workspace.id).order_by(User.created_at.desc()).limit(6).all()
    recent_claims = scope_query(
        Claim.query.filter(Claim.created_at >= datetime.now(timezone.utc) - timedelta(days=6)),
        Claim,
        workspace.id,
    ).all()
    claim_mix = {
        "pending": scope_query(Claim.query.filter_by(status=ClaimStatus.PENDING), Claim, workspace.id).count(),
        "approved": scope_query(Claim.query.filter_by(status=ClaimStatus.APPROVED), Claim, workspace.id).count(),
        "rejected": scope_query(Claim.query.filter_by(status=ClaimStatus.REJECTED), Claim, workspace.id).count(),
    }
    onboarding = {
        "items": [
            {
                "label": "Invite a teammate",
                "detail": "Add reviewers or support staff to the workspace.",
                "done": workspace.invites.filter_by(accepted_at=None, revoked_at=None).count() > 0,
                "href": url_for("admin.workspaces"),
                "action": "Manage invites",
            },
            {
                "label": "Create an API key",
                "detail": "Connect external tooling or automations.",
                "done": current_user.api_keys.filter_by(revoked_at=None).count() > 0,
                "href": url_for("auth.settings"),
                "action": "Open settings",
            },
            {
                "label": "Create a webhook",
                "detail": "Stream item, claim, and support events out to another system.",
                "done": workspace.webhook_endpoints.filter_by(is_active=True).count() > 0,
                "href": url_for("admin.workspaces"),
                "action": "Configure webhooks",
            },
            {
                "label": "Clear the claim queue",
                "detail": "Keep the review pipeline moving.",
                "done": stats["pending_claims"] == 0,
                "href": url_for("admin.claims"),
                "action": "Open claims",
            },
        ],
    }
    onboarding["completed"] = sum(1 for item in onboarding["items"] if item["done"])
    onboarding["total"] = len(onboarding["items"])
    onboarding["progress"] = round((onboarding["completed"] / onboarding["total"]) * 100) if onboarding["total"] else 0
    return render_template(
        "admin/index.html",
        stats=stats,
        pending_claims=pending_claims,
        recent_users=recent_users,
        claim_activity=build_claim_series(recent_claims),
        claim_mix=claim_mix,
        onboarding=onboarding,
    )


@admin_bp.route("/analytics")
@admin_required
def analytics():
    workspace = get_current_organization()
    window_start = datetime.now(timezone.utc) - timedelta(days=13)

    lost_items = scope_query(LostItem.query, LostItem, workspace.id).all()
    found_items = scope_query(FoundItem.query, FoundItem, workspace.id).all()
    claims = scope_query(Claim.query, Claim, workspace.id).all()
    support_requests = scope_query(SupportRequest.query, SupportRequest, workspace.id).all()
    audit_entries = scope_query(AuditLog.query, AuditLog, workspace.id).all()

    active_lost = sum(1 for item in lost_items if item.status != ItemStatus.ARCHIVED)
    active_found = sum(1 for item in found_items if item.status != ItemStatus.ARCHIVED)
    pending_claims = sum(1 for claim in claims if claim.status == ClaimStatus.PENDING)
    approved_claims = [claim for claim in claims if claim.status == ClaimStatus.APPROVED]
    rejected_claims = [claim for claim in claims if claim.status == ClaimStatus.REJECTED]
    open_support = sum(1 for request in support_requests if request.status in {SupportRequestStatus.OPEN, SupportRequestStatus.IN_PROGRESS})
    resolved_support = sum(1 for request in support_requests if request.status in {SupportRequestStatus.RESOLVED, SupportRequestStatus.CLOSED})

    item_series = {
        "lost": build_date_series(
            [item for item in lost_items if as_naive_utc(item.created_at) >= as_naive_utc(window_start) and item.status != ItemStatus.ARCHIVED],
            "created_at",
        ),
        "found": build_date_series(
            [item for item in found_items if as_naive_utc(item.created_at) >= as_naive_utc(window_start) and item.status != ItemStatus.ARCHIVED],
            "created_at",
        ),
        "claims": build_date_series(
            [claim for claim in claims if as_naive_utc(claim.created_at) >= as_naive_utc(window_start)],
            "created_at",
        ),
        "support": build_date_series(
            [request for request in support_requests if as_naive_utc(request.created_at) >= as_naive_utc(window_start)],
            "created_at",
        ),
        "audit": build_date_series(
            [entry for entry in audit_entries if as_naive_utc(entry.created_at) >= as_naive_utc(window_start)],
            "created_at",
        ),
    }

    category_counter = Counter()
    location_counter = Counter()
    support_category_counter = Counter()
    for item in [*lost_items, *found_items]:
        if item.category:
            category_counter[item.category] += 1
        if item.location:
            location_counter[item.location] += 1
    for request in support_requests:
        if request.category:
            support_category_counter[request.category] += 1

    audit_counter = Counter(entry.action for entry in audit_entries)
    audit_entity_counter = Counter(entry.entity_type for entry in audit_entries)
    avg_resolution_hours = average_hours(approved_claims)

    stats = {
        "users": scope_query(User.query, User, workspace.id).count(),
        "lost_items": len(lost_items),
        "found_items": len(found_items),
        "active_items": active_lost + active_found,
        "active_lost": active_lost,
        "active_found": active_found,
        "claims_total": len(claims),
        "pending_claims": pending_claims,
        "approved_claims": len(approved_claims),
        "rejected_claims": len(rejected_claims),
        "claim_resolution_rate": percent(len(approved_claims), len(claims)),
        "support_open": open_support,
        "support_resolved": resolved_support,
        "support_resolution_rate": percent(resolved_support, len(support_requests)),
        "audit_events": len(audit_entries),
        "audit_events_recent": item_series["audit"]["total"],
        "avg_resolution_hours": avg_resolution_hours,
    }

    top_categories = category_counter.most_common(6)
    top_locations = location_counter.most_common(6)
    top_support_categories = support_category_counter.most_common(5)

    recent_support = (
        scope_query(SupportRequest.query, SupportRequest, workspace.id)
        .order_by(SupportRequest.created_at.desc())
        .limit(6)
        .all()
    )
    recent_audit = (
        scope_query(AuditLog.query, AuditLog, workspace.id)
        .order_by(AuditLog.created_at.desc())
        .limit(8)
        .all()
    )

    return render_template(
        "admin/analytics.html",
        stats=stats,
        item_series=item_series,
        top_categories=top_categories,
        top_locations=top_locations,
        top_support_categories=top_support_categories,
        audit_actions=audit_counter.most_common(6),
        audit_entities=audit_entity_counter.most_common(6),
        recent_support=recent_support,
        recent_audit=recent_audit,
    )


@admin_bp.route("/analytics/export.csv")
@admin_required
def export_analytics():
    workspace = get_current_organization()
    window_start = datetime.now(timezone.utc) - timedelta(days=13)

    lost_items = scope_query(LostItem.query, LostItem, workspace.id).all()
    found_items = scope_query(FoundItem.query, FoundItem, workspace.id).all()
    claims = scope_query(Claim.query, Claim, workspace.id).all()
    support_requests = scope_query(SupportRequest.query, SupportRequest, workspace.id).all()
    audit_entries = scope_query(AuditLog.query, AuditLog, workspace.id).all()

    rows = [
        ["Metric", "Value"],
        ["Users", scope_query(User.query, User, workspace.id).count()],
        ["Lost items", len(lost_items)],
        ["Found items", len(found_items)],
        ["Claims", len(claims)],
        ["Support requests", len(support_requests)],
        ["Audit events", len(audit_entries)],
        ["Resolved claims", sum(1 for claim in claims if claim.status == ClaimStatus.APPROVED)],
        ["Pending claims", sum(1 for claim in claims if claim.status == ClaimStatus.PENDING)],
        ["Open support requests", sum(1 for request in support_requests if request.status in {SupportRequestStatus.OPEN, SupportRequestStatus.IN_PROGRESS})],
        [
            "Recent item/report activity",
            sum(1 for entry in audit_entries if as_naive_utc(entry.created_at) >= as_naive_utc(window_start)),
        ],
    ]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)

    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = 'attachment; filename="foundit-analytics.csv"'
    return response


@admin_bp.route("/claims")
@admin_required
def claims():
    workspace = get_current_organization()
    claims = scope_query(Claim.query, Claim, workspace.id).order_by(Claim.created_at.desc()).all()
    return render_template("admin/claims.html", claims=claims)


@admin_bp.route("/claims/<int:claim_id>/archive", methods=["POST"])
@admin_required
def archive_claim_records(claim_id):
    claim = get_or_404(Claim, claim_id)
    workspace = get_current_organization()
    if claim.organization_id != workspace.id:
        abort(404)
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
    log_audit_event(
        "archive",
        "claim",
        entity_id=claim.id,
        before_data={"status": claim.status.value},
        after_data={"status": "archived"},
        organization=workspace,
    )
    dispatch_webhook_event(
        "claim.reviewed",
        {
            "id": claim.id,
            "status": "archived",
            "found_item_id": claim.found_item_id,
            "claimant_id": claim.claimant_id,
        },
        workspace.id,
    )
    db.session.commit()
    flash("Handoff recorded. The recovered records were archived and removed from the active queues.", "success")
    return redirect(url_for("admin.claims"))


@admin_bp.route("/claims/<int:claim_id>", methods=["GET", "POST"])
@admin_required
def review_claim(claim_id):
    claim = get_or_404(Claim, claim_id)
    workspace = get_current_organization()
    if claim.organization_id != workspace.id:
        abort(404)

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
        log_audit_event(
            "review",
            "claim",
            entity_id=claim.id,
            before_data={"status": ClaimStatus.PENDING.value},
            after_data={
                "status": claim.status.value,
                "decision": decision,
                "notes": notes,
                "closed_other_claims": outcome["closed_other_claims"],
            },
            organization=workspace,
        )
        dispatch_webhook_event(
            "claim.reviewed",
            {
                "id": claim.id,
                "status": claim.status.value,
                "decision": decision,
                "notes": notes,
                "found_item_id": claim.found_item_id,
                "claimant_id": claim.claimant_id,
            },
            workspace.id,
        )
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
    workspace = get_current_organization()
    lost_items = scope_query(
        LostItem.query.filter(LostItem.status != ItemStatus.ARCHIVED),
        LostItem,
        workspace.id,
    ).order_by(LostItem.created_at.desc()).all()
    found_items = scope_query(
        FoundItem.query.filter(FoundItem.status != ItemStatus.ARCHIVED),
        FoundItem,
        workspace.id,
    ).order_by(FoundItem.created_at.desc()).all()
    return render_template("admin/items.html", lost_items=lost_items, found_items=found_items)


@admin_bp.route("/users")
@admin_required
def users():
    workspace = get_current_organization()
    users = scope_query(User.query, User, workspace.id).order_by(User.created_at.desc()).all()
    role_options = [role for role in UserRole]
    return render_template("admin/users.html", users=users, role_options=role_options)


@admin_bp.route("/workspaces", methods=["GET", "POST"])
@admin_required
def workspaces():
    workspace = get_current_organization()
    invite_form = WorkspaceInviteForm()
    webhook_form = WebhookEndpointForm()
    new_webhook_secret = None
    members = scope_query(User.query, User, workspace.id).order_by(User.created_at.asc()).all()
    active_invites = (
        scope_query(
            OrganizationInvite.query.filter(
                OrganizationInvite.accepted_at.is_(None),
                OrganizationInvite.revoked_at.is_(None),
            ),
            OrganizationInvite,
            workspace.id,
        )
        .order_by(OrganizationInvite.created_at.desc())
        .all()
    )
    webhook_endpoints = scope_query(
        WebhookEndpoint.query.filter(WebhookEndpoint.is_active.is_(True)),
        WebhookEndpoint,
        workspace.id,
    ).order_by(WebhookEndpoint.created_at.desc()).all()

    if request.method == "POST":
        form_type = request.form.get("form_type", "")

        if form_type == "invite" and invite_form.validate_on_submit():
            invite = OrganizationInvite(
                organization=workspace,
                email=invite_form.email.data.lower().strip(),
                role=invite_form.role.data,
                creator=current_user,
                expires_at=datetime.now(timezone.utc) + timedelta(days=current_app.config["WORKSPACE_INVITE_TTL_DAYS"]),
            )
            db.session.add(invite)
            db.session.flush()
            accept_url = url_for("auth.invite_details", token=invite.generate_token(), _external=True)
            email_sent = send_workspace_invite_email(invite, accept_url)
            dispatch_webhook_event(
                "invite.created",
                {
                    "id": invite.id,
                    "email": invite.email,
                    "role": invite.role,
                    "expires_at": invite.expires_at.isoformat(),
                    "accept_url": accept_url,
                },
                workspace.id,
            )
            log_audit_event(
                "create",
                "workspace_invite",
                entity_id=invite.id,
                after_data={
                    "email": invite.email,
                    "role": invite.role,
                    "accept_url": accept_url,
                    "email_sent": email_sent,
                },
                organization=workspace,
            )
            db.session.commit()
            flash(
                f"Invite sent to {invite.email}." if email_sent else f"Invite created for {invite.email}. Share the link manually.",
                "success",
            )
            return redirect(url_for("admin.workspaces"))

        if form_type == "webhook" and webhook_form.validate_on_submit():
            endpoint = WebhookEndpoint(
                organization=workspace,
                name=webhook_form.name.data.strip(),
                url=webhook_form.url.data.strip(),
                events=list(webhook_form.events.data),
            )
            db.session.add(endpoint)
            db.session.flush()
            log_audit_event(
                "create",
                "webhook_endpoint",
                entity_id=endpoint.id,
                after_data={
                    "name": endpoint.name,
                    "url": endpoint.url,
                    "events": endpoint.events,
                },
                organization=workspace,
            )
            db.session.commit()
            new_webhook_secret = endpoint.signing_secret
            flash("Webhook endpoint created. Copy the secret below now; it will not be shown again.", "success")
            webhook_endpoints = scope_query(
                WebhookEndpoint.query.filter(WebhookEndpoint.is_active.is_(True)),
                WebhookEndpoint,
                workspace.id,
            ).order_by(WebhookEndpoint.created_at.desc()).all()
            return render_template(
                "admin/workspaces.html",
                workspace=workspace,
                members=members,
                active_invites=active_invites,
                invite_form=invite_form,
                webhook_form=webhook_form,
                webhook_endpoints=webhook_endpoints,
                seat_limit=current_app.config["WORKSPACE_SEAT_LIMIT"],
                seat_count=len(members),
                new_webhook_secret=new_webhook_secret,
            )

    seat_limit = current_app.config["WORKSPACE_SEAT_LIMIT"]
    return render_template(
        "admin/workspaces.html",
        workspace=workspace,
        members=members,
        active_invites=active_invites,
        invite_form=invite_form,
        webhook_form=webhook_form,
        webhook_endpoints=webhook_endpoints,
        seat_limit=seat_limit,
        seat_count=len(members),
        new_webhook_secret=new_webhook_secret,
    )


@admin_bp.route("/workspaces/invites/<int:invite_id>/revoke", methods=["POST"])
@admin_required
def revoke_workspace_invite(invite_id):
    workspace = get_current_organization()
    invite = db.session.get(OrganizationInvite, invite_id)
    if invite is None or invite.organization_id != workspace.id:
        abort(404)
    if invite.accepted_at is not None:
        flash("That invite has already been accepted.", "info")
        return redirect(url_for("admin.workspaces"))
    if invite.revoked_at is not None:
        flash("That invite is already revoked.", "info")
        return redirect(url_for("admin.workspaces"))

    invite.revoked_at = datetime.now(timezone.utc)
    log_audit_event(
        "revoke",
        "workspace_invite",
        entity_id=invite.id,
        before_data={"email": invite.email, "role": invite.role},
        after_data={"revoked_at": invite.revoked_at.isoformat()},
        organization=workspace,
    )
    db.session.commit()
    flash("Workspace invite revoked.", "info")
    return redirect(url_for("admin.workspaces"))


@admin_bp.route("/workspaces/webhooks/<int:endpoint_id>/delete", methods=["POST"])
@admin_required
def delete_webhook_endpoint(endpoint_id):
    workspace = get_current_organization()
    endpoint = db.session.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.organization_id != workspace.id:
        abort(404)

    db.session.delete(endpoint)
    log_audit_event(
        "delete",
        "webhook_endpoint",
        entity_id=endpoint.id,
        before_data={"name": endpoint.name, "url": endpoint.url},
        organization=workspace,
    )
    db.session.commit()
    flash("Webhook endpoint deleted.", "info")
    return redirect(url_for("admin.workspaces"))


@admin_bp.route("/audit-logs")
@admin_required
def audit_logs():
    workspace = get_current_organization()
    query = scope_query(AuditLog.query, AuditLog, workspace.id)
    action = request.args.get("action", "").strip()
    entity_type = request.args.get("entity_type", "").strip()
    actor = request.args.get("actor", "").strip()

    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if actor:
        query = query.join(AuditLog.actor).filter(User.full_name.ilike(f"%{actor}%"))

    entries = query.order_by(AuditLog.created_at.desc()).limit(120).all()
    actions = [row[0] for row in db.session.query(AuditLog.action).filter(AuditLog.organization_id == workspace.id).distinct().order_by(AuditLog.action.asc())]
    entity_types = [row[0] for row in db.session.query(AuditLog.entity_type).filter(AuditLog.organization_id == workspace.id).distinct().order_by(AuditLog.entity_type.asc())]

    return render_template(
        "admin/audit_logs.html",
        entries=entries,
        actions=actions,
        entity_types=entity_types,
        current_filters={"action": action, "entity_type": entity_type, "actor": actor},
    )


@admin_bp.route("/users/<int:user_id>/toggle-role", methods=["POST"])
@admin_required
def toggle_role(user_id):
    user = get_or_404(User, user_id)
    workspace = get_current_organization()
    if user.organization_id != workspace.id:
        abort(404)
    if user.id == current_user.id and user.role == UserRole.ADMIN:
        flash("Use another admin account to change your own access level.", "warning")
        return redirect(url_for("admin.users"))
    if user.role == UserRole.ADMIN and scope_query(User.query.filter_by(role=UserRole.ADMIN), User, workspace.id).count() == 1:
        flash("You cannot remove the last admin account from the system.", "warning")
        return redirect(url_for("admin.users"))
    before_role = user.role.value
    user.role = UserRole.USER if user.role == UserRole.ADMIN else UserRole.ADMIN
    log_audit_event(
        "update",
        "user",
        entity_id=user.id,
        before_data={"role": before_role},
        after_data={"role": user.role.value},
        organization=workspace,
    )
    db.session.commit()
    flash("User role updated.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/set-role", methods=["POST"])
@admin_required
def set_role(user_id):
    user = get_or_404(User, user_id)
    workspace = get_current_organization()
    if user.organization_id != workspace.id:
        abort(404)

    requested_role = request.form.get("role", "").strip()
    try:
        next_role = UserRole(requested_role)
    except ValueError:
        flash("That role is not valid.", "danger")
        return redirect(url_for("admin.users"))

    if user.id == current_user.id and next_role != current_user.role:
        flash("Use another admin account to change your own role.", "warning")
        return redirect(url_for("admin.users"))
    if user.role == UserRole.ADMIN and next_role != UserRole.ADMIN:
        if scope_query(User.query.filter_by(role=UserRole.ADMIN), User, workspace.id).count() == 1:
            flash("You cannot remove the last admin account from the system.", "warning")
            return redirect(url_for("admin.users"))

    before_role = user.role.value
    user.role = next_role
    log_audit_event(
        "update",
        "user",
        entity_id=user.id,
        before_data={"role": before_role},
        after_data={"role": user.role.value},
        organization=workspace,
    )
    db.session.commit()
    flash(f"{user.full_name} now has {user.role.value.title()} access.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/reset-password-link", methods=["POST"])
@admin_required
def reset_password_link(user_id):
    user = get_or_404(User, user_id)
    workspace = get_current_organization()
    if user.organization_id != workspace.id:
        abort(404)
    reset_url = reset_password_url(user)
    email_sent = send_password_reset_email(user, reset_url)
    log_audit_event(
        "create",
        "password_reset_link",
        entity_id=user.id,
        after_data={"email_sent": email_sent, "reset_url": reset_url},
        organization=workspace,
    )
    db.session.commit()
    if email_sent:
        flash(f"Password reset email sent to {user.email}.", "success")
        return redirect(url_for("admin.users"))
    flash(
        f"Password reset link for {user.full_name}: {reset_url}",
        "success",
    )
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = get_or_404(User, user_id)
    workspace = get_current_organization()
    if user.organization_id != workspace.id:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot delete your own account while signed in.", "warning")
        return redirect(url_for("admin.users"))
    if user.role == UserRole.ADMIN and scope_query(User.query.filter_by(role=UserRole.ADMIN), User, workspace.id).count() == 1:
        flash("You cannot delete the last admin account from the system.", "warning")
        return redirect(url_for("admin.users"))

    try:
        deleted_counts = delete_user_with_dependencies(user)
        log_audit_event(
            "delete",
            "user",
            entity_id=user.id,
            before_data={"email": user.email, "role": user.role.value},
            organization=workspace,
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        flash("We could not delete that account right now. Please try again.", "danger")
        return redirect(url_for("admin.users"))

    flash(
        "User deleted. "
        f"Cleaned up {deleted_counts['items']} item(s), {deleted_counts['claims']} claim(s), "
        f"and {deleted_counts['notifications']} notification(s).",
        "info",
    )
    return redirect(url_for("admin.users"))
