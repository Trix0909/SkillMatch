"""The optional invitation must never become an access-control requirement."""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.mfa import PENDING_KEY
from skillmatch.mfa_views import REMINDER_KEY
from skillmatch.models import Account, EmployerProfile, JobSeekerProfile


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MFAReminderTests(TestCase):
    password = "Reminder-Test-832!"

    @classmethod
    def setUpTestData(cls):
        cls.seeker = User.objects.create_user("reminder_seeker", password=cls.password)
        Account.objects.create(user=cls.seeker, role="seeker")
        JobSeekerProfile.objects.create(user=cls.seeker)
        cls.employer = User.objects.create_user("reminder_employer", password=cls.password)
        Account.objects.create(user=cls.employer, role="employer")
        EmployerProfile.objects.create(user=cls.employer, company_name="Nairobi Works")
        cls.admin_user = User.objects.create_superuser("reminder_admin", password=cls.password)

    def sign_in(self, user=None, next_url=None):
        return self.client.post(
            reverse("login"),
            {
                "username": (user or self.seeker).username,
                "password": self.password,
                "next": next_url or "",
            },
        )

    def token(self, device):
        return f"{TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift).token():06d}"

    def test_normal_login_shows_both_choices_with_existing_profile_path(self):
        response = self.sign_in()
        self.assertEqual(response.url, reverse("mfa_reminder"))
        self.assertEqual(self.client.session[SESSION_KEY], str(self.seeker.pk))
        page = self.client.get(response.url)
        self.assertContains(page, "Enable now")
        self.assertContains(page, "Not now")
        self.assertContains(page, "My profile")
        self.assertContains(page, reverse("account_security"))
        self.assertIn("no-store", page["Cache-Control"])
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertFalse(TOTPDevice.objects.exists())

    def test_not_now_preserves_next_and_all_normal_access_without_repeating(self):
        destination = reverse("jobs") + "?q=Python&page=1"
        self.sign_in(next_url=destination)
        self.client.get(reverse("mfa_reminder"))
        response = self.client.post(reverse("mfa_reminder"), {"action": "later", "next": "/wrong/"})
        self.assertRedirects(response, destination)
        self.assertNotIn(REMINDER_KEY, self.client.session)
        self.assertNotIn(PENDING_KEY, self.client.session)
        for name in ("jobs", "recommendations", "profile_edit", "account_security"):
            page = self.client.get(reverse(name))
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, "Not now")
        self.assertRedirects(
            self.client.get(reverse("mfa_reminder")), reverse("home"), fetch_redirect_response=False
        )
        self.assertFalse(TOTPDevice.objects.exists())

    def test_user_can_ignore_invitation_and_navigate_without_choosing(self):
        self.sign_in()
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)
        self.client.get(reverse("mfa_reminder"))
        self.assertEqual(self.client.get(reverse("profile_edit")).status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("mfa_reminder")), reverse("home"), fetch_redirect_response=False
        )

    def test_enable_now_reuses_setup_and_returns_to_original_destination(self):
        destination = reverse("jobs") + "?q=Django"
        self.sign_in(next_url=destination)
        self.client.get(reverse("mfa_reminder"))
        response = self.client.post(reverse("mfa_reminder"), {"action": "enable"})
        self.assertRedirects(response, reverse("mfa_setup"))
        self.assertNotIn(REMINDER_KEY, self.client.session)
        device = TOTPDevice.objects.get(user=self.seeker)
        self.assertFalse(device.confirmed)
        response = self.client.post(reverse("mfa_setup"), {"code": self.token(device)})
        self.assertRedirects(response, destination)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(TOTPDevice.objects.filter(user=self.seeker).count(), 1)

    def test_expired_password_confirmation_reuses_existing_security_page(self):
        self.sign_in()
        invitation = self.client.session[REMINDER_KEY]
        with patch(
            "skillmatch.mfa_views.time.time",
            return_value=invitation["password_verified_at"] + settings.MFA_PENDING_SECONDS + 1,
        ):
            self.assertRedirects(
                self.client.post(reverse("mfa_reminder"), {"action": "enable"}),
                reverse("account_security"),
            )
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertFalse(TOTPDevice.objects.exists())

    def test_existing_enabled_user_gets_only_existing_code_flow(self):
        device = TOTPDevice.objects.create(user=self.seeker, confirmed=True)
        self.assertRedirects(self.sign_in(), reverse("mfa_verify"))
        self.assertNotIn(REMINDER_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertRedirects(
            self.client.post(reverse("mfa_verify"), {"code": self.token(device)}),
            reverse("home"),
            fetch_redirect_response=False,
        )
        self.assertRedirects(
            self.client.get(reverse("mfa_reminder")), reverse("home"), fetch_redirect_response=False
        )

    def test_admin_without_mfa_has_no_optional_choice_or_access_bypass(self):
        self.assertRedirects(self.sign_in(self.admin_user), reverse("mfa_setup"))
        self.assertNotIn(REMINDER_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotContains(self.client.get(reverse("mfa_setup")), "Not now")
        self.assertEqual(
            self.client.post(reverse("mfa_reminder"), {"action": "later"}).status_code, 302
        )
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_admin_with_mfa_keeps_mandatory_verification(self):
        device = TOTPDevice.objects.create(user=self.admin_user, confirmed=True)
        self.assertRedirects(self.sign_in(self.admin_user, "/admin/"), reverse("mfa_verify"))
        self.assertNotIn(REMINDER_KEY, self.client.session)
        self.assertRedirects(
            self.client.post(reverse("mfa_verify"), {"code": self.token(device)}), "/admin/"
        )
        self.assertRedirects(
            self.client.get(reverse("mfa_reminder")), reverse("home"), fetch_redirect_response=False
        )

    def test_future_fresh_login_shows_invitation_again(self):
        self.sign_in()
        self.client.post(reverse("mfa_reminder"), {"action": "later"})
        self.assertNotIn(REMINDER_KEY, self.client.session)
        self.client.post(reverse("logout"))
        self.assertRedirects(self.sign_in(), reverse("mfa_reminder"))
        self.assertTrue(self.client.session[REMINDER_KEY]["shown"])

    def test_employer_gets_correct_navigation_label_and_role_destination(self):
        self.sign_in(self.employer)
        self.assertContains(self.client.get(reverse("mfa_reminder")), "Company profile")
        self.assertRedirects(
            self.client.post(reverse("mfa_reminder"), {"action": "later"}),
            reverse("home"),
            fetch_redirect_response=False,
        )
        self.assertRedirects(self.client.get(reverse("home")), reverse("employer_jobs"))

    def test_direct_link_or_post_cannot_create_new_invitation_or_enrollment(self):
        self.client.force_login(self.seeker)
        for method in (self.client.get, self.client.post):
            self.assertRedirects(
                method(reverse("mfa_reminder"), {"action": "enable"}),
                reverse("home"),
                fetch_redirect_response=False,
            )
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertFalse(TOTPDevice.objects.exists())

    def test_csrf_required_and_unrecognized_actions_do_not_enroll(self):
        self.sign_in()
        self.assertEqual(
            self.client.post(reverse("mfa_reminder"), {"action": "unexpected"}).status_code, 400
        )
        protected = Client(enforce_csrf_checks=True)
        protected.cookies = self.client.cookies
        self.assertEqual(
            protected.post(reverse("mfa_reminder"), {"action": "enable"}).status_code, 403
        )
        self.assertFalse(TOTPDevice.objects.exists())

    def test_external_and_reminder_next_destinations_do_not_redirect_unsafely(self):
        for destination in ("https://evil.example/", reverse("mfa_reminder")):
            self.client.logout()
            self.sign_in(next_url=destination)
            self.assertRedirects(
                self.client.post(reverse("mfa_reminder"), {"action": "later"}),
                reverse("home"),
                fetch_redirect_response=False,
            )

    def test_registration_does_not_create_a_reminder(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new_reminder_user",
                "first_name": "Amina",
                "last_name": "Kamau",
                "email": "amina@example.test",
                "role": "seeker",
                "password1": self.password,
                "password2": self.password,
            },
        )
        self.assertRedirects(response, reverse("profile_edit"))
        self.assertNotIn(REMINDER_KEY, self.client.session)
