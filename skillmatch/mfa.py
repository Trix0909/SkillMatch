"""MFA policy and expiring first-factor handoffs; TOTP is handled by django-otp."""

import time

from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.shortcuts import resolve_url
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_variables
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

PENDING_KEY = "skillmatch_mfa_pending"


def is_admin(user):
    return user.is_staff or user.is_superuser


def confirmed_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).order_by("pk").first()


def is_totp_verified(user):
    device = getattr(user, "otp_device", None)
    return (
        user.is_authenticated
        and isinstance(device, TOTPDevice)
        and device.confirmed
        and device.user_id == user.pk
        and user.is_verified()
    )


def safe_destination(request, destination):
    if destination and url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        # Avoid cycling into a completed or expired authentication step.
        from urllib.parse import urlsplit

        excluded = {reverse(name) for name in ("login", "mfa_setup", "mfa_verify", "mfa_cancel")}
        excluded.add(reverse("admin:login"))
        if urlsplit(destination).path not in excluded:
            return destination
    return resolve_url(settings.LOGIN_REDIRECT_URL)


@sensitive_variables()
def begin_pending(request, user, *, backend, destination, mode="login"):
    if mode == "login":
        # No Django authenticated session exists until both stages succeed.
        logout(request)
    else:
        request.session.cycle_key()
    request.session[PENDING_KEY] = {
        "user_id": user.pk,
        "auth_hash": user.get_session_auth_hash(),
        "backend": backend,
        "expires": time.time() + settings.MFA_PENDING_SECONDS,
        "next": safe_destination(request, destination),
        "mode": mode,
    }


@sensitive_variables()
def pending_user(request):
    pending = request.session.get(PENDING_KEY)
    if not isinstance(pending, dict):
        return None
    user = get_user_model().objects.filter(pk=pending.get("user_id"), is_active=True).first()
    valid = (
        user is not None
        and pending.get("expires", 0) > time.time()
        and pending.get("backend") in settings.AUTHENTICATION_BACKENDS
        and constant_time_compare(pending.get("auth_hash", ""), user.get_session_auth_hash())
    )
    if pending.get("mode") == "enroll":
        valid = valid and request.user.is_authenticated and request.user.pk == user.pk
    elif pending.get("mode") == "login":
        valid = valid and not request.user.is_authenticated
    else:
        valid = False
    if not valid:
        request.session.pop(PENDING_KEY, None)
        return None
    return user


def pending_route(user):
    return "mfa_verify" if confirmed_device(user) else "mfa_setup"


@transaction.atomic
def enrollment_device(user):
    # Serialize device creation per account. SQLite fails concurrent conflicting
    # writes rather than committing duplicate devices; row locks also support PostgreSQL.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if confirmed_device(user):
        return None
    device = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("pk").first()
    if device is None:
        device = TOTPDevice.objects.create(user=user, name="Authenticator app", confirmed=False)
    return device


class MFAEnforcementMiddleware:
    """Enforce required MFA even for sessions created before MFA was enabled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        had_device = DEVICE_ID_SESSION_KEY in request.session
        user = request.user
        if user.is_authenticated and request.path != reverse("logout"):
            required = is_admin(user) or had_device or confirmed_device(user) is not None
            if required and not is_totp_verified(user):
                destination = safe_destination(request, request.get_full_path())
                logout(request)
                return redirect_to_login(destination)
        return self.get_response(request)
