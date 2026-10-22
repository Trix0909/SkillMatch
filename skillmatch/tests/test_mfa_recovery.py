"""Recovery tokens replace only the second factor and are consumed atomically."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.db import OperationalError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.mfa import PENDING_KEY
from skillmatch.mfa_recovery import generate_codes, verify_recovery_code
from skillmatch.models import Account, JobSeekerProfile, RecoveryCode, RecoveryDevice


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RecoveryTests(TestCase):
    password = "Recovery-Tests-891!"

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("recovery_seeker", password=cls.password)
        Account.objects.create(user=cls.user, active_role="seeker")
        JobSeekerProfile.objects.create(user=cls.user)
        cls.other = User.objects.create_user("recovery_other", password=cls.password)
        cls.staff = User.objects.create_superuser("recovery_admin", password=cls.password)

    def setUp(self):
        self.device = TOTPDevice.objects.create(user=self.user, confirmed=True)
        self.codes = generate_codes(self.device)
        self.recovery = RecoveryDevice.objects.get(user=self.user)

    def sign_in(self, user=None, destination=None):
        return self.client.post(
            reverse("login"),
            {
                "username": (user or self.user).username,
                "password": self.password,
                "next": destination or reverse("jobs"),
            },
        )

    def recover(self, code=None):
        return self.client.post(reverse("mfa_recovery"), {"code": code or self.codes[0]})

    def verified_login(self):
        self.sign_in()
        return self.recover()

    def assert_anonymous(self):
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def clear_throttle(self):
        self.recovery.refresh_from_db()
        self.recovery.throttle_reset()

    def test_setup_generates_unique_codes_only_after_totp_confirmation(self):
        self.device.delete()
        self.client.force_login(self.user)
        self.client.post(reverse("account_security"), {"password": self.password})
        self.client.get(reverse("mfa_setup"))
        device = TOTPDevice.objects.get(user=self.user)
        self.assertFalse(RecoveryDevice.objects.filter(user=self.user).exists())
        self.client.post(reverse("mfa_setup"), {"code": "not-a-code"})
        self.assertFalse(RecoveryCode.objects.exists())
        token = f"{TOTP(device.bin_key).token():06d}"
        response = self.client.post(reverse("mfa_setup"), {"code": token})
        self.assertContains(response, "Save your recovery codes")
        self.assertContains(response, "Copy all recovery codes")
        self.assertContains(response, "Download recovery codes")
        codes = response.context["codes"]
        self.assertEqual(len(codes), 10)
        self.assertEqual(len(set(codes)), 10)
        self.assertEqual(RecoveryCode.objects.count(), 10)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertTrue(TOTPDevice.objects.get(pk=device.pk).confirmed)
        for code in codes:
            self.assertNotIn(code, str(dict(self.client.session)))
        # A repeated POST/refresh must not generate or reveal another set.
        original = list(RecoveryCode.objects.values_list("digest", flat=True))
        response = self.client.post(reverse("mfa_setup"), {"code": token}, follow=True)
        self.assertEqual(original, list(RecoveryCode.objects.values_list("digest", flat=True)))
        for code in codes:
            self.assertNotContains(response, code)

    def test_storage_has_only_one_way_digests_not_plaintext(self):
        digests = list(self.recovery.codes.values_list("digest", flat=True))
        self.assertEqual(len(digests), 10)
        for code in self.codes:
            self.assertNotIn(code, digests)
            self.assertNotIn(code.replace("-", ""), digests)
            self.assertIn(RecoveryDevice.token_digest(code), digests)
        self.assertTrue(all(len(value) == 64 for value in digests))

    def test_valid_code_rotates_session_consumes_once_and_preserves_destination(self):
        destination = reverse("jobs") + "?q=Python&page=1"
        self.assertRedirects(self.sign_in(destination=destination), reverse("mfa_verify"))
        self.assertContains(self.client.get(reverse("mfa_verify")), "Use a recovery code")
        self.assert_anonymous()
        self.client.get(reverse("mfa_recovery"))
        old_session = self.client.session.session_key
        response = self.recover()
        self.assertRedirects(response, destination, fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], self.recovery.persistent_id)
        self.assertNotEqual(old_session, self.client.session.session_key)
        self.assertNotIn(PENDING_KEY, self.client.session)
        self.assertEqual(self.recovery.codes.count(), 9)
        self.assertFalse(
            self.recovery.codes.filter(digest=RecoveryDevice.token_digest(self.codes[0])).exists()
        )
        page = self.client.get(reverse("jobs"))
        self.assertContains(page, "You signed in using a recovery code")
        self.assertContains(page, reverse("account_security"))
        self.assertTrue(TOTPDevice.objects.get(pk=self.device.pk).confirmed)
        self.client.post(reverse("logout"))
        self.assert_anonymous()
        self.assertRedirects(self.sign_in(), reverse("mfa_verify"))
        self.assertContains(self.recover(), "Invalid or already used recovery code.")
        self.assert_anonymous()

    def test_no_first_factor_cannot_use_code_or_get_code_list(self):
        for url in ("mfa_recovery", "mfa_recovery_generate", "mfa_setup"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 302)
            self.assertEqual(
                self.client.post(reverse(url), {"code": self.codes[0]}).status_code, 302
            )
        self.assert_anonymous()
        self.assertEqual(self.recovery.codes.count(), 10)
        response = self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.codes[0]}
        )
        self.assertEqual(response.status_code, 200)
        self.assert_anonymous()

    def test_invalid_malformed_foreign_codes_have_same_error_and_do_not_authenticate(self):
        other_device = TOTPDevice.objects.create(user=self.other, confirmed=True)
        foreign = generate_codes(other_device)[0]
        self.sign_in()
        for code in ("", "bad", "x" * 200, "0" * 32, foreign):
            self.clear_throttle()
            response = self.client.post(
                reverse("mfa_recovery"), {"code": code, "user_id": self.other.pk}
            )
            self.assertContains(response, "Invalid or already used recovery code.")
            self.assert_anonymous()
            self.assertEqual(self.recovery.codes.count(), 10)
        self.assertEqual(RecoveryDevice.objects.get(user=self.other).codes.count(), 10)

    def test_recovery_cannot_bypass_admin_enrollment(self):
        self.sign_in(self.staff, "/admin/")
        self.assertRedirects(self.recover(), reverse("mfa_setup"))
        self.assert_anonymous()
        self.assertFalse(RecoveryDevice.objects.filter(user=self.staff).exists())
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_admin_recovery_uses_same_verified_session_and_direct_admin_gate(self):
        authenticator = TOTPDevice.objects.create(user=self.staff, confirmed=True)
        code = generate_codes(authenticator)[0]
        self.sign_in(self.staff, "/admin/")
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.assert_anonymous()
        self.assertRedirects(self.recover(code), "/admin/")
        self.assertEqual(self.client.get("/admin/auth/user/").status_code, 200)
        self.client.post(reverse("logout"))
        self.sign_in(self.staff, "/admin/")
        self.assertContains(self.recover(code), "Invalid or already used recovery code.")
        self.assert_anonymous()

    def test_admin_gate_accepts_recovery_and_rejects_password_only_without_enforcement_middleware(
        self,
    ):
        authenticator = TOTPDevice.objects.create(user=self.staff, confirmed=True)
        generate_codes(authenticator)
        device = RecoveryDevice.objects.get(user=self.staff)
        middleware = [
            item
            for item in settings.MIDDLEWARE
            if item != "skillmatch.mfa.MFAEnforcementMiddleware"
        ]
        with override_settings(MIDDLEWARE=middleware):
            client = Client()
            client.force_login(self.staff)
            self.assertEqual(client.get("/admin/").status_code, 302)
            session = client.session
            session[DEVICE_ID_SESSION_KEY] = device.persistent_id
            session.save()
            self.assertEqual(client.get("/admin/").status_code, 200)

    def test_setup_generation_failure_keeps_authenticator_unconfirmed(self):
        self.device.delete()
        self.client.force_login(self.user)
        self.client.post(reverse("account_security"), {"password": self.password})
        self.client.get(reverse("mfa_setup"))
        device = TOTPDevice.objects.get(user=self.user)
        token = f"{TOTP(device.bin_key).token():06d}"
        with patch("skillmatch.mfa_recovery.random_hex", side_effect=OperationalError("locked")):
            response = self.client.post(reverse("mfa_setup"), {"code": token})
        self.assertContains(response, "Another request is in progress")
        self.assertFalse(TOTPDevice.objects.get(pk=device.pk).confirmed)
        self.assertFalse(RecoveryCode.objects.exists())

    def test_normal_totp_login_remains_unchanged_and_does_not_consume_recovery(self):
        self.sign_in()
        token = f"{TOTP(self.device.bin_key).token():06d}"
        self.assertRedirects(
            self.client.post(reverse("mfa_verify"), {"code": token}), reverse("jobs")
        )
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], self.device.persistent_id)
        self.assertEqual(self.recovery.codes.count(), 10)

    def test_counter_and_settings_never_reveal_existing_codes(self):
        self.verified_login()
        page = self.client.get(reverse("account_security"))
        self.assertContains(page, "Available recovery codes: 9 of 10")
        self.assertContains(page, reverse("mfa_recovery_generate"))
        for code in self.codes:
            self.assertNotContains(page, code)

    def test_regeneration_requires_password_and_replaces_old_set(self):
        self.verified_login()
        original = set(self.recovery.codes.values_list("digest", flat=True))
        self.assertEqual(self.client.get(reverse("mfa_recovery_generate")).status_code, 200)
        for password in ("", "wrong"):
            self.clear_throttle()
            response = self.client.post(reverse("mfa_recovery_generate"), {"password": password})
            self.assertContains(response, "Unable to verify your password")
            self.assertEqual(set(self.recovery.codes.values_list("digest", flat=True)), original)
        self.clear_throttle()
        response = self.client.post(reverse("mfa_recovery_generate"), {"password": self.password})
        self.assertContains(response, "Save your recovery codes")
        replacement = response.context["codes"]
        self.assertEqual(len(replacement), 10)
        self.assertFalse(set(replacement).intersection(self.codes))
        for code in replacement:
            self.assertNotIn(code, str(dict(self.client.session)))
        self.assertFalse(
            set(self.recovery.codes.values_list("digest", flat=True)).intersection(original)
        )
        self.client.post(reverse("logout"))
        self.sign_in()
        self.assertContains(self.recover(self.codes[1]), "Invalid or already used recovery code.")
        self.assert_anonymous()
        self.clear_throttle()
        self.assertRedirects(self.recover(replacement[0]), reverse("jobs"))
        self.assertEqual(self.recovery.codes.count(), 9)

    def test_exhaustion_does_not_log_out_current_session_and_password_can_regenerate(self):
        self.recovery.codes.exclude(digest=RecoveryDevice.token_digest(self.codes[0])).delete()
        self.verified_login()
        self.assertEqual(self.recovery.codes.count(), 0)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)
        response = self.client.post(reverse("mfa_recovery_generate"), {"password": self.password})
        self.assertEqual(len(response.context["codes"]), 10)

    def test_existing_totp_users_can_create_first_set_after_reverification(self):
        self.recovery.delete()
        self.sign_in()
        token = f"{TOTP(self.device.bin_key).token():06d}"
        self.client.post(reverse("mfa_verify"), {"code": token})
        self.assertContains(
            self.client.get(reverse("account_security")), "Available recovery codes: 0 of 10"
        )
        response = self.client.post(reverse("mfa_recovery_generate"), {"password": self.password})
        self.assertContains(response, "Save your recovery codes")
        self.assertEqual(RecoveryCode.objects.count(), 10)

    def test_missing_or_unconfirmed_authenticator_cannot_use_recovery_session(self):
        self.verified_login()
        TOTPDevice.objects.filter(pk=self.device.pk).update(confirmed=False)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 302)
        self.assert_anonymous()
        self.assertIsNone(verify_recovery_code(self.user, self.codes[1]))

    def test_deleting_authenticator_invalidates_codes_and_a_new_setup_is_fresh(self):
        old = set(self.recovery.codes.values_list("digest", flat=True))
        self.device.delete()
        self.assertFalse(RecoveryCode.objects.exists())
        self.assertFalse(RecoveryDevice.objects.exists())
        self.assertIsNone(verify_recovery_code(self.user, self.codes[0]))
        new = TOTPDevice.objects.create(user=self.user, confirmed=True)
        generate_codes(new)
        self.assertFalse(old.intersection(RecoveryCode.objects.values_list("digest", flat=True)))

    def test_normal_users_without_mfa_are_not_offered_or_given_recovery_codes(self):
        self.device.delete()
        self.client.force_login(self.user)
        self.assertNotContains(
            self.client.get(reverse("account_security")), "Generate new recovery codes"
        )
        self.assertRedirects(
            self.client.get(reverse("mfa_recovery_generate")), reverse("account_security")
        )
        self.assertFalse(RecoveryDevice.objects.exists())
        unconfirmed = TOTPDevice.objects.create(user=self.user, confirmed=False)
        with self.assertRaises(ValueError):
            generate_codes(unconfirmed)
        self.assertFalse(RecoveryCode.objects.exists())

    def test_throttle_survives_new_password_challenge_and_blocks_correct_code_briefly(self):
        self.sign_in()
        self.recover("wrong")
        self.client.post(reverse("mfa_cancel"))
        self.sign_in()
        self.assertContains(self.recover(), "Invalid or already used recovery code.")
        self.assert_anonymous()
        with patch(
            "django_otp.models.timezone.now", return_value=timezone.now() + timedelta(seconds=2)
        ):
            self.assertRedirects(self.recover(), reverse("jobs"))

    def test_regeneration_password_failures_are_throttled(self):
        self.verified_login()
        self.client.post(reverse("mfa_recovery_generate"), {"password": "wrong"})
        response = self.client.post(reverse("mfa_recovery_generate"), {"password": self.password})
        self.assertContains(response, "Unable to verify your password")
        self.assertEqual(self.recovery.codes.count(), 9)
        with patch(
            "django_otp.models.timezone.now", return_value=timezone.now() + timedelta(seconds=2)
        ):
            response = self.client.post(
                reverse("mfa_recovery_generate"), {"password": self.password}
            )
        self.assertContains(response, "Save your recovery codes")

    def test_expired_password_challenge_cannot_consume_a_recovery_code(self):
        self.sign_in()
        with patch(
            "skillmatch.mfa.time.time",
            return_value=__import__("time").time() + settings.MFA_PENDING_SECONDS + 1,
        ):
            self.assertRedirects(self.recover(), reverse("login"))
        self.assert_anonymous()
        self.assertEqual(self.recovery.codes.count(), 10)

    def test_password_changes_or_deactivation_invalidate_recovery_challenge(self):
        for inactive in (False, True):
            self.user.is_active = True
            self.user.set_password(self.password)
            self.user.save()
            self.sign_in()
            if inactive:
                User.objects.filter(pk=self.user.pk).update(is_active=False)
            else:
                self.user.set_password("Another-test-password-920!")
                self.user.save()
            self.assertRedirects(self.recover(), reverse("login"))
            self.assert_anonymous()
            self.assertEqual(self.recovery.codes.count(), 10)

    def test_safe_next_does_not_loop_to_recovery_or_external_site(self):
        for destination in (
            "https://evil.example/",
            reverse("mfa_recovery"),
            reverse("mfa_recovery_generate"),
        ):
            self.client.logout()
            self.sign_in(destination=destination)
            self.assertRedirects(
                self.recover(self.codes.pop()), reverse("home"), fetch_redirect_response=False
            )

    def test_csrf_and_methods_protect_recovery_actions(self):
        protected = Client(enforce_csrf_checks=True)
        for name in ("mfa_recovery", "mfa_recovery_generate"):
            self.assertEqual(
                protected.post(
                    reverse(name), {"code": self.codes[0], "password": self.password}
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.delete(reverse(name)).status_code,
                405 if name == "mfa_recovery" else 302,
            )
        self.assertEqual(self.recovery.codes.count(), 10)

    def test_foreign_device_in_verified_session_cannot_bypass_enforcement(self):
        foreign = TOTPDevice.objects.create(user=self.other, confirmed=True)
        generate_codes(foreign)
        self.client.force_login(self.user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = RecoveryDevice.objects.get(user=self.other).persistent_id
        session.save()
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 302)
        self.assert_anonymous()

    def test_device_and_hash_editing_are_not_exposed_through_admin(self):
        self.assertFalse(admin.site.is_registered(RecoveryDevice))
        self.assertFalse(admin.site.is_registered(RecoveryCode))

    def test_verification_write_conflict_fails_closed_without_authentication(self):
        self.sign_in()
        with patch(
            "skillmatch.mfa_views.verify_recovery_code", side_effect=OperationalError("locked")
        ):
            self.assertContains(self.recover(), "Invalid or already used recovery code.")
        self.assert_anonymous()
        self.assertEqual(self.recovery.codes.count(), 10)

    def test_regeneration_failure_rolls_back_old_set(self):
        self.verified_login()
        original = set(self.recovery.codes.values_list("digest", flat=True))
        with patch("skillmatch.mfa_recovery.random_hex", side_effect=OperationalError("locked")):
            self.assertContains(
                self.client.post(reverse("mfa_recovery_generate"), {"password": self.password}),
                "Unable to verify your password",
            )
        self.assertEqual(original, set(self.recovery.codes.values_list("digest", flat=True)))

    def test_case_and_separators_do_not_create_multiple_uses_of_same_code(self):
        self.sign_in()
        self.assertRedirects(self.recover(self.codes[0].replace("-", "").upper()), reverse("jobs"))
        self.client.logout()
        self.sign_in()
        self.assertContains(self.recover(self.codes[0]), "Invalid or already used recovery code.")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class RecoveryConcurrencyTests(TransactionTestCase):
    def test_simultaneous_submissions_cannot_consume_the_same_code_twice(self):
        user = User.objects.create_user("concurrent_recovery")
        authenticator = TOTPDevice.objects.create(user=user, confirmed=True)
        code = generate_codes(authenticator)[0]
        barrier = Barrier(2)

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return verify_recovery_code(User.objects.get(pk=user.pk), code) is not None
            except OperationalError:
                # SQLite rejects conflicting writes instead of locking rows.
                return False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: attempt(), range(2)))
        self.assertLessEqual(sum(results), 1)
        device = RecoveryDevice.objects.get(user=user)
        if any(results):
            self.assertEqual(device.codes.count(), 9)
            with transaction.atomic():
                self.assertFalse(device.verify_token(code))
        else:
            self.assertIsNotNone(verify_recovery_code(user, code))
            self.assertIsNone(verify_recovery_code(user, code))
