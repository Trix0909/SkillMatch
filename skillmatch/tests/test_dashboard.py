from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.template import engines
from django.template.loader import render_to_string
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from skillmatch.models import Account, JobSeekerProfile, Skill


class DashboardPresentationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="dashboard_seeker", first_name="Amina", last_name="Kamau"
        )
        Account.objects.create(user=cls.user, active_role="seeker")
        cls.profile = JobSeekerProfile.objects.create(user=cls.user)

    def test_greeting_uses_nairobi_time_at_each_boundary(self):
        self.client.force_login(self.user)
        for hour, minute, expected in [
            (1, 59, "Good evening"),  # 04:59 in Nairobi
            (2, 0, "Good morning"),
            (8, 59, "Good morning"),
            (9, 0, "Good afternoon"),
            (13, 59, "Good afternoon"),
            (14, 0, "Good evening"),
            (20, 59, "Good evening"),
            (21, 0, "Good evening"),  # Midnight in Nairobi
        ]:
            with self.subTest(utc_hour=hour, minute=minute):
                now = datetime(2026, 10, 28, hour, minute, tzinfo=UTC)
                with (
                    timezone.override("Africa/Nairobi"),
                    patch("skillmatch.views.timezone.now", return_value=now),
                ):
                    response = self.client.get(reverse("recommendations"))
                self.assertEqual(response.context["greeting"], expected)
                self.assertContains(response, f"{expected}, <span>Amina</span>")

    def test_progress_tracks_existing_essentials_and_completion_rule(self):
        for bio, portfolio, has_skill, expected in [
            ("", "", False, 0),
            ("  ", "\n", False, 0),
            ("", "", True, 33),
            ("My professional summary", "", True, 67),
            ("My professional summary", "My project portfolio", True, 100),
        ]:
            with self.subTest(expected=expected, bio=bio):
                self.profile.bio = bio
                self.profile.portfolio = portfolio
                if has_skill:
                    Skill.objects.get_or_create(profile=self.profile, name="Python")
                html = render_to_string(
                    "skillmatch/includes/dashboard_profile_progress.html",
                    {"profile": self.profile},
                )
                self.assertIn(f'aria-valuenow="{expected}"', html)
                self.assertIn(f'stroke-dasharray="{expected} 100"', html)
                self.assertEqual(expected == 100, self.profile.is_complete)
        # Computing presentation values does not save profile edits.
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, "")
        self.assertEqual(self.profile.portfolio, "")

    def test_dashboard_renders_without_custom_template_tag_libraries(self):
        self.client.force_login(self.user)
        engine = engines["django"].engine
        static = engine.template_libraries["static"]
        # Reproduce the failing server's registry, which did not know "dashboard".
        with patch.dict(engine.template_libraries, {"static": static}, clear=True):
            for loader in engine.template_loaders:
                loader.reset()
            response = self.client.get(reverse("recommendations"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Your profile progress")
        for loader in engine.template_loaders:
            loader.reset()

    def test_partial_ring_and_help_use_actual_missing_field(self):
        self.profile.bio = "A professional summary"
        self.profile.save(update_fields=["bio"])
        Skill.objects.create(profile=self.profile, name="Python")
        self.client.force_login(self.user)
        response = self.client.get(reverse("recommendations"))
        self.assertContains(response, 'aria-valuenow="67"')
        self.assertContains(response, 'stroke-dasharray="67 100"')
        self.assertContains(response, "Add your project portfolio")
        self.assertContains(response, "2 of 3 profile essentials added")

    def test_account_menu_preserves_csrf_protected_post_logout(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.get(reverse("recommendations"))
        self.assertContains(response, "Amina Kamau")
        self.assertContains(response, reverse("profile_detail", args=[self.profile.pk]))
        self.assertContains(response, "Log out")
        self.assertNotContains(response, 'class="account-card"')
        self.assertNotContains(response, 'class="mobile-signout"')
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(reverse("logout"), {"csrfmiddlewaretoken": token}).status_code, 302
        )
        self.assertNotIn("_auth_user_id", client.session)

    def test_other_pages_keep_their_existing_sidebar(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("jobs"))
        self.assertContains(response, 'class="account-card"')
        self.assertContains(response, "A BETTER WAY TO CONNECT")
        self.assertNotContains(response, "seeker-dashboard.css")
