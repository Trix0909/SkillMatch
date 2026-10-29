"""Real OAuth state/callback/session flows with provider HTTP fully mocked."""

import base64
import hashlib
import time
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.mfa import PENDING_KEY
from skillmatch.mfa_recovery import generate_codes
from skillmatch.mfa_views import REMINDER_KEY
from skillmatch.models import Account, EmployerProfile, JobSeekerProfile
from skillmatch.social import PROVIDERS, RECENT_KEY, SOCIAL_BACKEND, can_auto_link
from skillmatch.social_views import ADAPTERS

PROVIDER_SETTINGS = {
    provider: {
        "APPS": [{"client_id": "test-client", "secret": "test-secret", "key": ""}],
        "OAUTH_PKCE_ENABLED": True,
        "SCOPE": settings.SOCIALACCOUNT_PROVIDERS[provider]["SCOPE"],
    }
    for provider in PROVIDERS
}


@override_settings(
    SOCIALACCOUNT_PROVIDERS=PROVIDER_SETTINGS,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class SocialTests(TestCase):
    password = "Provider-test-password-591!"

    def setUp(self):
        cache.clear()
        # Any accidental provider HTTP request makes the test fail immediately.
        network = patch(
            "requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")
        )
        network.start()
        self.addCleanup(network.stop)

    def user(self, username="amina", password=True, **kwargs):
        user = User.objects.create_user(
            username, password=self.password if password else None, **kwargs
        )
        Account.objects.create(user=user, active_role="seeker")
        JobSeekerProfile.objects.create(user=user)
        return user

    def link(self, user, provider="google", uid="123"):
        return SocialAccount.objects.create(user=user, provider=provider, uid=uid)

    def start(self, provider="google", purpose="login", **data):
        response = self.client.post(reverse(f"{provider}_login"), {"purpose": purpose, **data})
        self.assertEqual(response.status_code, 302)
        self.assertIn("state=", response.url)
        return parse_qs(urlsplit(response.url).query)["state"][0]

    def callback(
        self,
        provider="google",
        state=None,
        uid="123",
        email="new@example.test",
        verified=True,
        **start,
    ):
        if state is None:
            state = self.start(provider, **start)

        def identity(adapter, request, app, token, **kwargs):
            service = get_adapter(request).get_provider(request, provider)
            if provider == "github":
                payload = {
                    "id": uid,
                    "login": "amina",
                    "name": "Amina Kamau",
                    "email": None,
                    "emails": [],
                }
                if email:
                    payload["emails"] = [{"email": email, "verified": verified, "primary": True}]
            else:
                payload = {
                    "sub": uid,
                    "email": email,
                    "email_verified": verified,
                    "given_name": "Amina",
                    "family_name": "Kamau",
                    "picture": "https://avatar.invalid/large.jpg",
                }
            sociallogin = service.sociallogin_from_response(request, payload)
            return sociallogin

        with (
            patch(
                "allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token",
                return_value={"access_token": "test-only-token"},
            ),
            patch.object(ADAPTERS[provider], "complete_login", autospec=True, side_effect=identity),
        ):
            return self.client.get(
                reverse(f"{provider}_callback"), {"code": "mock-code", "state": state}
            )

    def reauth(self):
        response = self.client.post(reverse("social_reauthenticate"), {"password": self.password})
        self.assertRedirects(response, reverse("social_connections"))

    def totp(self, device):
        token = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
        return f"{token.token():06d}"

    def assert_anonymous(self):
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_configured_provider_buttons(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(set(PROVIDERS), {"google", "github"})
        self.assertEqual(set(ADAPTERS), {"google", "github"})
        self.assertNotContains(response, "Microsoft")
        self.assertNotContains(response, "Not configured")
        for provider, name in PROVIDERS.items():
            self.assertContains(response, f"Continue with {name}")
            self.assertContains(response, f'action="{reverse(f"{provider}_login")}"')
            self.start(provider)

    @override_settings(SOCIALACCOUNT_PROVIDERS={})
    def test_missing_configuration_is_safe(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "or continue with", count=1)
        self.assertNotContains(response, "Microsoft")
        self.assertNotContains(response, "Not configured")
        self.assertContains(response, 'class="sm-button sm-social-button" disabled', count=2)
        for provider, name in PROVIDERS.items():
            self.assertContains(response, f"Continue with {name}")
            self.assertNotContains(response, f'action="{reverse(f"{provider}_login")}"')
            self.assertRedirects(self.client.post(reverse(f"{provider}_login")), reverse("login"))
            self.assertRedirects(self.client.get(reverse(f"{provider}_callback")), reverse("login"))
        self.assertNotIn("socialaccount_states", self.client.session)
        self.assert_anonymous()

    @override_settings(SOCIALACCOUNT_PROVIDERS={"github": PROVIDER_SETTINGS["github"]})
    def test_one_configured_provider_still_works(self):
        response = self.client.get(reverse("login"))
        for name in PROVIDERS.values():
            self.assertContains(response, f"Continue with {name}")
        self.assertNotContains(response, "Not configured")
        self.assertContains(response, 'class="sm-button sm-social-button" disabled', count=1)
        self.assertContains(response, f'action="{reverse("github_login")}"')
        self.assertNotContains(response, f'action="{reverse("google_login")}"')
        self.assertRedirects(self.callback(provider="github"), reverse("socialaccount_signup"))

    def test_partial_credentials_keep_provider_buttons_disabled(self):
        for app in ({"client_id": "test-client"}, {"secret": "test-secret"}):
            with (
                self.subTest(app=app),
                override_settings(
                    SOCIALACCOUNT_PROVIDERS={key: {"APPS": [app]} for key in PROVIDERS}
                ),
            ):
                response = self.client.get(reverse("login"))
                self.assertNotContains(response, "Not configured")
                self.assertContains(
                    response, 'class="sm-button sm-social-button" disabled', count=2
                )
                for provider in PROVIDERS:
                    self.assertNotContains(response, f'action="{reverse(f"{provider}_login")}"')
                    self.assertRedirects(
                        self.client.post(reverse(f"{provider}_login")), reverse("login")
                    )

    def test_database_apps_do_not_override_environment(self):
        SocialApp.objects.create(provider="google", client_id="db-client", secret="db-secret")
        self.assertEqual(len(get_adapter().list_apps(None, "google")), 1)
        self.assertEqual(get_adapter().get_app(None, "google").client_id, "test-client")

    def test_admin_cannot_edit_identity_tables_to_bypass_confirmation(self):
        for model in (SocialAccount, SocialApp, SocialToken, EmailAddress):
            self.assertFalse(admin.site.is_registered(model))

    def test_credentials_removed_during_onboarding_fail_safely(self):
        self.callback()
        with override_settings(SOCIALACCOUNT_PROVIDERS={}):
            self.assertRedirects(self.client.get(reverse("socialaccount_signup")), reverse("login"))
        self.assertFalse(User.objects.exists())

    def test_both_providers_use_existing_mfa_handoff(self):
        user = self.user()
        TOTPDevice.objects.create(user=user, confirmed=True)
        for provider in PROVIDERS:
            self.link(user, provider)
            self.client.logout()
            self.assertRedirects(self.callback(provider), reverse("mfa_verify"))
            self.assert_anonymous()

    def test_callback_connection_conflict_is_handled_without_partial_account(self):
        from django.db import IntegrityError

        user = self.user()
        self.client.force_login(user)
        self.reauth()
        with patch(
            "allauth.socialaccount.models.SocialLogin.connect", side_effect=IntegrityError()
        ):
            self.assertRedirects(self.callback(purpose="connect"), reverse("social_connections"))
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(SocialAccount.objects.exists())

    def test_provider_start_requires_post_and_csrf(self):
        for provider in PROVIDERS:
            self.assertEqual(self.client.get(reverse(f"{provider}_login")).status_code, 405)
            self.assertEqual(
                Client(enforce_csrf_checks=True).post(reverse(f"{provider}_login")).status_code, 403
            )

    def test_new_user_remains_anonymous_until_onboarding(self):
        self.assertRedirects(self.callback(), reverse("socialaccount_signup"))
        self.assertFalse(User.objects.exists())
        self.assertFalse(Account.objects.exists())
        self.assertFalse(JobSeekerProfile.objects.exists())
        self.assert_anonymous()
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 302)
        pending = self.client.session["socialaccount_sociallogin"]
        self.assertNotIn("token", pending)
        self.assertTrue(pending["user"]["password"].startswith("!"))

    def test_onboarding_seeker_uses_shared_profile_creation(self):
        self.callback(next=reverse("jobs"))
        response = self.client.post(
            reverse("socialaccount_signup"), {"role": "seeker", "is_staff": "true"}
        )
        self.assertRedirects(response, reverse("mfa_reminder"))
        user = User.objects.get()
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff)
        self.assertEqual(user.account.active_role, "seeker")
        self.assertTrue(JobSeekerProfile.objects.filter(user=user).exists())
        self.assertRedirects(
            self.client.post(reverse("mfa_reminder"), {"action": "later"}), reverse("jobs")
        )
        self.assertEqual(SocialAccount.objects.get().extra_data, {"email": "new@example.test"})
        self.assertFalse(SocialToken.objects.exists())

    def test_employer_onboarding_requires_company_then_can_switch(self):
        self.callback()
        self.assertContains(
            self.client.post(reverse("socialaccount_signup"), {"role": "employer"}),
            "Enter your company name.",
        )
        self.assertFalse(User.objects.exists())
        self.client.post(
            reverse("socialaccount_signup"), {"role": "employer", "company_name": "Wanjiku Studio"}
        )
        user = User.objects.get()
        self.assertEqual(user.account.active_role, "employer")
        self.assertEqual(user.employer_profile.company_name, "Wanjiku Studio")
        self.client.post(reverse("mfa_reminder"), {"action": "later"})
        self.assertRedirects(self.client.get(reverse("home")), reverse("employer_jobs"))
        self.assertRedirects(
            self.client.post(reverse("switch_role"), {"active_role": "seeker"}),
            reverse("profile_edit"),
        )
        self.assertTrue(EmployerProfile.objects.filter(user=user).exists())
        self.assertTrue(JobSeekerProfile.objects.filter(user=user).exists())

    def test_invalid_onboarding_role_cannot_escalate(self):
        self.callback()
        response = self.client.post(reverse("socialaccount_signup"), {"role": "admin"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_same_email_and_duplicate_local_emails_never_link(self):
        one = self.user(email="New@example.test")
        self.user("other", email="new@example.test")
        response = self.callback()
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertContains(
            self.client.get(reverse("login")), "An account with this email already exists"
        )
        self.assertEqual(User.objects.count(), 2)
        self.assertFalse(SocialAccount.objects.exists())
        self.assertFalse(can_auto_link(one, one.email))
        self.assert_anonymous()

    def test_email_conflict_created_during_onboarding_is_rechecked(self):
        self.callback()
        self.user(email="new@example.test")
        self.assertRedirects(
            self.client.post(reverse("socialaccount_signup"), {"role": "seeker"}), reverse("login")
        )
        self.assertEqual(User.objects.count(), 1)
        self.assertFalse(SocialAccount.objects.exists())

    def test_unverified_and_missing_email_refused(self):
        for provider in PROVIDERS:
            for email, verified in [("new@example.test", False), (None, False)]:
                with self.subTest(provider=provider, email=email):
                    self.assertRedirects(
                        self.callback(provider, email=email, verified=verified), reverse("login")
                    )
                    self.assertFalse(User.objects.exists())

    def test_github_verified_private_email_is_accepted(self):
        self.assertRedirects(self.callback("github"), reverse("socialaccount_signup"))

    def test_github_username_collision_does_not_merge_or_block_onboarding(self):
        self.assertRedirects(self.callback("github"), reverse("socialaccount_signup"))
        owner = self.user("Amina", email="different@example.test")
        self.assertRedirects(
            self.client.post(reverse("socialaccount_signup"), {"role": "seeker"}),
            reverse("mfa_reminder"),
        )
        newcomer = SocialAccount.objects.get(provider="github", uid="123").user
        self.assertNotEqual(newcomer.pk, owner.pk)
        self.assertNotEqual(newcomer.username.casefold(), owner.username.casefold())
        self.assertEqual(newcomer.email, "new@example.test")
        self.assertFalse(newcomer.has_usable_password())
        owner.refresh_from_db()
        self.assertEqual(owner.username, "Amina")
        self.assertEqual(owner.email, "different@example.test")
        self.assertTrue(owner.check_password(self.password))

    def test_existing_identity_uses_uid_after_email_changes(self):
        user = self.user(email="original@example.test")
        self.link(user)
        self.user("collision", email="new@example.test")
        self.assertRedirects(self.callback(), reverse("mfa_reminder"))
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        self.assertEqual(User.objects.count(), 2)
        user.refresh_from_db()
        self.assertEqual(user.email, "original@example.test")

    def test_existing_identity_does_not_need_email_again(self):
        user = self.user()
        self.link(user)
        self.assertRedirects(self.callback(email=None), reverse("mfa_reminder"))

    def test_normal_login_reuses_reminder_once_and_preserves_next(self):
        user = self.user()
        self.link(user)
        old_key = self.client.session.session_key
        self.assertRedirects(self.callback(next=reverse("jobs")), reverse("mfa_reminder"))
        self.assertNotEqual(old_key, self.client.session.session_key)
        self.assertRedirects(
            self.client.post(reverse("mfa_reminder"), {"action": "later"}), reverse("jobs")
        )
        self.assertNotIn(REMINDER_KEY, self.client.session)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("mfa_reminder")), reverse("home"), fetch_redirect_response=False
        )

    def test_reminder_enable_uses_existing_setup(self):
        user = self.user(password=False)
        self.link(user)
        self.callback()
        self.assertRedirects(
            self.client.post(reverse("mfa_reminder"), {"action": "enable"}), reverse("mfa_setup")
        )

    def test_totp_is_required_and_invalid_code_does_not_login(self):
        user = self.user()
        self.link(user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        self.assertRedirects(self.callback(next=reverse("jobs")), reverse("mfa_verify"))
        self.assert_anonymous()
        self.assertEqual(self.client.session[PENDING_KEY]["backend"], SOCIAL_BACKEND)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 302)
        self.assertContains(self.client.post(reverse("mfa_verify"), {"code": "wrong"}), "6-digit")
        self.assert_anonymous()
        self.assertRedirects(
            self.client.post(reverse("mfa_verify"), {"code": self.totp(device)}), reverse("jobs")
        )
        self.assertIn(DEVICE_ID_SESSION_KEY, self.client.session)
        self.assertNotIn(REMINDER_KEY, self.client.session)

    def test_recovery_code_completes_social_login(self):
        user = self.user()
        self.link(user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        code = generate_codes(device)[0]
        self.callback()
        self.assertRedirects(
            self.client.post(reverse("mfa_recovery"), {"code": code}),
            reverse("home"),
            fetch_redirect_response=False,
        )
        self.assertIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_wrong_numeric_totp_is_rejected_and_throttled(self):
        user = self.user()
        self.link(user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        self.callback()
        clock = time.time()
        valid = set()
        for offset in (-30, 0, 30):
            with patch("time.time", return_value=clock + offset):
                valid.add(self.totp(device))
        wrong = next(f"{n:06d}" for n in range(10) if f"{n:06d}" not in valid)
        self.assertContains(
            self.client.post(reverse("mfa_verify"), {"code": wrong}), "Invalid authentication code"
        )
        self.assert_anonymous()
        device.refresh_from_db()
        self.assertEqual(device.throttling_failure_count, 1)

    def test_social_reauth_and_first_password_keep_verified_mfa_session(self):
        user = self.user(password=False)
        self.link(user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        self.callback()
        self.client.post(reverse("mfa_verify"), {"code": self.totp(device)})
        self.assertRedirects(self.callback(purpose="reauthenticate"), reverse("social_connections"))
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], device.persistent_id)
        self.assertRedirects(
            self.client.post(
                reverse("first_password"),
                {"new_password1": self.password, "new_password2": self.password},
            ),
            reverse("social_connections"),
        )
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], device.persistent_id)
        self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)

    def test_admin_without_device_is_forced_to_setup(self):
        user = self.user(is_staff=True, is_superuser=True)
        self.link(user)
        self.assertRedirects(self.callback(next=reverse("admin:index")), reverse("mfa_setup"))
        self.assert_anonymous()
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        self.assertNotContains(self.client.get(reverse("mfa_setup")), "Not now")
        device = TOTPDevice.objects.get(user=user)
        self.assertEqual(
            self.client.post(reverse("mfa_setup"), {"code": self.totp(device)}).status_code, 200
        )
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_admin_with_device_cannot_bypass_totp(self):
        user = self.user(is_staff=True, is_superuser=True)
        self.link(user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        self.assertRedirects(self.callback(next=reverse("admin:index")), reverse("mfa_verify"))
        self.assert_anonymous()
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
        self.assertRedirects(
            self.client.post(reverse("mfa_verify"), {"code": self.totp(device)}),
            reverse("admin:index"),
        )

    def test_pending_state_expiry_hash_and_backend(self):
        user = self.user()
        self.link(user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        for field, value in [
            ("expires", 0),
            ("auth_hash", "tampered"),
            ("backend", "unknown.Backend"),
        ]:
            with self.subTest(field=field):
                self.client.logout()
                self.callback()
                session = self.client.session
                session[PENDING_KEY][field] = value
                session.save()
                self.assertRedirects(
                    self.client.post(reverse("mfa_verify"), {"code": self.totp(device)}),
                    reverse("login"),
                )
                self.assert_anonymous()

    def test_logout_prevents_pending_and_oauth_replay(self):
        user = self.user()
        self.link(user)
        TOTPDevice.objects.create(user=user, confirmed=True)
        state = self.start()
        self.callback(state=state)
        self.client.post(reverse("logout"))
        self.assertRedirects(self.callback(state=state), reverse("login"))
        self.assertRedirects(self.client.get(reverse("mfa_verify")), reverse("login"))
        self.assert_anonymous()

    def test_inactive_user_is_refused(self):
        user = self.user(is_active=False)
        self.link(user)
        self.assertRedirects(self.callback(), reverse("login"))
        self.assert_anonymous()

    def test_unsafe_next_is_neutralized(self):
        user = self.user()
        self.link(user)
        for destination in ["https://evil.example/", "//evil.example/", reverse("login")]:
            self.client.logout()
            self.callback(next=destination)
            self.assertEqual(self.client.session[REMINDER_KEY]["next"], reverse("home"))

    def test_cancelled_and_invalid_state_do_not_create_accounts(self):
        state = self.start()
        self.assertRedirects(
            self.client.get(reverse("google_callback"), {"state": state, "error": "access_denied"}),
            reverse("login"),
        )
        self.assertRedirects(self.callback(state="wrong-state"), reverse("login"))
        self.assertFalse(User.objects.exists())

    def test_old_session_cannot_connect_disconnect_or_set_password(self):
        user = self.user(password=False)
        account = self.link(user)
        self.client.force_login(user)
        for name, args, data in [
            ("github_login", [], {"purpose": "connect"}),
            ("social_disconnect", [account.pk], {}),
            (
                "first_password",
                [],
                {"new_password1": self.password, "new_password2": self.password},
            ),
        ]:
            self.assertRedirects(
                self.client.post(reverse(name, args=args), data), reverse("social_reauthenticate")
            )
        self.assertTrue(SocialAccount.objects.filter(pk=account.pk).exists())
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_current_password_reauthentication_and_expiry(self):
        user = self.user()
        self.client.force_login(user)
        self.assertContains(
            self.client.post(reverse("social_reauthenticate"), {"password": "wrong"}), "incorrect"
        )
        self.assertNotIn(RECENT_KEY, self.client.session)
        self.reauth()
        state = self.start("github", purpose="connect")
        session = self.client.session
        session[RECENT_KEY]["at"] = 0
        session.save()
        self.assertRedirects(self.callback("github", state=state), reverse("social_reauthenticate"))
        self.assertFalse(SocialAccount.objects.exists())

    def test_connect_requires_fresh_auth_and_preserves_current_user(self):
        user = self.user()
        self.client.force_login(user)
        self.reauth()
        self.assertRedirects(
            self.callback("github", purpose="connect"), reverse("social_connections")
        )
        self.assertEqual(SocialAccount.objects.get().user, user)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        self.assertContains(
            self.client.get(reverse("social_connections")), "Connected as new@example.test"
        )

    def test_connected_elsewhere_is_never_reassigned(self):
        owner = self.user("owner")
        account = self.link(owner)
        user = self.user()
        self.client.force_login(user)
        self.reauth()
        self.assertRedirects(self.callback(purpose="connect"), reverse("social_connections"))
        account.refresh_from_db()
        self.assertEqual(account.user, owner)
        self.assertEqual(User.objects.count(), 2)

    def test_unverified_email_cannot_connect(self):
        user = self.user()
        self.client.force_login(user)
        self.reauth()
        self.assertRedirects(
            self.callback(purpose="connect", verified=False), reverse("social_connections")
        )
        self.assertFalse(SocialAccount.objects.exists())

    def test_social_only_reauth_requires_already_connected_identity(self):
        user = self.user(password=False)
        self.link(user)
        self.client.force_login(user)
        self.assertRedirects(
            self.callback(purpose="reauthenticate", uid="attacker"), reverse("social_connections")
        )
        self.assertNotIn(RECENT_KEY, self.client.session)
        self.assertRedirects(self.callback(purpose="reauthenticate"), reverse("social_connections"))
        self.assertIn(RECENT_KEY, self.client.session)

    def test_reauth_callback_bound_to_same_session_user(self):
        user = self.user(password=False)
        self.link(user)
        self.client.force_login(user)
        state = self.start(purpose="reauthenticate")
        self.client.logout()
        self.assertRedirects(self.callback(state=state), reverse("login"))
        self.assertNotIn(RECENT_KEY, self.client.session)

    def test_mfa_required_session_cannot_manage_accounts_before_totp(self):
        user = self.user()
        TOTPDevice.objects.create(user=user, confirmed=True)
        self.client.force_login(user)
        self.assertEqual(
            self.client.post(
                reverse("social_reauthenticate"), {"password": self.password}
            ).status_code,
            302,
        )
        self.assert_anonymous()

    def test_password_user_can_disconnect_provider(self):
        user = self.user()
        account = self.link(user)
        self.client.force_login(user)
        self.reauth()
        self.assertRedirects(
            self.client.post(reverse("social_disconnect", args=[account.pk])),
            reverse("social_connections"),
        )
        self.assertFalse(SocialAccount.objects.exists())

    def test_social_only_last_provider_cannot_be_removed(self):
        user = self.user(password=False)
        account = self.link(user)
        self.client.force_login(user)
        self.callback(purpose="reauthenticate")
        response = self.client.post(reverse("social_disconnect", args=[account.pk]), follow=True)
        self.assertContains(response, "Add a password or connect another account first.")
        self.assertTrue(SocialAccount.objects.filter(pk=account.pk).exists())

    def test_social_only_can_remove_one_of_two_providers(self):
        user = self.user(password=False)
        account = self.link(user)
        self.link(user, "github")
        self.client.force_login(user)
        self.callback(purpose="reauthenticate")
        self.assertRedirects(
            self.client.post(reverse("social_disconnect", args=[account.pk])),
            reverse("social_connections"),
        )
        self.assertEqual(SocialAccount.objects.get().provider, "github")

    def test_first_password_keeps_provider_then_allows_disconnect(self):
        user = self.user(password=False)
        account = self.link(user)
        self.client.force_login(user)
        self.callback(purpose="reauthenticate")
        self.assertRedirects(
            self.client.post(
                reverse("first_password"),
                {"new_password1": self.password, "new_password2": self.password},
            ),
            reverse("social_connections"),
        )
        user.refresh_from_db()
        self.assertTrue(user.check_password(self.password))
        self.assertTrue(SocialAccount.objects.filter(pk=account.pk).exists())
        self.assertNotIn(RECENT_KEY, self.client.session)
        self.reauth()
        self.client.post(reverse("social_disconnect", args=[account.pk]))
        self.assertFalse(SocialAccount.objects.exists())
        self.client.logout()
        self.assertRedirects(
            self.client.post(
                reverse("login"), {"username": user.username, "password": self.password}
            ),
            reverse("mfa_reminder"),
        )

    def test_existing_password_cannot_use_set_first_password(self):
        user = self.user()
        self.client.force_login(user)
        self.assertRedirects(
            self.client.get(reverse("first_password")), reverse("account_security")
        )

    def test_disconnect_is_post_only_and_user_scoped(self):
        user = self.user()
        account = self.link(user)
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse("social_disconnect", args=[account.pk])).status_code, 405
        )
        self.reauth()
        other = self.link(self.user("other"), uid="other")
        self.assertEqual(
            self.client.post(reverse("social_disconnect", args=[other.pk])).status_code, 404
        )

    def test_connections_private_and_linked_from_profile(self):
        self.assertEqual(self.client.get(reverse("social_connections")).status_code, 302)
        user = self.user()
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("profile_edit")), reverse("social_connections"))
        response = self.client.get(reverse("social_connections"))
        self.assertNotContains(response, "Microsoft")
        self.assertEqual([p["id"] for p in response.context["providers"]], ["google", "github"])
        for name in PROVIDERS.values():
            self.assertContains(response, name)

    def test_cancelled_connect_returns_to_connections(self):
        user = self.user()
        self.client.force_login(user)
        self.reauth()
        state = self.start(purpose="connect")
        self.assertRedirects(
            self.client.get(reverse("google_callback"), {"state": state, "error": "access_denied"}),
            reverse("social_connections"),
        )
        self.assertFalse(SocialAccount.objects.exists())

    def test_expired_oauth_and_onboarding_requests(self):
        state = self.start()
        with patch("skillmatch.social.time.time", return_value=time.time() + 301):
            self.assertRedirects(self.callback(state=state), reverse("login"))
        self.callback()
        with patch("skillmatch.social_views.time.time", return_value=time.time() + 301):
            self.assertRedirects(
                self.client.post(reverse("socialaccount_signup"), {"role": "seeker"}),
                reverse("login"),
            )
        self.assertFalse(User.objects.exists())

    def test_social_only_can_enable_mfa_from_security_after_reauth(self):
        user = self.user(password=False)
        self.link(user)
        self.client.force_login(user)
        self.assertRedirects(
            self.client.post(reverse("social_enable_mfa")), reverse("social_reauthenticate")
        )
        self.callback(purpose="reauthenticate")
        self.assertRedirects(self.client.post(reverse("social_enable_mfa")), reverse("mfa_setup"))

    def test_github_fetches_verified_email_endpoint_when_public_email_absent(self):
        state = self.start("github")
        profile, emails = Mock(), Mock()
        profile.json.return_value = {
            "id": 123,
            "login": "amina",
            "name": "Amina Kamau",
            "email": None,
        }
        emails.status_code = 200
        emails.json.return_value = [
            {"email": "private@example.test", "primary": True, "verified": True}
        ]
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.side_effect = [profile, emails]
        with (
            patch(
                "allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token",
                return_value={"access_token": "test-only-token"},
            ),
            patch("skillmatch.social.SocialAdapter.get_requests_session", return_value=session),
        ):
            response = self.client.get(reverse("github_callback"), {"code": "mock", "state": state})
        self.assertRedirects(response, reverse("socialaccount_signup"))
        self.assertEqual(
            session.get.call_args_list[1].args[0], "https://api.github.com/user/emails"
        )

    def test_github_public_email_without_verification_is_refused(self):
        for addresses in (
            [],
            [{"email": "public@example.test", "primary": True, "verified": False}],
        ):
            with self.subTest(addresses=addresses):
                state = self.start("github")
                profile, emails = Mock(), Mock()
                profile.json.return_value = {
                    "id": 123,
                    "login": "amina",
                    "email": "public@example.test",
                }
                emails.status_code = 200
                emails.json.return_value = addresses
                session = Mock()
                session.__enter__ = Mock(return_value=session)
                session.__exit__ = Mock(return_value=False)
                session.get.side_effect = [profile, emails]
                with (
                    patch(
                        "allauth.socialaccount.providers.oauth2.client.OAuth2Client.get_access_token",
                        return_value={"access_token": "test-only-token"},
                    ),
                    patch(
                        "skillmatch.social.SocialAdapter.get_requests_session", return_value=session
                    ),
                ):
                    response = self.client.get(
                        reverse("github_callback"), {"code": "mock", "state": state}
                    )
                self.assertRedirects(response, reverse("login"))
                self.assertFalse(User.objects.exists())
                self.assertFalse(SocialAccount.objects.exists())
                self.assert_anonymous()

    def google_token_callback(self, overrides=None):
        state = self.start("google")
        verifier = self.client.session["socialaccount_states"][state][0]["pkce_code_verifier"]
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "test-client",
            "sub": "google-123",
            "exp": time.time() + 300,
            "iat": time.time(),
            "email": "google@example.test",
            "email_verified": True,
            "given_name": "Amina",
            "family_name": "Kamau",
        }
        claims.update(overrides or {})
        # Simulate Google's TLS token response; allauth validates its claims.
        credential = jwt.encode(
            claims, "test-token-signing-key-not-used-outside-tests", algorithm="HS256"
        )
        token_response = Mock(status_code=200, headers={"content-type": "application/json"})
        token_response.json.return_value = {
            "access_token": "test-only-token",
            "id_token": credential,
        }
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.request.return_value = token_response
        with patch("skillmatch.social.SocialAdapter.get_requests_session", return_value=session):
            response = self.client.get(reverse("google_callback"), {"code": "mock", "state": state})
        self.assertEqual(
            session.request.call_args.args[:2], ("POST", "https://oauth2.googleapis.com/token")
        )
        self.assertEqual(session.request.call_args.kwargs["data"]["code_verifier"], verifier)
        return response

    def test_google_real_adapter_accepts_verified_identity(self):
        self.assertRedirects(self.google_token_callback(), reverse("socialaccount_signup"))
        self.assert_anonymous()
        self.client.post(reverse("socialaccount_signup"), {"role": "seeker"})
        user = User.objects.get()
        self.assertEqual(user.email, "google@example.test")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(SocialAccount.objects.get().uid, "google-123")
        self.assertFalse(SocialToken.objects.exists())

    def test_google_real_adapter_refuses_invalid_claims(self):
        for claims in (
            {"aud": "other-client"},
            {"iss": "https://evil.example"},
            {"exp": 1},
            {"email_verified": False},
            {"email": None},
        ):
            with self.subTest(claims=claims):
                self.assertRedirects(self.google_token_callback(claims), reverse("login"))
                self.assertFalse(User.objects.exists())
                self.assert_anonymous()

    def test_both_providers_start_with_correct_callback_scopes_and_pkce(self):
        for provider, host, scopes in (
            ("google", "accounts.google.com", {"openid", "email", "profile"}),
            ("github", "github.com", {"read:user", "user:email"}),
        ):
            with self.subTest(provider=provider):
                response = self.client.post(
                    reverse(f"{provider}_login"), HTTP_HOST="127.0.0.1:8000"
                )
                self.assertEqual(response.status_code, 302)
                url = urlsplit(response.url)
                query = parse_qs(url.query)
                self.assertEqual(url.hostname, host)
                self.assertEqual(
                    query["redirect_uri"],
                    [f"http://127.0.0.1:8000/accounts/social/{provider}/login/callback/"],
                )
                self.assertEqual(set(query["scope"][0].split()), scopes)
                self.assertEqual(query["code_challenge_method"], ["S256"])
                state = self.client.session["socialaccount_states"][query["state"][0]][0]
                challenge = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(state["pkce_code_verifier"].encode()).digest()
                    )
                    .rstrip(b"=")
                    .decode()
                )
                self.assertEqual(query["code_challenge"], [challenge])

    def test_both_providers_keep_onboarding_reminder_totp_and_recovery(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.client.logout()
                self.assertRedirects(
                    self.callback(provider, email=f"{provider}@example.test"),
                    reverse("socialaccount_signup"),
                )
                self.assert_anonymous()
                self.assertRedirects(
                    self.client.post(reverse("socialaccount_signup"), {"role": "seeker"}),
                    reverse("mfa_reminder"),
                )
                user = SocialAccount.objects.get(provider=provider).user
                self.assertEqual(user.account.active_role, "seeker")
                self.assertFalse(user.has_usable_password())
                self.client.post(reverse("mfa_reminder"), {"action": "later"})
                self.assertEqual(self.client.get(reverse("jobs")).status_code, 200)
                device = TOTPDevice.objects.create(user=user, confirmed=True)
                self.client.logout()
                self.assertRedirects(
                    self.callback(provider, next=reverse("jobs")), reverse("mfa_verify")
                )
                self.assert_anonymous()
                self.assertRedirects(
                    self.client.post(reverse("mfa_verify"), {"code": self.totp(device)}),
                    reverse("jobs"),
                )
                self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
                code = generate_codes(device)[0]
                self.client.post(reverse("logout"))
                self.assert_anonymous()
                self.assertRedirects(
                    self.callback(provider, next=reverse("jobs")), reverse("mfa_verify")
                )
                self.assert_anonymous()
                self.assertRedirects(
                    self.client.post(reverse("mfa_recovery"), {"code": code}), reverse("jobs")
                )
                self.assertIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_both_providers_enforce_staff_mfa_setup_and_verification(self):
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.client.logout()
                user = self.user(f"staff_{provider}", is_staff=True)
                self.link(user, provider)
                self.assertRedirects(
                    self.callback(provider, next=reverse("admin:index")), reverse("mfa_setup")
                )
                self.assert_anonymous()
                self.assertNotContains(self.client.get(reverse("mfa_setup")), "Not now")
                self.assertEqual(self.client.get(reverse("admin:index")).status_code, 302)
                device = TOTPDevice.objects.get(user=user)
                self.client.post(reverse("mfa_setup"), {"code": self.totp(device)})
                self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
                self.client.post(reverse("logout"))
                self.assertRedirects(
                    self.callback(provider, next=reverse("admin:index")), reverse("mfa_verify")
                )
                self.assert_anonymous()

    def test_connected_provider_with_missing_config_is_not_lockout_alternative(self):
        user = self.user(password=False)
        google = self.link(user)
        self.link(user, "github")
        self.client.force_login(user)
        self.callback(purpose="reauthenticate")
        with override_settings(SOCIALACCOUNT_PROVIDERS={"google": PROVIDER_SETTINGS["google"]}):
            self.client.post(reverse("social_disconnect", args=[google.pk]))
        self.assertTrue(SocialAccount.objects.filter(pk=google.pk).exists())

    def test_first_password_validators_and_expired_confirmation(self):
        user = self.user(password=False)
        self.link(user)
        self.client.force_login(user)
        self.callback(purpose="reauthenticate")
        response = self.client.post(
            reverse("first_password"), {"new_password1": "123", "new_password2": "123"}
        )
        self.assertContains(response, "too short")
        session = self.client.session
        session[RECENT_KEY]["at"] = 0
        session.save()
        self.assertRedirects(
            self.client.post(
                reverse("first_password"),
                {"new_password1": self.password, "new_password2": self.password},
            ),
            reverse("social_reauthenticate"),
        )
        user.refresh_from_db()
        self.assertFalse(user.has_usable_password())

    def test_oauth_state_is_single_use_and_bound_to_provider(self):
        state = self.start("google")
        self.assertRedirects(self.callback("github", state=state), reverse("login"))
        self.assertRedirects(self.callback("google", state=state), reverse("socialaccount_signup"))
        self.assertRedirects(self.callback("google", state=state), reverse("login"))

    def test_only_provider_endpoints_are_exposed(self):
        for path in [
            "/accounts/social/signup/",
            "/accounts/password/reset/",
            "/accounts/google/login/token/",
            "/accounts/social/microsoft/login/",
            "/accounts/social/microsoft/login/callback/",
        ]:
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.post(path).status_code, 404)

    def test_sensitive_post_actions_require_csrf(self):
        user = self.user()
        account = self.link(user)
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        for name, args in [
            ("social_disconnect", [account.pk]),
            ("social_reauthenticate", []),
            ("first_password", []),
        ]:
            self.assertEqual(client.post(reverse(name, args=args)).status_code, 403)

    def test_password_confirmation_throttles_retries(self):
        user = self.user()
        self.client.force_login(user)
        for _ in range(5):
            self.client.post(reverse("social_reauthenticate"), {"password": "wrong"})
        response = self.client.post(reverse("social_reauthenticate"), {"password": self.password})
        self.assertContains(response, "Too many attempts")
        self.assertNotIn(RECENT_KEY, self.client.session)
