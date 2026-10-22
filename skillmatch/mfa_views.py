"""Small integration around the existing password form and django-otp devices."""

import time
from base64 import b32encode
from functools import wraps

import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import OperationalError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from .forms import LoginForm
from .mfa import (
    PENDING_KEY,
    begin_pending,
    confirmed_device,
    enrollment_device,
    is_admin,
    pending_route,
    pending_user,
    safe_destination,
)
from .mfa_forms import (
    AuthenticatorCodeForm,
    EnableTwoFactorForm,
    RecoveryCodeForm,
    RegenerateRecoveryCodesForm,
)
from .mfa_recovery import (
    RECOVERY_CODE_COUNT,
    generate_codes,
    regenerate_codes,
    verify_recovery_code,
)
from .models import RecoveryDevice

REMINDER_KEY = "skillmatch_mfa_reminder"


def private_mfa_page(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        # Keep same-origin form POSTs compatible with CSRF Origin validation,
        # while withholding referrers from other sites.
        response["Referrer-Policy"] = "same-origin"
        return response

    return never_cache(sensitive_post_parameters("password", "code")(wrapped))


class MFALoginView(LoginView):
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get(self, request, *args, **kwargs):
        user = pending_user(request)
        if user:
            return redirect(pending_route(user))
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if is_admin(user) or confirmed_device(user):
            destination = self.get_success_url()
            begin_pending(
                request=self.request, user=user, backend=user.backend, destination=destination
            )
            return redirect(pending_route(user))
        self.request.session.pop(PENDING_KEY, None)
        response = super().form_valid(form)
        # The user is fully signed in. This invitation never gates site access.
        self.request.session[REMINDER_KEY] = {
            "next": safe_destination(self.request, response.url),
            "password_verified_at": time.time(),
            "shown": False,
        }
        return redirect("mfa_reminder")


@private_mfa_page
@login_required
@require_http_methods(["GET", "POST"])
def reminder(request):
    invitation = request.session.get(REMINDER_KEY)
    destination = safe_destination(request, invitation.get("next") if invitation else None)
    if is_admin(request.user) or confirmed_device(request.user) or not invitation:
        request.session.pop(REMINDER_KEY, None)
        return redirect(destination)
    if request.method == "POST":
        action = request.POST.get("action")
        if action not in {"enable", "later"}:
            return HttpResponseBadRequest("Choose Enable now or Not now.")
        request.session.pop(REMINDER_KEY, None)
        if action == "enable":
            if time.time() - invitation["password_verified_at"] > settings.MFA_PENDING_SECONDS:
                # Reuse the existing password-confirmed settings flow if stale.
                return redirect("account_security")
            begin_pending(
                request,
                request.user,
                backend=request.session[BACKEND_SESSION_KEY],
                destination=destination,
                mode="enroll",
            )
            return redirect("mfa_setup")
        return redirect(destination)
    if invitation["shown"]:
        return redirect(destination)
    invitation["shown"] = True
    request.session[REMINDER_KEY] = invitation
    return render(request, "registration/mfa_reminder.html")


@private_mfa_page
@login_required
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def security(request):
    enabled = confirmed_device(request.user) is not None
    form = EnableTwoFactorForm(
        request.POST if request.method == "POST" else None, user=request.user
    )
    if request.method == "POST" and not enabled and form.is_valid():
        begin_pending(
            request,
            request.user,
            backend=request.session[BACKEND_SESSION_KEY],
            destination=reverse("account_security"),
            mode="enroll",
        )
        return redirect("mfa_setup")
    recovery = (
        RecoveryDevice.objects.filter(
            user=request.user, authenticator__confirmed=True, confirmed=True
        ).first()
        if enabled
        else None
    )
    return render(
        request,
        "registration/security.html",
        {
            "enabled": enabled,
            "form": form,
            "remaining_codes": recovery.codes.count() if recovery else 0,
            "total_codes": RECOVERY_CODE_COUNT,
        },
    )


def expired_challenge(request):
    messages.info(request, "Please confirm your password again to continue securely.")
    return redirect("account_security" if request.user.is_authenticated else "login")


@sensitive_variables()
def verify_code(user, device_id, code, *, confirm=False):
    # Failure must commit the library's throttle counter. Never roll it back by
    # raising form validation errors inside this transaction.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        if confirm and confirmed_device(user):
            return None
        device = (
            TOTPDevice.objects.select_for_update()
            .filter(pk=device_id, user=user, confirmed=not confirm)
            .first()
        )
        if device is None or not device.verify_token(code):
            return None
        if confirm:
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            device.recovery_codes = generate_codes(device)
        return device


@sensitive_variables()
def complete_challenge(request, user, device):
    pending = request.session.pop(PENDING_KEY)
    destination = safe_destination(request, pending["next"])
    if pending["mode"] == "login":
        user.otp_device = device
        login(request, user, backend=pending["backend"])
    else:
        request.session.cycle_key()
    otp_login(request, device)
    return redirect(destination)


@sensitive_variables()
def check_code(request, form, user, device, *, confirm=False):
    if request.method != "POST" or not form.is_valid():
        return None
    try:
        verified = verify_code(user, device.pk, form.cleaned_data["code"], confirm=confirm)
    except OperationalError:
        # SQLite serializes writes; a concurrent verification must fail closed.
        form.add_error(None, "Another request is in progress. Please try again shortly.")
        return None
    if verified is not None:
        response = complete_challenge(request, user, verified)
        if confirm:
            return recovery_codes_page(request, verified.recovery_codes, response.url)
        return response
    form.add_error(
        "code",
        "Invalid authentication code. Please try again. After repeated attempts, "
        "wait before retrying. If you just used a code, wait for the next one.",
    )
    return None


@private_mfa_page
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def setup(request):
    user = pending_user(request)
    if user is None:
        return expired_challenge(request)
    pending = request.session[PENDING_KEY]
    if confirmed_device(user):
        return redirect("account_security" if request.user.is_authenticated else "mfa_verify")
    if pending["mode"] != "enroll" and not is_admin(user):
        request.session.pop(PENDING_KEY, None)
        return expired_challenge(request)
    device = enrollment_device(user)
    if device is None:
        return redirect("mfa_verify")
    form = AuthenticatorCodeForm(request.POST if request.method == "POST" else None)
    response = check_code(request, form, user, device, confirm=True)
    if response is not None:
        return response
    # Encode locally. No third-party QR service, secret-bearing HTTP URL or logs.
    qr_image = segno.make(device.config_url, micro=False).svg_data_uri(scale=5, border=4)
    return render(
        request,
        "registration/mfa_setup.html",
        {
            "form": form,
            "qr_image": qr_image,
            "manual_key": b32encode(device.bin_key).decode("ascii"),
            "mandatory": is_admin(user),
        },
    )


@private_mfa_page
@require_http_methods(["GET", "POST"])
def verify(request):
    user = pending_user(request)
    if user is None:
        return expired_challenge(request)
    device = confirmed_device(user)
    if device is None:
        return redirect("mfa_setup") if is_admin(user) else expired_challenge(request)
    form = AuthenticatorCodeForm(request.POST if request.method == "POST" else None)
    response = check_code(request, form, user, device)
    return (
        response
        if response is not None
        else render(request, "registration/mfa_verify.html", {"form": form})
    )


@sensitive_variables()
def recovery_codes_page(request, codes, destination):
    # Render directly from the successful POST. No plaintext is persisted in
    # sessions, messages, URLs, files or a later GET/download endpoint.
    return render(
        request,
        "registration/recovery_codes.html",
        {
            "codes": codes,
            "destination": safe_destination(request, destination),
        },
    )


@private_mfa_page
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def recovery(request):
    user = pending_user(request)
    if user is None:
        return expired_challenge(request)
    if request.session[PENDING_KEY]["mode"] != "login" or confirmed_device(user) is None:
        return redirect(pending_route(user))
    form = RecoveryCodeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        valid = form.is_valid()
        try:
            verified = verify_recovery_code(
                user, form.cleaned_data.get("code", "") if valid else ""
            )
        except OperationalError:
            verified = None
        if verified is not None:
            response = complete_challenge(request, user, verified)
            messages.info(
                request,
                format_html(
                    "You signed in using a recovery code. If you no longer have access to your "
                    'authenticator app, update your <a href="{}">Two-factor authentication settings</a> '
                    "from your profile. Your account is still protected by 2FA.",
                    reverse("account_security"),
                ),
            )
            return response
        form.add_error(
            None,
            "Invalid or already used recovery code. Wait before retrying after repeated attempts.",
        )
    return render(request, "registration/mfa_recovery.html", {"form": form})


@private_mfa_page
@login_required
@sensitive_variables()
@require_http_methods(["GET", "POST"])
def recovery_generate(request):
    if confirmed_device(request.user) is None:
        return redirect("account_security")
    form = RegenerateRecoveryCodesForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        valid = form.is_valid()
        try:
            codes = regenerate_codes(
                request.user, form.cleaned_data.get("password", "") if valid else ""
            )
        except OperationalError:
            codes = None
        if codes is not None:
            request.session.cycle_key()
            return recovery_codes_page(request, codes, reverse("account_security"))
        form.add_error(
            None,
            "Unable to verify your password. Please try again, waiting before retrying after repeated attempts.",
        )
    return render(request, "registration/recovery_generate.html", {"form": form})


@private_mfa_page
@require_POST
def cancel(request):
    request.session.pop(PENDING_KEY, None)
    if request.user.is_authenticated:
        return redirect("account_security")
    logout(request)
    return redirect("login")
