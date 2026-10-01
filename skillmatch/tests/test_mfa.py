"""End-to-end HTTP/session tests for optional user and mandatory admin TOTP."""

from base64 import b32encode
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.mfa import PENDING_KEY
from skillmatch.models import Account, EmployerProfile, JobSeekerProfile


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MFATests(TestCase):
    password = "Authenticator-Test-832!"

    @classmethod
    def setUpTestData(cls):
        cls.seeker = User.objects.create_user("mfa_seeker", password=cls.password)
        Account.objects.create(user=cls.seeker, role="seeker")
        JobSeekerProfile.objects.create(user=cls.seeker)
        cls.employer = User.objects.create_user("mfa_employer", password=cls.password)
        Account.objects.create(user=cls.employer, role="employer")
        EmployerProfile.objects.create(user=cls.employer, company_name="Nairobi Works")
        cls.admin_user = User.objects.create_superuser("mfa_admin", password=cls.password)

    def setUp(self):
        self.now = 1800000000.0
        timer = patch("django_otp.plugins.otp_totp.models.time.time", side_effect=lambda: self.now)
        timer.start()
        self.addCleanup(timer.stop)

    def code(self, device, offset=0):
        token = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
        token.time = self.now + offset
        return f"{token.token():06d}"

    def wrong_code(self, device):
        valid = {self.code(device, shift) for shift in (-30, 0, 30)}
        return next(f"{n:06d}" for n in range(10) if f"{n:06d}" not in valid)

    def password_login(self, user=None, *, next_url=None, client=None):
        data = {"username": (user or self.seeker).username, "password": self.password}
        if next_url:
            data["next"] = next_url
        client = client or self.client
        response = client.post(reverse("login"), data)
        # Existing MFA tests exercise the unchanged flow after declining the
        # optional invitation. Dedicated reminder tests cover both choices.
        if response.status_code == 302 and response.url == reverse("mfa_reminder"):
            response = client.post(reverse("mfa_reminder"), {"action": "later"})
        return response

    def device(self, user=None, *, confirmed=True):
        return TOTPDevice.objects.create(user=user or self.seeker, confirmed=confirmed)

    def start_enrollment(self, client=None):
        client = client or self.client
        response = client.post(reverse("account_security"), {"password": self.password})
        self.assertRedirects(response, reverse("mfa_setup"))
        return TOTPDevice.objects.get(user=self.seeker)

    def assert_no_login(self, client=None):
        self.assertNotIn(SESSION_KEY, (client or self.client).session)
        self.assertNotIn(DEVICE_ID_SESSION_KEY, (client or self.client).session)

    def test_normal_password_only_login_and_role_destinations_are_unchanged(self):
        for user, target, pages in [
            (self.seeker, "recommendations", ["profile_edit", "jobs", "recommendations"]),
            (self.employer, "employer_jobs", ["profile_edit", "employer_jobs", "candidates"]),
        ]:
            self.client.logout()
            response = self.password_login(user)
            self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
            self.assertRedirects(self.client.get(reverse("home")), reverse(target))
            for name in pages:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
            self.assertNotIn(PENDING_KEY, self.client.session)
            self.assertFalse(TOTPDevice.objects.filter(user=user).exists())

    def test_registration_remains_optional_for_both_roles(self):
        for role in ("seeker", "employer"):
            self.client.logout()
            response = self.client.post(
                reverse("register"),
                {
                    "username": "new_" + role,
                    "first_name": "Amina",
                    "last_name": "Kamau",
                    "email": role + "@example.test",
                    "role": role,
                    "company_name": "Nairobi SME",
                    "password1": self.password,
                    "password2": self.password,
                },
            )
            self.assertRedirects(response, reverse("profile_edit"))
            user = User.objects.get(username="new_" + role)
            self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
            self.assertEqual(user.account.role, role)
            self.assertFalse(TOTPDevice.objects.filter(user=user).exists())

    def test_settings_are_private_and_linked_from_profile(self):
        self.assertEqual(self.client.get(reverse("account_security")).status_code, 302)
        self.password_login()
        self.assertContains(self.client.get(reverse("profile_edit")), reverse("account_security"))
        self.assertContains(self.client.get(reverse("account_security")), "Not enabled")
        self.assertFalse(TOTPDevice.objects.exists())

    def test_setup_requires_fresh_password_and_direct_get_does_not_create_device(self):
        self.password_login()
        self.assertRedirects(self.client.get(reverse("mfa_setup")), reverse("account_security"))
        response = self.client.post(reverse("account_security"), {"password": "incorrect"})
        self.assertContains(response, "Your password was incorrect")
        self.assertFalse(TOTPDevice.objects.exists())

    def test_qr_and_manual_key_use_standard_per_user_provisioning(self):
        self.password_login()
        device = self.start_enrollment()
        response = self.client.get(reverse("mfa_setup"))
        with patch("skillmatch.mfa_views.segno.make", wraps=__import__("segno").make) as make:
            self.client.get(reverse("mfa_setup"))
            uri = make.call_args.args[0]
        parsed = urlsplit(uri)
        self.assertEqual((parsed.scheme, parsed.netloc), ("otpauth", "totp"))
        self.assertEqual(unquote(parsed.path), "/SkillMatch:" + self.seeker.username)
        values = parse_qs(parsed.query)
        self.assertEqual(values["issuer"], ["SkillMatch"])
        self.assertEqual(values["digits"], ["6"])
        self.assertEqual(values["period"], ["30"])
        self.assertEqual(values["secret"], [b32encode(device.bin_key).decode()])
        self.assertContains(response, 'src="data:image/svg+xml')
        self.assertContains(response, b32encode(device.bin_key).decode())
        self.assertContains(response, "Microsoft Authenticator")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertNotIn(device.key, str(dict(self.client.session)))
        self.assertFalse(device.confirmed)

    def test_invalid_setup_keeps_device_unconfirmed_and_throttle_persists(self):
        self.password_login()
        device = self.start_enrollment()
        response = self.client.post(reverse("mfa_setup"), {"code": self.wrong_code(device)})
        self.assertContains(response, "Invalid authentication code")
        device.refresh_from_db()
        self.assertFalse(device.confirmed)
        self.assertEqual(device.throttling_failure_count, 1)
        self.assertContains(self.client.get(reverse("account_security")), "Not enabled")
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)

    def test_successful_setup_enables_mfa_only_after_valid_code(self):
        self.password_login()
        device = self.start_enrollment()
        old_session = self.client.session.session_key
        response = self.client.post(reverse("mfa_setup"), {"code": self.code(device)})
        self.assertRedirects(response, reverse("account_security"))
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], device.persistent_id)
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertNotEqual(old_session, self.client.session.session_key)
        self.assertContains(self.client.get(reverse("account_security")), "Status: Enabled")
        self.assertNotContains(self.client.get(reverse("account_security")), device.key)

    def test_revisits_and_repeat_start_do_not_create_duplicate_devices(self):
        self.password_login()
        device = self.start_enrollment()
        self.client.get(reverse("mfa_setup"))
        self.start_enrollment()
        self.assertEqual(TOTPDevice.objects.filter(user=self.seeker).count(), 1)
        self.client.post(reverse("mfa_setup"), {"code": self.code(device)})
        self.client.get(reverse("mfa_setup"))
        self.client.post(reverse("account_security"), {"password": self.password})
        self.assertEqual(TOTPDevice.objects.filter(user=self.seeker).count(), 1)

    def test_unconfirmed_device_does_not_require_mfa_on_normal_login(self):
        self.device(confirmed=False)
        self.assertRedirects(self.password_login(), reverse("home"), fetch_redirect_response=False)
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_enabled_user_password_alone_is_not_authenticated(self):
        self.device()
        response = self.password_login(next_url=reverse("jobs") + "?q=Python")
        self.assertRedirects(response, reverse("mfa_verify"))
        self.assert_no_login()
        for url in [
            reverse("jobs"),
            reverse("profile_edit"),
            reverse("account_security"),
            "/admin/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.assert_no_login()

    def test_incorrect_code_rejected_then_valid_code_completes_login(self):
        device = self.device()
        self.password_login(next_url=reverse("jobs") + "?q=Python")
        session_key = self.client.session.session_key
        response = self.client.post(reverse("mfa_verify"), {"code": self.wrong_code(device)})
        self.assertContains(response, "Invalid authentication code")
        self.assert_no_login()
        with patch(
            "django_otp.models.timezone.now", return_value=timezone.now() + timedelta(seconds=2)
        ):
            response = self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
        self.assertRedirects(response, reverse("jobs") + "?q=Python")
        self.assertEqual(self.client.session[SESSION_KEY], str(self.seeker.pk))
        self.assertNotEqual(session_key, self.client.session.session_key)
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_admin_without_device_must_enroll_before_access(self):
        response = self.password_login(self.admin_user, next_url="/admin/auth/user/")
        self.assertRedirects(response, reverse("mfa_setup"))
        self.assert_no_login()
        self.assertEqual(self.client.get("/admin/auth/user/").status_code, 302)
        device = TOTPDevice.objects.get(user=self.admin_user)
        self.assertFalse(device.confirmed)
        self.assertContains(self.client.get(reverse("mfa_setup")), "required for administrators")
        response = self.client.post(reverse("mfa_setup"), {"code": self.code(device)})
        self.assertRedirects(response, "/admin/auth/user/")
        self.assertTrue(TOTPDevice.objects.get(pk=device.pk).confirmed)

    def test_staff_and_superuser_flags_both_trigger_mandatory_mfa(self):
        for staff, superuser in [(True, False), (False, True)]:
            self.client.logout()
            self.seeker.is_staff, self.seeker.is_superuser = staff, superuser
            self.seeker.save()
            self.assertRedirects(self.password_login(), reverse("mfa_setup"))
            self.assert_no_login()

    def test_admin_with_device_requires_valid_code(self):
        device = self.device(self.admin_user)
        self.assertRedirects(
            self.password_login(self.admin_user, next_url="/admin/"), reverse("mfa_verify")
        )
        self.assert_no_login()
        response = self.client.post(reverse("mfa_verify"), {"code": self.wrong_code(device)})
        self.assertContains(response, "Invalid authentication code")
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        with patch(
            "django_otp.models.timezone.now", return_value=timezone.now() + timedelta(seconds=2)
        ):
            response = self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
        self.assertRedirects(response, "/admin/")
        self.assertEqual(self.client.get("/admin/auth/user/").status_code, 200)

    def test_direct_admin_login_uses_shared_login_even_for_post(self):
        for method in (self.client.get, self.client.post):
            response = method(
                "/admin/login/?next=/admin/auth/user/",
                {"username": self.admin_user.username, "password": self.password},
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("login")))
            self.assert_no_login()

    def test_old_password_only_admin_sessions_are_rejected(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)
        self.assert_no_login()
        self.assertTrue(response.url.startswith(reverse("login")))

    def test_old_sessions_on_other_devices_require_factors_after_enrollment(self):
        other = Client()
        self.password_login(client=other)
        self.password_login()
        device = self.start_enrollment()
        self.client.post(reverse("mfa_setup"), {"code": self.code(device)})
        response = other.get(reverse("jobs"))
        self.assertEqual(response.status_code, 302)
        self.assert_no_login(other)

    def test_promoted_user_session_cannot_bypass_admin_mfa(self):
        self.password_login()
        User.objects.filter(pk=self.seeker.pk).update(is_staff=True)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 302)
        self.assert_no_login()

    def test_otp_admin_permissions_are_enforced_without_the_policy_middleware(self):
        device = self.device(self.admin_user)
        middleware = [
            m for m in settings.MIDDLEWARE if m != "skillmatch.mfa.MFAEnforcementMiddleware"
        ]
        with override_settings(MIDDLEWARE=middleware):
            client = Client()
            client.force_login(self.admin_user)
            self.assertEqual(client.get("/admin/").status_code, 302)
            session = client.session
            session[DEVICE_ID_SESSION_KEY] = device.persistent_id
            session.save()
            self.assertEqual(client.get("/admin/").status_code, 200)

    def test_device_management_is_not_an_admin_bypass(self):
        self.assertFalse(admin.site.is_registered(TOTPDevice))

    def test_logout_clears_mfa_and_next_login_requires_both_factors(self):
        device = self.device()
        self.password_login()
        self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assert_no_login()
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertRedirects(self.password_login(), reverse("mfa_verify"))
        self.assert_no_login()

    def test_replay_of_a_successful_code_is_rejected(self):
        device = self.device()
        self.password_login()
        token = self.code(device)
        self.client.post(reverse("mfa_verify"), {"code": token})
        self.client.post(reverse("logout"))
        self.password_login()
        response = self.client.post(reverse("mfa_verify"), {"code": token})
        self.assertContains(response, "Invalid authentication code")
        self.assert_no_login()
        self.now += 30
        with patch(
            "django_otp.models.timezone.now", return_value=timezone.now() + timedelta(seconds=2)
        ):
            response = self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
        self.assertEqual(response.status_code, 302)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_library_throttling_blocks_immediate_retry_and_survives_new_login(self):
        device = self.device()
        self.password_login()
        self.client.post(reverse("mfa_verify"), {"code": self.wrong_code(device)})
        self.client.post(reverse("mfa_cancel"))
        self.password_login()
        response = self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
        self.assertContains(response, "Invalid authentication code")
        self.assert_no_login()
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)

    def test_pending_challenge_expires_without_logging_in(self):
        device = self.device()
        self.password_login()
        self.now += settings.MFA_PENDING_SECONDS + 1
        response = self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
        self.assertRedirects(response, reverse("login"))
        self.assert_no_login()
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_optional_setup_expiry_does_not_enable_device_or_sign_user_out(self):
        self.password_login()
        device = self.start_enrollment()
        self.now += settings.MFA_PENDING_SECONDS + 1
        self.assertRedirects(
            self.client.post(reverse("mfa_setup"), {"code": self.code(device)}),
            reverse("account_security"),
        )
        self.assertFalse(TOTPDevice.objects.get(pk=device.pk).confirmed)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_password_change_or_deactivation_invalidates_pending_login(self):
        device = self.device()
        for change in ("password", "inactive"):
            self.seeker.set_password(self.password)
            self.seeker.is_active = True
            self.seeker.save()
            self.password_login()
            if change == "password":
                self.seeker.set_password("A-different-password-832!")
            else:
                self.seeker.is_active = False
            self.seeker.save()
            self.assertRedirects(
                self.client.post(reverse("mfa_verify"), {"code": self.code(device)}),
                reverse("login"),
            )
            self.assert_no_login()

    def test_device_id_and_user_id_in_post_cannot_target_another_account(self):
        own = self.device()
        other = self.device(self.employer)
        self.password_login()
        response = self.client.post(
            reverse("mfa_verify"),
            {
                "code": self.code(own),
                "user_id": self.employer.pk,
                "device_id": other.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.seeker.pk))
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], own.persistent_id)

    def test_setup_cannot_enroll_a_different_user(self):
        self.password_login()
        own = self.start_enrollment()
        other = self.device(self.employer, confirmed=False)
        self.client.post(
            reverse("mfa_setup"),
            {"code": self.code(own), "user_id": self.employer.pk, "device_id": other.pk},
        )
        self.assertTrue(TOTPDevice.objects.get(pk=own.pk).confirmed)
        self.assertFalse(TOTPDevice.objects.get(pk=other.pk).confirmed)

    def test_external_next_and_auth_loop_destinations_are_not_followed(self):
        device = self.device()
        for next_url in (
            "https://evil.example/",
            "//evil.example/",
            reverse("mfa_verify"),
            "/admin/login/",
        ):
            self.client.logout()
            self.now += 30
            self.password_login(next_url=next_url)
            response = self.client.post(reverse("mfa_verify"), {"code": self.code(device)})
            self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_anonymous_setup_and_verification_do_not_expose_secrets(self):
        device = self.device(confirmed=False)
        for name in ("mfa_setup", "mfa_verify"):
            response = self.client.get(reverse(name), {"user_id": self.seeker.pk})
            self.assertRedirects(response, reverse("login"))
            self.assertNotIn(device.key.encode(), response.content)
            self.assertNotIn(b32encode(device.bin_key), response.content)

    def test_cancel_is_post_only_and_clears_only_the_pending_flow(self):
        self.device()
        self.password_login()
        self.assertEqual(self.client.get(reverse("mfa_cancel")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("mfa_cancel")), reverse("login"))
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assert_no_login()

    def test_optional_setup_cancellation_leaves_ordinary_access(self):
        self.password_login()
        device = self.start_enrollment()
        self.assertRedirects(self.client.post(reverse("mfa_cancel")), reverse("account_security"))
        self.assertFalse(TOTPDevice.objects.get(pk=device.pk).confirmed)
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)

    def test_csrf_is_required_for_all_mutating_mfa_endpoints(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.seeker)
        for name in ("account_security", "mfa_setup", "mfa_verify", "mfa_cancel"):
            self.assertEqual(
                client.post(
                    reverse(name), {"code": "123456", "password": self.password}
                ).status_code,
                403,
            )

    def test_inactive_user_and_incorrect_password_do_not_start_mfa(self):
        self.device()
        response = self.client.post(
            reverse("login"), {"username": self.seeker.username, "password": "incorrect"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(PENDING_KEY, self.client.session)
        User.objects.filter(pk=self.seeker.pk).update(is_active=False)
        self.assertEqual(self.password_login().status_code, 200)
        self.assertNotIn(PENDING_KEY, self.client.session)

    def test_malformed_and_stale_tokens_are_rejected(self):
        device = self.device()
        self.password_login()
        for code in ("", "12345", "1234567", "abcdef", self.code(device, offset=-300)):
            self.assertEqual(
                self.client.post(reverse("mfa_verify"), {"code": code}).status_code, 200
            )
            self.assert_no_login()

    def test_foreign_or_unconfirmed_session_device_is_not_trusted(self):
        self.device()
        for device in (self.device(self.employer), self.device(confirmed=False)):
            self.client.force_login(self.seeker)
            session = self.client.session
            session[DEVICE_ID_SESSION_KEY] = device.persistent_id
            session.save()
            self.assertEqual(self.client.get(reverse("jobs")).status_code, 302)
            self.assert_no_login()

    def test_no_recovery_or_alternative_factor_apps_installed(self):
        self.assertNotIn("django_otp.plugins.otp_static", settings.INSTALLED_APPS)
        self.assertNotIn("django_otp.plugins.otp_email", settings.INSTALLED_APPS)
