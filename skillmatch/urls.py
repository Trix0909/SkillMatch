from django.contrib.auth import views as auth_views
from django.urls import path

from . import mfa_views, social_views, views

urlpatterns = [
    path("accounts/social/onboarding/", social_views.onboarding, name="socialaccount_signup"),
    path("accounts/security/connections/", social_views.connections, name="social_connections"),
    path("accounts/security/confirm/", social_views.reauthenticate, name="social_reauthenticate"),
    path("accounts/security/password/set/", social_views.first_password, name="first_password"),
    path("accounts/security/enable-2fa/", social_views.social_enable_mfa, name="social_enable_mfa"),
    path(
        "accounts/security/connections/<int:pk>/disconnect/",
        social_views.disconnect_provider,
        name="social_disconnect",
    ),
    path("", views.landing, name="landing"),
    path("home/", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/switch-role/", views.switch_role, name="switch_role"),
    path(
        "accounts/login/",
        mfa_views.MFALoginView.as_view(),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/security/", mfa_views.security, name="account_security"),
    path("accounts/2fa/reminder/", mfa_views.reminder, name="mfa_reminder"),
    path("accounts/2fa/setup/", mfa_views.setup, name="mfa_setup"),
    path("accounts/2fa/verify/", mfa_views.verify, name="mfa_verify"),
    path("accounts/2fa/recovery/", mfa_views.recovery, name="mfa_recovery"),
    path(
        "accounts/2fa/recovery/generate/", mfa_views.recovery_generate, name="mfa_recovery_generate"
    ),
    path("accounts/2fa/cancel/", mfa_views.cancel, name="mfa_cancel"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("profiles/<int:pk>/", views.profile_detail, name="profile_detail"),
    path("recommendations/", views.recommendations, name="recommendations"),
    path("jobs/", views.jobs, name="jobs"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("employer/jobs/", views.employer_jobs, name="employer_jobs"),
    path("employer/jobs/new/", views.job_form, name="job_create"),
    path("employer/jobs/<int:pk>/edit/", views.job_form, name="job_edit"),
    path("employer/jobs/<int:pk>/toggle/", views.job_toggle, name="job_toggle"),
    path("employer/jobs/<int:pk>/delete/", views.job_delete, name="job_delete"),
    path("employer/jobs/<int:pk>/candidates/", views.candidates, name="job_candidates"),
    path("employer/candidates/", views.candidates, name="candidates"),
    path("how-matching-works/", views.methodology, name="methodology"),
]

for provider in social_views.ADAPTERS:
    urlpatterns += [
        path(
            f"accounts/social/{provider}/login/",
            social_views.provider_start,
            {"provider": provider},
            name=f"{provider}_login",
        ),
        path(
            f"accounts/social/{provider}/login/callback/",
            social_views.provider_callback,
            {"provider": provider},
            name=f"{provider}_callback",
        ),
    ]

# allauth's internal redirects resolve to the existing canonical SkillMatch login.
urlpatterns.append(path("accounts/login/", mfa_views.MFALoginView.as_view(), name="account_login"))
