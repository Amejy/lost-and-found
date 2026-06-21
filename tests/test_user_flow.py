import tempfile
import unittest
import re
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import (
    Claim,
    ClaimStatus,
    FoundItem,
    ItemMatch,
    ItemStatus,
    LostItem,
    Notification,
    NotificationType,
    User,
    UserRole,
)


class LostFoundUserFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        upload_path = Path(self.temp_dir.name) / "uploads"

        self.app = create_app(
            test_config={
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
                "UPLOAD_FOLDER": str(upload_path),
            }
        )
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            admin = User(
                full_name="System Admin",
                email="admin@lostfound.local",
                role=UserRole.ADMIN,
            )
            admin.set_password("Admin12345!")
            db.session.add(admin)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.temp_dir.cleanup()

    def register_user(self, full_name, email, password="StrongPass123!"):
        response = self.client.post(
            "/register",
            data={
                "full_name": full_name,
                "email": email,
                "password": password,
                "confirm_password": password,
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Account created successfully", response.data)

    def login(self, email, password="StrongPass123!"):
        response = self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome back", response.data)

    def logout(self):
        response = self.client.post("/logout", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You have been logged out", response.data)

    def test_real_user_flow_from_reports_to_admin_approval(self):
        self.register_user("Ada Owner", "owner@example.com")
        self.register_user("Ben Finder", "finder@example.com")

        self.login("owner@example.com")
        lost_response = self.client.post(
            "/lost/report",
            data={
                "title": "Black Dell Backpack",
                "description": "Black Dell backpack with a silver laptop sleeve, math notebook, and charger inside.",
                "category": "Bags",
                "location": "Engineering Building Lobby",
                "date_lost": "2026-03-20",
            },
            follow_redirects=True,
        )
        self.assertEqual(lost_response.status_code, 200)
        self.assertIn(b"Lost item report submitted successfully", lost_response.data)
        self.logout()

        self.login("finder@example.com")
        found_response = self.client.post(
            "/found/report",
            data={
                "title": "Black Laptop Backpack",
                "description": "Found a black backpack with a Dell sleeve, notebooks, and a charger near the engineering lobby.",
                "category": "Bags",
                "location": "Engineering Building Lobby",
                "date_found": "2026-03-21",
            },
            follow_redirects=True,
        )
        self.assertEqual(found_response.status_code, 200)
        self.assertIn(b"Found item report submitted successfully", found_response.data)
        self.logout()

        with self.app.app_context():
            lost_item = LostItem.query.filter_by(title="Black Dell Backpack").one()
            found_item = FoundItem.query.filter_by(title="Black Laptop Backpack").one()
            self.assertEqual(ItemMatch.query.count(), 1)
            self.assertEqual(lost_item.status, ItemStatus.MATCHED)
            self.assertEqual(found_item.status, ItemStatus.MATCHED)
            self.assertEqual(Notification.query.count(), 2)
            found_item_id = found_item.id
            lost_item_id = lost_item.id

        self.login("owner@example.com")
        claim_page = self.client.get(f"/found/{found_item_id}/claim")
        self.assertEqual(claim_page.status_code, 200)
        self.assertIn(b"Use the visual picker below", claim_page.data)

        claim_response = self.client.post(
            f"/found/{found_item_id}/claim",
            data={
                "lost_item_id": str(lost_item_id),
                "proof_text": "This is my backpack. The front pocket contains a TI calculator, campus ID card, and a Dell 65W charger.",
            },
            follow_redirects=True,
        )
        self.assertEqual(claim_response.status_code, 200)
        self.assertIn(b"Claim submitted. An admin will review it shortly.", claim_response.data)
        self.assertIn(b"Track ownership claim progress", claim_response.data)
        self.logout()

        self.login("admin@lostfound.local", "Admin12345!")
        admin_home = self.client.get("/", follow_redirects=True)
        self.assertEqual(admin_home.status_code, 200)
        self.assertIn(b"Operational command center", admin_home.data)
        admin_dashboard_redirect = self.client.get("/dashboard", follow_redirects=True)
        self.assertEqual(admin_dashboard_redirect.status_code, 200)
        self.assertIn(b"Operational command center", admin_dashboard_redirect.data)
        with self.app.app_context():
            claim = Claim.query.one()
            self.assertEqual(claim.status, ClaimStatus.PENDING)
            self.assertEqual(Notification.query.count(), 3)
            claim_id = claim.id

        review_page = self.client.get(f"/admin/claims/{claim_id}")
        self.assertEqual(review_page.status_code, 200)
        self.assertIn(b"Verification summary", review_page.data)
        self.assertIn(b"Compare the records side by side", review_page.data)
        self.assertIn(b"Found vs linked lost report", review_page.data)

        approval_response = self.client.post(
            f"/admin/claims/{claim_id}",
            data={
                "decision": "approve",
                "admin_notes": "Verified the linked lost report, matching location, and the item-specific contents described by the claimant.",
            },
            follow_redirects=True,
        )
        self.assertEqual(approval_response.status_code, 200)
        self.assertIn(b"Claim review saved", approval_response.data)

        admin_claims_page = self.client.get("/admin/claims")
        self.assertEqual(admin_claims_page.status_code, 200)
        self.assertIn(b"Verified", admin_claims_page.data)
        self.assertNotIn(b'<span class="status-badge status-pending">Awaiting verification</span>', admin_claims_page.data)

        admin_dashboard_page = self.client.get("/admin/")
        self.assertEqual(admin_dashboard_page.status_code, 200)
        self.assertNotIn(b"Black Laptop Backpack", admin_dashboard_page.data)

        with self.app.app_context():
            claim = Claim.query.one()
            lost_item = LostItem.query.one()
            found_item = FoundItem.query.one()
            owner = User.query.filter_by(email="owner@example.com").one()
            finder = User.query.filter_by(email="finder@example.com").one()

            self.assertEqual(claim.status, ClaimStatus.APPROVED)
            self.assertEqual(lost_item.status, ItemStatus.RESOLVED)
            self.assertEqual(found_item.status, ItemStatus.RESOLVED)
            self.assertEqual(Notification.query.count(), 4)
            self.assertEqual(owner.notifications.count(), 2)
            self.assertEqual(finder.notifications.count(), 2)

        self.logout()
        self.login("owner@example.com")
        owner_claims = self.client.get("/claims")
        self.assertEqual(owner_claims.status_code, 200)
        self.assertIn(b"Verified", owner_claims.data)
        self.assertNotIn(b'<span class="status-badge status-pending">Awaiting verification</span>', owner_claims.data)
        self.logout()

        self.login("admin@lostfound.local", "Admin12345!")
        archive_response = self.client.post(
            f"/admin/claims/{claim_id}/archive",
            follow_redirects=True,
        )
        self.assertEqual(archive_response.status_code, 200)
        self.assertIn(b"Handoff recorded", archive_response.data)

        with self.app.app_context():
            lost_item = LostItem.query.one()
            found_item = FoundItem.query.one()
            self.assertEqual(lost_item.status, ItemStatus.ARCHIVED)
            self.assertEqual(found_item.status, ItemStatus.ARCHIVED)

        active_lost = self.client.get("/lost-items")
        active_found = self.client.get("/found-items")
        self.assertNotIn(b"Black Dell Backpack", active_lost.data)
        self.assertNotIn(b"Black Laptop Backpack", active_found.data)

        self.logout()
        self.login("owner@example.com")
        owner_dashboard = self.client.get("/dashboard")
        self.assertEqual(owner_dashboard.status_code, 200)
        self.assertIn(b'<strong data-counter="0">0</strong>', owner_dashboard.data)

        archived_claim_attempt = self.client.get(f"/found/{found_item_id}/claim", follow_redirects=True)
        self.assertEqual(archived_claim_attempt.status_code, 200)
        self.assertIn(b"This found item is no longer accepting claims.", archived_claim_attempt.data)

    def test_landing_and_match_widgets_only_show_live_queue_data(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            archived_owner = User(full_name="Archived Owner", email="archived-owner@example.com")
            archived_owner.set_password("StrongPass123!")
            archived_finder = User(full_name="Archived Finder", email="archived-finder@example.com")
            archived_finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder, archived_owner, archived_finder])
            db.session.flush()

            live_lost = LostItem(
                reporter=owner,
                title="Live Laptop",
                description="Silver laptop in a padded sleeve.",
                category="Electronics",
                location="Library",
                date_lost=date(2026, 3, 20),
                status=ItemStatus.MATCHED,
            )
            live_found = FoundItem(
                reporter=finder,
                title="Live Laptop",
                description="Silver laptop in a grey sleeve near the library desk.",
                category="Electronics",
                location="Library",
                date_found=date(2026, 3, 21),
                status=ItemStatus.MATCHED,
            )
            archived_lost = LostItem(
                reporter=archived_owner,
                title="Archived Wallet",
                description="Brown wallet already collected.",
                category="Accessories",
                location="Student Center",
                date_lost=date(2026, 3, 18),
                status=ItemStatus.ARCHIVED,
            )
            archived_found = FoundItem(
                reporter=archived_finder,
                title="Archived Wallet",
                description="Recovered wallet already handed back.",
                category="Accessories",
                location="Student Center",
                date_found=date(2026, 3, 18),
                status=ItemStatus.ARCHIVED,
            )
            db.session.add_all([live_lost, live_found, archived_lost, archived_found])
            db.session.flush()

            live_match = ItemMatch(
                lost_item=live_lost,
                found_item=live_found,
                score=0.92,
                reasons="same category, descriptions overlap, dates are close",
            )
            archived_match = ItemMatch(
                lost_item=archived_lost,
                found_item=archived_found,
                score=0.91,
                reasons="historical archived pair",
            )
            db.session.add_all([live_match, archived_match])
            db.session.commit()

        landing = self.client.get("/")
        self.assertEqual(landing.status_code, 200)
        self.assertIn(b"Live Laptop", landing.data)
        self.assertNotIn(b"Archived Wallet", landing.data)
        self.assertIn(b"Match queue</span>", landing.data)
        self.assertIn(b"<strong>1</strong>", landing.data)

        self.login("owner@example.com")
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Live Laptop", dashboard.data)
        self.assertNotIn(b"Archived Wallet", dashboard.data)

    def test_admin_can_approve_without_manual_note_and_claim_becomes_verified(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            lost_item = LostItem(
                reporter=owner,
                title="Grey Headphones",
                description="Grey over-ear headphones with a small scratch on the left side.",
                category="Electronics",
                location="Lecture Hall",
                date_lost=date(2026, 3, 20),
            )
            found_item = FoundItem(
                reporter=finder,
                title="Grey Headphones",
                description="Found grey headphones near the lecture hall back row.",
                category="Electronics",
                location="Lecture Hall",
                date_found=date(2026, 3, 21),
                status=ItemStatus.CLAIMED,
            )
            db.session.add_all([owner, finder, lost_item, found_item])
            db.session.flush()
            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="These are my headphones because the left earcup has a visible scratch and I keep them in a soft pouch.",
            )
            db.session.add(claim)
            db.session.commit()
            claim_id = claim.id

        self.login("admin@lostfound.local", "Admin12345!")
        response = self.client.post(
            f"/admin/claims/{claim_id}",
            data={
                "decision": "approve",
                "admin_notes": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Claim review saved", response.data)

        with self.app.app_context():
            claim = db.session.get(Claim, claim_id)
            self.assertEqual(claim.status, ClaimStatus.APPROVED)
            self.assertEqual(claim.admin_notes, "Ownership verified by admin review.")

    def test_archiving_verified_claim_is_idempotent(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            lost_item = LostItem(
                reporter=owner,
                title="Archive Test Bag",
                description="Bag already handed back.",
                category="Bags",
                location="Library",
                date_lost=date(2026, 3, 20),
                status=ItemStatus.RESOLVED,
            )
            found_item = FoundItem(
                reporter=finder,
                title="Archive Test Bag",
                description="Recovered bag already verified.",
                category="Bags",
                location="Library",
                date_found=date(2026, 3, 21),
                status=ItemStatus.RESOLVED,
            )
            db.session.add_all([owner, finder, lost_item, found_item])
            db.session.flush()
            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="This bag is mine because it contains my books and charger.",
                status=ClaimStatus.APPROVED,
            )
            db.session.add(claim)
            db.session.commit()
            claim_id = claim.id

        self.login("admin@lostfound.local", "Admin12345!")
        first_archive = self.client.post(f"/admin/claims/{claim_id}/archive", follow_redirects=True)
        self.assertEqual(first_archive.status_code, 200)
        self.assertIn(b"Handoff recorded", first_archive.data)

        second_archive = self.client.post(f"/admin/claims/{claim_id}/archive", follow_redirects=True)
        self.assertEqual(second_archive.status_code, 200)
        self.assertIn(b"already archived", second_archive.data)

        with self.app.app_context():
            claim = db.session.get(Claim, claim_id)
            owner = User.query.filter_by(email="owner@example.com").one()
            self.assertEqual(claim.found_item.status, ItemStatus.ARCHIVED)
            self.assertEqual(claim.lost_item.status, ItemStatus.ARCHIVED)
            archive_notifications = owner.notifications.filter_by(title="Claim archived").count()
            self.assertEqual(archive_notifications, 1)

    def test_approving_one_claim_closes_other_pending_claims_for_same_item(self):
        with self.app.app_context():
            owner = User(full_name="Owner One", email="owner-one@example.com")
            owner.set_password("StrongPass123!")
            rival = User(full_name="Owner Two", email="owner-two@example.com")
            rival.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")

            lost_primary = LostItem(
                reporter=owner,
                title="Blue Wallet",
                description="Blue leather wallet with student card and transport pass.",
                category="Accessories",
                location="Student Center",
                date_lost=date(2026, 3, 20),
            )
            lost_rival = LostItem(
                reporter=rival,
                title="Navy Wallet",
                description="Dark blue wallet with ID and bank cards.",
                category="Accessories",
                location="Student Center",
                date_lost=date(2026, 3, 20),
            )
            found_item = FoundItem(
                reporter=finder,
                title="Blue Wallet",
                description="Found a blue wallet with cards near the student center stairs.",
                category="Accessories",
                location="Student Center",
                date_found=date(2026, 3, 21),
                status=ItemStatus.CLAIMED,
            )
            db.session.add_all([owner, rival, finder, lost_primary, lost_rival, found_item])
            db.session.flush()

            primary_claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_primary,
                proof_text="My wallet has a transport pass, student ID, and a folded receipt in the cash slot.",
            )
            rival_claim = Claim(
                claimant=rival,
                found_item=found_item,
                lost_item=lost_rival,
                proof_text="My wallet has two bank cards and a school identity card inside it.",
            )
            db.session.add_all([primary_claim, rival_claim])
            db.session.commit()
            primary_claim_id = primary_claim.id

        self.login("admin@lostfound.local", "Admin12345!")
        response = self.client.post(
            f"/admin/claims/{primary_claim_id}",
            data={
                "decision": "approve",
                "admin_notes": "Approved after checking the claimant details and the specific contents listed in the report.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"competing pending claim", response.data)

        with self.app.app_context():
            claims = Claim.query.order_by(Claim.id.asc()).all()
            found_item = FoundItem.query.one()
            self.assertEqual(claims[0].status, ClaimStatus.APPROVED)
            self.assertEqual(claims[1].status, ClaimStatus.REJECTED)
            self.assertEqual(found_item.status, ItemStatus.RESOLVED)

    def test_user_root_redirect_stays_in_user_portal(self):
        self.register_user("Plain User", "plain@example.com")
        self.login("plain@example.com")
        response = self.client.get("/", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Operate your recovery workflow like a modern SaaS team.", response.data)

    def test_admin_cannot_demote_own_account(self):
        with self.app.app_context():
            admin = User.query.filter_by(email="admin@lostfound.local").one()
            admin_id = admin.id

        self.login("admin@lostfound.local", "Admin12345!")
        response = self.client.post(f"/admin/users/{admin_id}/toggle-role", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Use another admin account to change your own access level.", response.data)

        with self.app.app_context():
            admin = db.session.get(User, admin_id)
            self.assertEqual(admin.role, UserRole.ADMIN)

    def test_password_reset_request_and_completion_flow(self):
        self.register_user("Reset Me", "reset@example.com")

        request_response = self.client.post(
            "/forgot-password",
            data={"email": "reset@example.com"},
            follow_redirects=True,
        )
        self.assertEqual(request_response.status_code, 200)
        self.assertIn(b"Reset link for reset@example.com", request_response.data)

        match = re.search(rb"/reset-password/([^\"']+)", request_response.data)
        self.assertIsNotNone(match)
        token = match.group(1).decode()

        reset_response = self.client.post(
            f"/reset-password/{token}",
            data={
                "password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
            follow_redirects=True,
        )
        self.assertEqual(reset_response.status_code, 200)
        self.assertIn(b"Password updated successfully", reset_response.data)

        self.login("reset@example.com", "NewStrongPass123!")

    def test_password_reset_request_sends_email_when_available(self):
        self.register_user("Email Reset", "email-reset@example.com")

        with patch("backend.app.routes.auth.send_password_reset_email", return_value=True) as mocked_send_email:
            response = self.client.post(
                "/forgot-password",
                data={"email": "email-reset@example.com"},
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"We sent a password reset email", response.data)
        self.assertNotIn(b"/reset-password/", response.data)
        self.assertTrue(mocked_send_email.called)

    def test_admin_can_generate_reset_link_and_delete_user(self):
        self.register_user("Disposable User", "dispose@example.com")

        with self.app.app_context():
            user = User.query.filter_by(email="dispose@example.com").one()
            user_id = user.id

        self.login("admin@lostfound.local", "Admin12345!")

        reset_link_response = self.client.post(
            f"/admin/users/{user_id}/reset-password-link",
            follow_redirects=True,
        )
        self.assertEqual(reset_link_response.status_code, 200)
        self.assertIn(b"Password reset link for Disposable User", reset_link_response.data)
        self.assertIn(b"/reset-password/", reset_link_response.data)

        delete_response = self.client.post(
            f"/admin/users/{user_id}/delete",
            follow_redirects=True,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertIn(b"User deleted", delete_response.data)

        with self.app.app_context():
            self.assertIsNone(db.session.get(User, user_id))

    def test_admin_can_send_reset_email_when_mail_is_available(self):
        self.register_user("Mail User", "mail-user@example.com")

        with self.app.app_context():
            user = User.query.filter_by(email="mail-user@example.com").one()
            user_id = user.id

        self.login("admin@lostfound.local", "Admin12345!")

        with patch("backend.app.routes.admin.send_password_reset_email", return_value=True) as mocked_send_email:
            response = self.client.post(
                f"/admin/users/{user_id}/reset-password-link",
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password reset email sent to mail-user@example.com", response.data)
        self.assertTrue(mocked_send_email.called)

    def test_admin_cannot_delete_self_account(self):
        with self.app.app_context():
            admin = User.query.filter_by(email="admin@lostfound.local").one()
            admin_id = admin.id

        self.login("admin@lostfound.local", "Admin12345!")
        response = self.client.post(f"/admin/users/{admin_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You cannot delete your own account while signed in.", response.data)

    def test_reporter_can_delete_found_item_with_linked_claim_without_server_error(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            lost_item = LostItem(
                reporter=owner,
                title="Campus Bag",
                description="Black campus bag with books and a charger.",
                category="Bags",
                location="Library",
                date_lost=date(2026, 3, 20),
            )
            found_item = FoundItem(
                reporter=finder,
                title="Campus Bag",
                description="Found black bag with books near the library.",
                category="Bags",
                location="Library",
                date_found=date(2026, 3, 21),
                status=ItemStatus.CLAIMED,
            )
            db.session.add_all([lost_item, found_item])
            db.session.flush()

            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="This is my bag because it has my charger, economics notes, and my timetable in the front pocket.",
            )
            db.session.add(claim)
            db.session.flush()
            db.session.add_all(
                [
                    Notification(
                        user=finder,
                        title="Match alert",
                        message="Open found item",
                        type=NotificationType.MATCH,
                        related_url=f"/found/{found_item.id}",
                    ),
                    Notification(
                        user=finder,
                        title="Claim needs review",
                        message="Open claim review",
                        type=NotificationType.CLAIM,
                        related_url=f"/admin/claims/{claim.id}",
                    ),
                    Notification(
                        user=owner,
                        title="Generic claim update",
                        message="View your claims list",
                        type=NotificationType.CLAIM,
                        related_url="/claims",
                    ),
                ]
            )
            db.session.commit()
            found_item_id = found_item.id

        self.login("finder@example.com")
        response = self.client.post(f"/found/{found_item_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Found item deleted", response.data)

        with self.app.app_context():
            self.assertEqual(FoundItem.query.count(), 0)
            self.assertEqual(Claim.query.count(), 0)
            self.assertEqual(LostItem.query.count(), 1)
            self.assertEqual(LostItem.query.one().status, ItemStatus.OPEN)
            remaining_urls = {notification.related_url for notification in Notification.query.all()}
            self.assertEqual(remaining_urls, {"/claims"})

    def test_admin_can_delete_found_item_with_claim_cleanup(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            lost_item = LostItem(
                reporter=owner,
                title="Blue Folder",
                description="Blue folder with certificates.",
                category="Documents",
                location="Admin Block",
                date_lost=date(2026, 3, 20),
            )
            found_item = FoundItem(
                reporter=finder,
                title="Blue Folder",
                description="Found blue folder at the admin block.",
                category="Documents",
                location="Admin Block",
                date_found=date(2026, 3, 21),
                status=ItemStatus.RESOLVED,
            )
            db.session.add_all([lost_item, found_item])
            db.session.flush()

            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="This folder is mine because it contains my WAEC certificate and a passport photo envelope.",
                status=ClaimStatus.APPROVED,
            )
            db.session.add(claim)
            db.session.commit()
            found_item_id = found_item.id

        self.login("admin@lostfound.local", "Admin12345!")
        response = self.client.post(f"/found/{found_item_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Found item deleted", response.data)

        with self.app.app_context():
            self.assertEqual(FoundItem.query.count(), 0)
            self.assertEqual(Claim.query.count(), 0)

    def test_reporter_can_delete_lost_item_with_linked_claim_cleanup(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            lost_item = LostItem(
                reporter=owner,
                title="Grey Jacket",
                description="Grey jacket with house keys in the inside pocket.",
                category="Clothing",
                location="Main Hall",
                date_lost=date(2026, 3, 20),
            )
            found_item = FoundItem(
                reporter=finder,
                title="Grey Jacket",
                description="Found a grey jacket in the main hall.",
                category="Clothing",
                location="Main Hall",
                date_found=date(2026, 3, 21),
                status=ItemStatus.CLAIMED,
            )
            db.session.add_all([lost_item, found_item])
            db.session.flush()

            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="This jacket is mine because the inside pocket contains my keys and a folded bus receipt.",
            )
            db.session.add(claim)
            db.session.flush()
            db.session.add(
                Notification(
                    user=owner,
                    title="Open lost item",
                    message="Stale lost item link",
                    type=NotificationType.MATCH,
                    related_url=f"/lost/{lost_item.id}",
                )
            )
            db.session.commit()
            lost_item_id = lost_item.id

        self.login("owner@example.com")
        response = self.client.post(f"/lost/{lost_item_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Lost item deleted", response.data)

        with self.app.app_context():
            self.assertEqual(LostItem.query.count(), 0)
            self.assertEqual(Claim.query.count(), 0)
            self.assertEqual(FoundItem.query.count(), 1)
            self.assertEqual(FoundItem.query.one().status, ItemStatus.OPEN)
            self.assertEqual(Notification.query.count(), 0)

    def test_deleting_matched_found_item_reopens_surviving_lost_report(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            lost_item = LostItem(
                reporter=owner,
                title="Green Water Bottle",
                description="Metal green water bottle with university sticker.",
                category="Accessories",
                location="Gym",
                date_lost=date(2026, 3, 20),
                status=ItemStatus.MATCHED,
            )
            found_item = FoundItem(
                reporter=finder,
                title="Green Bottle",
                description="Found a green metal bottle near the gym entrance.",
                category="Accessories",
                location="Gym",
                date_found=date(2026, 3, 21),
                status=ItemStatus.MATCHED,
            )
            db.session.add_all([lost_item, found_item])
            db.session.flush()

            db.session.add(
                ItemMatch(
                    lost_item=lost_item,
                    found_item=found_item,
                    score=0.88,
                    reasons="same category, descriptions overlap, locations are similar",
                )
            )
            db.session.commit()
            found_item_id = found_item.id

        self.login("finder@example.com")
        response = self.client.post(f"/found/{found_item_id}/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Found item deleted", response.data)

        with self.app.app_context():
            self.assertEqual(FoundItem.query.count(), 0)
            self.assertEqual(ItemMatch.query.count(), 0)
            surviving_lost_item = LostItem.query.one()
            self.assertEqual(surviving_lost_item.status, ItemStatus.OPEN)

    def test_finalized_claim_cannot_be_reviewed_twice(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            lost_item = LostItem(
                reporter=owner,
                title="Calculator",
                description="Scientific calculator with initials at the back.",
                category="Electronics",
                location="Classroom",
                date_lost=date(2026, 3, 20),
            )
            found_item = FoundItem(
                reporter=finder,
                title="Calculator",
                description="Found a calculator in the classroom.",
                category="Electronics",
                location="Classroom",
                date_found=date(2026, 3, 21),
                status=ItemStatus.CLAIMED,
            )
            db.session.add_all([lost_item, found_item])
            db.session.flush()

            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="This calculator is mine because my initials are written behind the battery cover.",
                status=ClaimStatus.APPROVED,
            )
            db.session.add(claim)
            db.session.commit()
            claim_id = claim.id

        self.login("admin@lostfound.local", "Admin12345!")
        response = self.client.post(
            f"/admin/claims/{claim_id}",
            data={"decision": "reject", "admin_notes": "Trying to re-review"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"This claim has already been finalized", response.data)

        with self.app.app_context():
            claim = db.session.get(Claim, claim_id)
            self.assertEqual(claim.status, ClaimStatus.APPROVED)

    def test_reporter_cannot_claim_own_found_item(self):
        with self.app.app_context():
            reporter = User(full_name="Finder", email="finder@example.com")
            reporter.set_password("StrongPass123!")
            db.session.add(reporter)
            db.session.flush()

            found_item = FoundItem(
                reporter=reporter,
                title="Phone",
                description="Found a black phone.",
                category="Electronics",
                location="Hallway",
                date_found=date(2026, 3, 21),
            )
            db.session.add(found_item)
            db.session.commit()
            found_item_id = found_item.id

        self.login("finder@example.com")
        response = self.client.get(f"/found/{found_item_id}/claim", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"You cannot submit a claim for an item you reported as found.", response.data)

    def test_archived_lost_report_cannot_be_linked_to_new_claim(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            archived_lost = LostItem(
                reporter=owner,
                title="Archived ID Card",
                description="School ID card already recovered.",
                category="Documents",
                location="Faculty Building",
                date_lost=date(2026, 3, 20),
                status=ItemStatus.ARCHIVED,
            )
            found_item = FoundItem(
                reporter=finder,
                title="ID Card",
                description="Found an ID card at the faculty building.",
                category="Documents",
                location="Faculty Building",
                date_found=date(2026, 3, 21),
            )
            db.session.add_all([archived_lost, found_item])
            db.session.commit()
            archived_lost_id = archived_lost.id
            found_item_id = found_item.id

        self.login("owner@example.com")
        response = self.client.post(
            f"/found/{found_item_id}/claim",
            data={
                "lost_item_id": str(archived_lost_id),
                "proof_text": "This ID card belongs to me and has already been part of an older completed recovery case.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no longer eligible to be linked to a new claim", response.data)

    def test_api_claim_creation_uses_real_admin_review_link(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            found_item = FoundItem(
                reporter=finder,
                title="USB Drive",
                description="Found a USB drive in the lab.",
                category="Electronics",
                location="Computer Lab",
                date_found=date(2026, 3, 21),
            )
            db.session.add_all([owner, finder, found_item])
            db.session.commit()
            found_item_id = found_item.id

        self.login("owner@example.com")
        response = self.client.post(
            "/api/v1/claims",
            json={
                "found_item_id": found_item_id,
                "proof_text": "This USB drive is mine because it has a red cap and my project backup folders inside it.",
            },
        )
        self.assertEqual(response.status_code, 201)

        with self.app.app_context():
            claim = Claim.query.one()
            notification = Notification.query.filter_by(type=NotificationType.CLAIM).one()
            self.assertEqual(notification.related_url, f"/found/{claim.found_item_id}")

    def test_user_cannot_submit_duplicate_claims_for_same_item(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            found_item = FoundItem(
                reporter=finder,
                title="Wallet",
                description="Black wallet near the cafeteria.",
                category="Accessories",
                location="Cafeteria",
                date_found=date(2026, 3, 21),
            )
            db.session.add_all([owner, finder, found_item])
            db.session.commit()
            found_item_id = found_item.id

        self.login("owner@example.com")
        first_claim = self.client.post(
            f"/found/{found_item_id}/claim",
            data={"lost_item_id": "0", "proof_text": "This wallet is mine because it contains my ID."},
            follow_redirects=True,
        )
        self.assertEqual(first_claim.status_code, 200)
        self.assertIn(b"Claim submitted", first_claim.data)

        second_claim = self.client.post(
            f"/found/{found_item_id}/claim",
            data={"lost_item_id": "0", "proof_text": "Trying to submit a second claim."},
            follow_redirects=True,
        )
        self.assertEqual(second_claim.status_code, 200)
        self.assertIn(b"already submitted a claim", second_claim.data)

    def test_no_new_claims_allowed_after_approved(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            other_user = User(full_name="Other", email="other@example.com")
            other_user.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            found_item = FoundItem(
                reporter=finder,
                title="Notebook",
                description="Spiral notebook.",
                category="Documents",
                location="Library",
                date_found=date(2026, 3, 21),
                status=ItemStatus.CLAIMED,
            )
            lost_item = LostItem(
                reporter=owner,
                title="Notebook",
                description="My spiral notebook.",
                category="Documents",
                location="Library",
                date_lost=date(2026, 3, 20),
            )
            db.session.add_all([owner, other_user, finder, found_item, lost_item])
            db.session.flush()
            claim = Claim(
                claimant=owner,
                found_item=found_item,
                lost_item=lost_item,
                proof_text="This notebook has my name inside the cover.",
                status=ClaimStatus.APPROVED,
            )
            db.session.add(claim)
            db.session.commit()
            found_item_id = found_item.id

        self.login("other@example.com")
        response = self.client.get(f"/found/{found_item_id}/claim", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"already has a verified ownership claim", response.data)

    def test_found_item_reporter_can_see_claimant_details(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            found_item = FoundItem(
                reporter=finder,
                title="Document",
                description="Certificate document.",
                category="Documents",
                location="Office",
                date_found=date(2026, 3, 21),
            )
            db.session.add_all([owner, finder, found_item])
            db.session.flush()
            claim = Claim(
                claimant=owner,
                found_item=found_item,
                proof_text="This document has my name and signature.",
            )
            db.session.add(claim)
            db.session.commit()
            found_item_id = found_item.id

        self.login("finder@example.com")
        response = self.client.get(f"/found/{found_item_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Owner", response.data)
        self.assertIn(b"owner@example.com", response.data)

    def test_resolved_items_cannot_be_edited_after_finalization(self):
        with self.app.app_context():
            owner = User(full_name="Owner", email="owner@example.com")
            owner.set_password("StrongPass123!")
            finder = User(full_name="Finder", email="finder@example.com")
            finder.set_password("StrongPass123!")
            db.session.add_all([owner, finder])
            db.session.flush()

            lost_item = LostItem(
                reporter=owner,
                title="Locked Laptop",
                description="Laptop already verified and handed over.",
                category="Electronics",
                location="Library",
                date_lost=date(2026, 3, 20),
                status=ItemStatus.RESOLVED,
            )
            found_item = FoundItem(
                reporter=finder,
                title="Locked Laptop",
                description="Found laptop already verified and resolved.",
                category="Electronics",
                location="Library",
                date_found=date(2026, 3, 21),
                status=ItemStatus.RESOLVED,
            )
            db.session.add_all([lost_item, found_item])
            db.session.commit()
            lost_item_id = lost_item.id
            found_item_id = found_item.id

        self.login("owner@example.com")
        lost_edit = self.client.get(f"/lost/{lost_item_id}/edit", follow_redirects=True)
        self.assertEqual(lost_edit.status_code, 200)
        self.assertIn(b"locked because the case has already been finalized", lost_edit.data)
        self.logout()

        self.login("finder@example.com")
        found_edit = self.client.get(f"/found/{found_item_id}/edit", follow_redirects=True)
        self.assertEqual(found_edit.status_code, 200)
        self.assertIn(b"locked because the case has already been finalized", found_edit.data)


if __name__ == "__main__":
    unittest.main()
