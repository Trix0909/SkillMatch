"""Small SkillMatch views around allauth's provider handshakes and identity store."""

import secrets
import time
from uuid import UUID

import jwt
from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.internal.flows.connect import disconnect, validate_disconnect
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialLogin
from allauth.socialaccount.providers.github.views import GitHubOAuth2Adapter
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.microsoft.views import MicrosoftGraphOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.oauth2.views import OAuth2CallbackView
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods, require_POST

from .forms import RoleSetupForm, StyledForm
from .mfa import begin_pending, safe_destination
from .mfa_views import private_mfa_page
from .social import (
    PROVIDERS,
    RECENT_KEY,
    complete_first_factor,
    configured,
    mark_recent,
    recently_authenticated,
    verified_email,
)


class MicrosoftAdapter(MicrosoftGraphOAuth2Adapter):
    profile_url_params = {"$select": "id,givenName,surname"}

    @sensitive_variables()
    def complete_login(self, request, app, token, **kwargs):
        credential = kwargs["response"].get("id_token", "")
        try:
            # Only the tenant identifier is inspected before cryptographic validation.
            tenant = str(UUID(jwt.decode(credential, options={"verify_signature": False})["tid"]))
            if jwt.get_unverified_header(credential).get("alg") != "RS256":
                raise ValueError()
            selected = settings.SOCIALACCOUNT_PROVIDERS["microsoft"].get("TENANT", "common")
            if selected not in {"common", "organizations", "consumers", tenant}:
                raise ValueError()
            claims = jwtkit.verify_and_decode(
                credential=credential,
                keys_url="https://login.microsoftonline.com/common/discovery/v2.0/keys",
                issuer=f"https://login.microsoftonline.com/{tenant}/v2.0",
                audience=app.client_id,
                lookup_kid=jwtkit.lookup_kid_jwk,
            )
            if not all(claims.get(key) for key in ("exp", "iat", "sub")):
                raise ValueError()
            if not request.sso_nonce or not constant_time_compare(
                claims.get("nonce", ""), request.sso_nonce
            ):
                raise ValueError()
        except (jwt.PyJWTError, ValueError, KeyError, AttributeError) as exc:
            raise OAuth2Error("Microsoft identity could not be verified") from exc
        sociallogin = super().complete_login(request, app, token, **kwargs)
        if claims.get("oid") != sociallogin.account.uid:
            raise OAuth2Error("Microsoft identity mismatch")
        if claims.get("xms_edov") is True and claims.get("email"):
            sociallogin.email_addresses = [
                EmailAddress(email=claims["email"], verified=True, primary=True)
            ]
        else:
            sociallogin.email_addresses = []
        email = verified_email(sociallogin)
        sociallogin.account.extra_data = {"email": email} if email else {}
        sociallogin.user.email = email or ""
        return sociallogin


class ProviderCallback(OAuth2CallbackView):
    def _get_state(self, request, provider):
        state, response = super()._get_state(request, provider)
        request.sso_nonce = (state or {}).get("data", {}).get("nonce", "")
        return state, response


ADAPTERS = {
    "google": GoogleOAuth2Adapter,
    "microsoft": MicrosoftAdapter,
    "github": GitHubOAuth2Adapter,
}


@private_mfa_page
@require_POST
def provider_start(request, provider):
    if not configured(provider):
        messages.info(request, "This sign-in provider is not configured yet.")
        return redirect("social_connections" if request.user.is_authenticated else "login")
    purpose = request.POST.get("purpose", "login")
    if purpose not in {"login", "connect", "reauthenticate"}:
        return HttpResponseBadRequest("Choose a valid sign-in action.")
    if purpose != "login":
        if not request.user.is_authenticated:
            return redirect("login")
        if purpose == "connect" and not recently_authenticated(request):
            return redirect("social_reauthenticate")
        if purpose == "reauthenticate" and (
            request.user.has_usable_password()
            or not SocialAccount.objects.filter(user=request.user, provider=provider).exists()
        ):
            return redirect("social_reauthenticate")
    elif request.user.is_authenticated:
        return redirect("social_connections")
    data = {"purpose": purpose, "started": time.time(), "nonce": secrets.token_urlsafe(32)}
    if request.user.is_authenticated:
        data.update(user=request.user.pk, hash=request.user.get_session_auth_hash())
    adapter = get_adapter(request)
    service = adapter.get_provider(request, provider)
    params = service.get_auth_params()
    if provider == "microsoft":
        params["nonce"] = data["nonce"]
    if purpose == "reauthenticate":
        params["prompt"] = "login" if provider == "microsoft" else "select_account"
        if provider == "google":
            params["max_age"] = "0"
    request.session.pop("socialaccount_sociallogin", None)
    return service.redirect(
        request,
        process="connect" if purpose == "connect" else "login",
        next_url=safe_destination(request, request.POST.get("next")),
        data=data,
        auth_params=params,
    )


@private_mfa_page
@require_http_methods(["GET"])
def provider_callback(request, provider):
    if not configured(provider):
        messages.info(request, "This sign-in provider is not configured yet.")
        return redirect("social_connections" if request.user.is_authenticated else "login")
    try:
        with transaction.atomic():
            return ProviderCallback.adapter_view(ADAPTERS[provider])(request)
    except (IntegrityError, OperationalError):
        messages.error(
            request,
            "This connection could not be completed. Please try again from Connected accounts.",
        )
        return redirect("social_connections" if request.user.is_authenticated else "login")


class OnboardingForm(StyledForm, RoleSetupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


@private_mfa_page
@require_http_methods(["GET", "POST"])
def onboarding(request):
    if request.user.is_authenticated:
        return redirect("home")
    payload = request.session.get("socialaccount_sociallogin")
    try:
        sociallogin = SocialLogin.deserialize(payload)
        started = sociallogin.state["data"]["started"]
        if (
            not configured(sociallogin.account.provider)
            or not 0 <= time.time() - started < settings.SSO_RECENT_AUTH_SECONDS
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError, SocialApp.DoesNotExist):
        request.session.pop("socialaccount_sociallogin", None)
        messages.info(
            request, "Please sign in with your provider again to finish creating your account."
        )
        return redirect("login")
    form = OnboardingForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        email = verified_email(sociallogin)
        try:
            with transaction.atomic():
                if not email or get_user_model().objects.filter(email__iexact=email).exists():
                    raise ValidationError(
                        "An account with this email already exists. Log in normally, then connect the provider from your profile."
                    )
                user = get_adapter(request).save_user(request, sociallogin)
                form.create_profile(user)
        except ValidationError as exc:
            request.session.pop("socialaccount_sociallogin", None)
            messages.error(request, exc.message)
            return redirect("login")
        except (IntegrityError, OperationalError):
            form.add_error(
                None,
                "Another request is in progress. Please restart provider sign-in if your account has already been created.",
            )
        else:
            request.session.pop("socialaccount_sociallogin", None)
            return complete_first_factor(request, user, sociallogin.state.get("next"))
    return render(request, "registration/social_onboarding.html", {"form": form})


@private_mfa_page
@login_required
@require_http_methods(["GET"])
def connections(request):
    accounts = list(SocialAccount.objects.filter(user=request.user))
    providers = [
        {
            "id": key,
            "name": name,
            "configured": configured(key),
            "accounts": [a for a in accounts if a.provider == key],
        }
        for key, name in PROVIDERS.items()
    ]
    return render(
        request,
        "registration/connections.html",
        {"providers": providers, "recent": recently_authenticated(request)},
    )


@private_mfa_page
@login_required
@require_http_methods(["GET", "POST"])
def reauthenticate(request):
    from .mfa_forms import EnableTwoFactorForm

    form = EnableTwoFactorForm(
        request.POST if request.method == "POST" else None, user=request.user
    )
    form.fields[
        "password"
    ].help_text = "Confirm your current password to manage your sign-in methods."
    if request.method == "POST" and request.user.has_usable_password():
        key = f"sso:reauth:{request.user.pk}"
        failures = cache.get(key, 0)
        if failures >= 5:
            form.add_error(None, "Too many attempts. Please wait five minutes before retrying.")
        elif form.is_valid():
            cache.delete(key)
            mark_recent(request, "password")
            messages.success(request, "Identity confirmed. You can continue your account change.")
            return redirect("social_connections")
        else:
            cache.set(key, failures + 1, settings.SSO_RECENT_AUTH_SECONDS)
    linked = SocialAccount.objects.filter(user=request.user).values_list("provider", flat=True)
    providers = [
        {"id": key, "name": name}
        for key, name in PROVIDERS.items()
        if key in linked and configured(key)
    ]
    return render(
        request, "registration/social_reauthenticate.html", {"form": form, "providers": providers}
    )


@private_mfa_page
@login_required
@require_POST
def disconnect_provider(request, pk):
    if not recently_authenticated(request):
        return redirect("social_reauthenticate")
    try:
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            account = get_object_or_404(SocialAccount, pk=pk, user=user)
            alternatives = SocialAccount.objects.filter(user=user).exclude(pk=pk)
            if not user.has_usable_password() and not any(
                configured(a.provider) for a in alternatives
            ):
                raise ValidationError("Add a password or connect another account first.")
            validate_disconnect(request, account)
            disconnect(request, account)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    except OperationalError:
        messages.error(request, "Another request is in progress. Please try again.")
    return redirect("social_connections")


class FirstPasswordForm(StyledForm, SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


@private_mfa_page
@login_required
@sensitive_post_parameters("new_password1", "new_password2")
@require_http_methods(["GET", "POST"])
def first_password(request):
    if request.user.has_usable_password():
        return redirect("account_security")
    if not recently_authenticated(request):
        return redirect("social_reauthenticate")
    form = FirstPasswordForm(request.user, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if user.has_usable_password():
                return redirect("account_security")
            form.user = user
            form.save()
            request.user = user
        update_session_auth_hash(request, request.user)
        request.session.pop(RECENT_KEY, None)
        messages.success(
            request, "Your SkillMatch password is set. Your connected providers are unchanged."
        )
        return redirect("social_connections")
    return render(request, "registration/first_password.html", {"form": form})


@private_mfa_page
@login_required
@require_POST
def social_enable_mfa(request):
    if request.user.has_usable_password():
        return redirect("account_security")
    if not recently_authenticated(request):
        return redirect("social_reauthenticate")
    begin_pending(
        request,
        request.user,
        backend=request.session[BACKEND_SESSION_KEY],
        destination=reverse("account_security"),
        mode="enroll",
    )
    return redirect("mfa_setup")
