from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.mfa import PENDING_KEY
from skillmatch.models import Account, EmployerProfile, JobSeekerProfile


class PrivacyTests(TestCase):
    def test_anonymous_public_policy_and_links(self):
        response = self.client.get("/privacy/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy policy")
        self.assertContains(
            response,
            '<a href="mailto:trina.kinyua@strathmore.edu">trina.kinyua@strathmore.edu</a>',
            html=True,
        )
        self.assertEqual(self.client.head("/privacy/").status_code, 200)
        self.assertEqual(self.client.post("/privacy/").status_code, 405)
        for page in ("landing", "login", "register"):
            with self.subTest(page=page):
                self.assertContains(self.client.get(reverse(page)), 'href="/privacy/"')

    def test_signed_in_roles_can_read_without_redirect_or_private_shell(self):
        for role in ("seeker", "employer"):
            with self.subTest(role=role):
                user = User.objects.create_user(f"policy_{role}")
                Account.objects.create(user=user, active_role=role)
                if role == "seeker":
                    JobSeekerProfile.objects.create(user=user)
                else:
                    EmployerProfile.objects.create(user=user, company_name="Private Company")
                self.client.force_login(user)
                response = self.client.get(reverse("privacy"))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, user.username)
                self.assertNotContains(response, "Private Company")
                self.assertIn(SESSION_KEY, self.client.session)
                self.client.logout()

    def test_pending_sign_in_is_unchanged(self):
        session = self.client.session
        pending = {"mode": "login", "user_id": 123, "started": 100}
        session[PENDING_KEY] = pending
        session.save()
        self.assertEqual(self.client.get(reverse("privacy")).status_code, 200)
        self.assertEqual(self.client.session[PENDING_KEY], pending)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_privacy_exception_does_not_bypass_mfa_on_other_routes(self):
        for staff in (False, True):
            with self.subTest(staff=staff):
                user = User.objects.create_user(f"protected_{staff}", is_staff=staff)
                if not staff:
                    TOTPDevice.objects.create(user=user, confirmed=True)
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse("privacy")).status_code, 200)
                self.assertIn(SESSION_KEY, self.client.session)
                self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")))
                self.assertNotIn(SESSION_KEY, self.client.session)
