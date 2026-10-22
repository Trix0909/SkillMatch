from django.contrib.auth import views as auth_views
from django.urls import path

from . import mfa_views, views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("home/", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path(
        "accounts/login/",
        mfa_views.MFALoginView.as_view(),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/security/", mfa_views.security, name="account_security"),
    path("accounts/2fa/setup/", mfa_views.setup, name="mfa_setup"),
    path("accounts/2fa/verify/", mfa_views.verify, name="mfa_verify"),
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
