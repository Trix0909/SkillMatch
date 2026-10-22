"""Keep the existing admin registry, using SkillMatch's two-stage sign-in."""

from django.contrib.auth.views import redirect_to_login
from django.urls import reverse
from django_otp.admin import OTPAdminSite


class SkillMatchAdminSite(OTPAdminSite):
    def __init__(self, name="admin"):
        super().__init__(name)

    def has_permission(self, request):
        from .mfa import is_totp_verified

        return super().has_permission(request) and is_totp_verified(request.user)

    def login(self, request, extra_context=None):
        # No parallel password-only admin login, including direct POSTs here.
        destination = request.GET.get("next") or reverse("admin:index")
        return redirect_to_login(destination)
