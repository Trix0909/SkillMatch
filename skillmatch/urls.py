from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("", views.landing, name="landing"),
    path("home/", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            authentication_form=LoginForm, redirect_authenticated_user=True
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
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
