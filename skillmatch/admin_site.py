"""Keep the existing admin registry, using SkillMatch's two-stage sign-in."""

from django.contrib.auth.views import redirect_to_login
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django_otp.admin import OTPAdminSite


class SkillMatchAdminSite(OTPAdminSite):
    index_template = "admin/overview.html"
    enable_nav_sidebar = False

    def __init__(self, name="admin"):
        super().__init__(name)

    def has_permission(self, request):
        from .mfa import is_mfa_verified

        return super().has_permission(request) and is_mfa_verified(request.user)

    def login(self, request, extra_context=None):
        # No parallel password-only admin login, including direct POSTs here.
        destination = request.GET.get("next") or reverse("admin:index")
        return redirect_to_login(destination)

    def get_urls(self):
        return [
            path("reports/", self.admin_view(self.reports), name="reports"),
            path("settings/", self.admin_view(self.settings_directory), name="settings"),
            path("search/", self.admin_view(self.search), name="search"),
        ] + super().get_urls()

    def each_context(self, request):
        from .admin_dashboard import navigation

        context = super().each_context(request)
        context["admin_navigation"] = navigation(self, request) if context["has_permission"] else []
        name = (
            request.user.get_full_name() or request.user.get_username()
            if request.user.is_authenticated
            else ""
        )
        context["admin_display_name"] = name
        context["admin_initials"] = "".join(part[0] for part in name.split()[:2]).upper()
        profile = (
            getattr(request.user, "seeker_profile", None) if context["has_permission"] else None
        )
        context["admin_photo_url"] = profile.photo.url if profile and profile.photo else ""
        return context

    def index(self, request, extra_context=None):
        from .admin_dashboard import dashboard_data

        return super().index(request, {**dashboard_data(self, request), **(extra_context or {})})

    def reports(self, request):
        from .admin_dashboard import dashboard_data

        return TemplateResponse(
            request,
            "admin/reports.html",
            {
                **self.each_context(request),
                **dashboard_data(self, request),
                "title": "Reports",
            },
        )

    def settings_directory(self, request):
        return TemplateResponse(
            request,
            "admin/settings_directory.html",
            {
                **self.each_context(request),
                "title": "Settings",
            },
        )

    def search(self, request):
        from .admin_dashboard import search_destinations

        query = request.GET.get("q", "").strip()[:200]
        return TemplateResponse(
            request,
            "admin/search.html",
            {
                **self.each_context(request),
                "title": "Search administration",
                "query": query,
                "destinations": search_destinations(self, request, query),
            },
        )
