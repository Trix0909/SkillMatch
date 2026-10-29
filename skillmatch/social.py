"""Provider identity policy and the handoff to SkillMatch's existing MFA flow."""

import time

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import redirect
from django.utils.crypto import constant_time_compare

from .mfa import (
    PENDING_KEY,
    begin_pending,
    confirmed_device,
    is_admin,
    pending_route,
    safe_destination,
)
from .mfa_views import REMINDER_KEY

PROVIDERS = {"google": "Google", "github": "GitHub"}
SOCIAL_BACKEND = "allauth.account.auth_backends.AuthenticationBackend"
RECENT_KEY = "skillmatch_recent_auth"


def configured(provider):
    return provider in PROVIDERS and any(
        app.get("client_id") and app.get("secret")
        for app in settings.SOCIALACCOUNT_PROVIDERS.get(provider, {}).get("APPS", [])
    )


def provider_buttons(request):
    return {
        "social_providers": [
            {"id": key, "name": name, "configured": configured(key)}
            for key, name in PROVIDERS.items()
        ]
    }


def can_auto_link(user, email):
    # Local registration has no independent verified-email evidence. Provider
    # EmailAddress rows are not evidence of ownership of a pre-existing account.
    return False


def verified_email(sociallogin):
    for address in sorted(sociallogin.email_addresses, key=lambda item: not item.primary):
        if address.verified is not True:
            continue
        try:
            validate_email(address.email)
        except ValidationError:
            continue
        return address.email
    return None


def mark_recent(request, method):
    request.session.cycle_key()
    request.session[RECENT_KEY] = {
        "user": request.user.pk,
        "hash": request.user.get_session_auth_hash(),
        "at": time.time(),
        "method": method,
    }


def recently_authenticated(request):
    # allauth 65.20's default check accepts social-only users with no available
    # reauthentication flow. Require explicit, bounded evidence instead.
    record = request.session.get(RECENT_KEY, {})
    return (
        request.user.is_authenticated
        and record.get("user") == request.user.pk
        and constant_time_compare(record.get("hash", ""), request.user.get_session_auth_hash())
        and 0 <= time.time() - record.get("at", 0) < settings.SSO_RECENT_AUTH_SECONDS
        and (not request.user.has_usable_password() or record.get("method") == "password")
    )


def complete_first_factor(request, user, destination):
    if not user.is_active:
        messages.error(request, "This account cannot sign in. Please contact the administrator.")
        return redirect("login")
    destination = safe_destination(request, destination)
    request.session.pop(RECENT_KEY, None)
    if is_admin(user) or confirmed_device(user):
        begin_pending(request, user, backend=SOCIAL_BACKEND, destination=destination)
        return redirect(pending_route(user))
    request.session.pop(PENDING_KEY, None)
    login(request, user, backend=SOCIAL_BACKEND)
    request.session[REMINDER_KEY] = {
        "next": destination,
        "password_verified_at": time.time(),
        "shown": False,
    }
    return redirect("mfa_reminder")


def refuse(request, message, target="login"):
    messages.error(request, message)
    raise ImmediateHttpResponse(redirect(target))


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

    def pre_login(self, request, user, **kwargs):
        # Defense in depth: no allauth completion may skip SkillMatch MFA.
        return complete_first_factor(request, user, kwargs.get("redirect_url"))


class SocialAdapter(DefaultSocialAccountAdapter):
    def list_apps(self, request, provider=None, client_id=None):
        apps = []
        for key, name in PROVIDERS.items():
            if (provider and key != provider) or not configured(key):
                continue
            for values in settings.SOCIALACCOUNT_PROVIDERS[key]["APPS"]:
                if client_id and values["client_id"] != client_id:
                    continue
                apps.append(SocialApp(provider=key, name=name, **values))
        return apps

    def can_authenticate_by_email(self, sociallogin, email):
        return can_auto_link(None, email)

    def is_email_verified(self, provider, email):
        # Never turn an arbitrary provider email into a verified one by domain.
        return False

    def is_open_for_signup(self, request, sociallogin):
        return True

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        email = verified_email(sociallogin)
        sociallogin.account.extra_data = {"email": email} if email else {}
        sociallogin.email_addresses = [a for a in sociallogin.email_addresses if a.email == email]
        return user

    def pre_social_login(self, request, sociallogin):
        state = sociallogin.state
        data = state.get("data") or {}
        target = "social_connections" if request.user.is_authenticated else "login"
        if not configured(sociallogin.account.provider) or not (
            0 <= time.time() - data.get("started", 0) < settings.SSO_RECENT_AUTH_SECONDS
        ):
            refuse(request, "Your sign-in request expired. Please try again.", target)
        sociallogin.token = None
        state["next"] = safe_destination(request, state.get("next"))
        purpose = data.get("purpose")
        if purpose in {"connect", "reauthenticate"}:
            if (
                not request.user.is_authenticated
                or data.get("user") != request.user.pk
                or not constant_time_compare(
                    data.get("hash", ""), request.user.get_session_auth_hash()
                )
            ):
                refuse(request, "Please sign in again before managing connected accounts.", target)
            if purpose == "reauthenticate":
                if (
                    request.user.has_usable_password()
                    or not sociallogin.is_existing
                    or sociallogin.user.pk != request.user.pk
                ):
                    refuse(request, "Use a provider already connected to this account.", target)
                mark_recent(request, "provider")
                messages.success(
                    request, "Identity confirmed. You can continue your account change."
                )
                raise ImmediateHttpResponse(redirect("social_connections"))
            if not recently_authenticated(request):
                refuse(
                    request,
                    "Confirm your identity again before connecting an account.",
                    "social_reauthenticate",
                )
            if sociallogin.is_existing and sociallogin.user.pk != request.user.pk:
                refuse(
                    request,
                    "That provider identity is already connected to another account.",
                    target,
                )
            if not verified_email(sociallogin):
                refuse(
                    request,
                    "The provider did not supply a verified email. No account was connected.",
                    target,
                )
            state["process"] = "connect"
            state["next"] = None
            return
        if purpose != "login" or request.user.is_authenticated:
            refuse(request, "Please start sign-in again from the login page.", target)
        if sociallogin.is_existing:
            raise ImmediateHttpResponse(
                complete_first_factor(request, sociallogin.user, state["next"])
            )
        email = verified_email(sociallogin)
        if not email:
            refuse(
                request,
                "The provider did not supply a verified email. Please use another sign-in method.",
            )
        if get_user_model().objects.filter(email__iexact=email).exists():
            refuse(
                request,
                f"An account with this email already exists. Log in with your password, then connect {PROVIDERS[sociallogin.account.provider]} from your profile.",
            )
        sociallogin.user.email = email
        sociallogin.user.set_unusable_password()

    def get_connect_redirect_url(self, request, socialaccount):
        from django.urls import reverse

        return reverse("social_connections")

    def on_authentication_error(self, request, provider, **kwargs):
        refuse(
            request,
            "Provider sign-in was cancelled or could not be completed. Please try again.",
            "social_connections" if request.user.is_authenticated else "login",
        )
