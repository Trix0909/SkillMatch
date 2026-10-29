from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    EmployerForm,
    HiringSwitchForm,
    JobForm,
    ProfileForm,
    RegistrationForm,
    SearchForm,
)
from .matching import MatchingAlgorithm
from .models import Account, EmployerProfile, JobPost, JobSeekerProfile, SavedCandidate, SavedJob


def role_required(role):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            account = getattr(request.user, "account", None)
            profile_name = "seeker_profile" if role == "seeker" else "employer_profile"
            if (
                not account
                or account.active_role != role
                or not hasattr(request.user, profile_name)
            ):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorate


def profiles():
    return (
        JobSeekerProfile.objects.filter(user__is_active=True)
        .select_related("user")
        .prefetch_related("skills", "evidence_links")
    )


def active_jobs():
    return JobPost.objects.filter(is_active=True, employer__user__is_active=True).select_related(
        "employer__user"
    )


def landing(request):
    if request.user.is_authenticated:
        return redirect("home")
    return render(request, "skillmatch/landing.html")


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Your account is ready. Complete your profile to get started.")
        return redirect("profile_edit")
    return render(request, "registration/register.html", {"form": form})


@login_required
def home(request):
    account = getattr(request.user, "account", None)
    if not account:
        if request.user.is_staff:
            return redirect("admin:index")
        raise PermissionDenied
    return redirect("recommendations" if account.active_role == "seeker" else "employer_jobs")


@login_required
@require_POST
@transaction.atomic
def switch_role(request):
    account = Account.objects.select_for_update().filter(user=request.user).first()
    target = request.POST.get("active_role")
    if not account or target not in ("seeker", "employer"):
        raise PermissionDenied
    created = False
    if target == "employer":
        if not EmployerProfile.objects.filter(user=request.user).exists():
            form = HiringSwitchForm(request.POST if "company_name" in request.POST else None)
            if not form.is_bound or not form.is_valid():
                return render(request, "skillmatch/switch_to_hiring.html", {"form": form})
            EmployerProfile.objects.get_or_create(
                user=request.user, defaults={"company_name": form.cleaned_data["company_name"]}
            )
    else:
        _, created = JobSeekerProfile.objects.get_or_create(user=request.user)
    account.active_role = target
    account.save(update_fields=["active_role"])
    if created:
        return redirect("profile_edit")
    return redirect("recommendations" if target == "seeker" else "employer_jobs")


@login_required
def profile_edit(request):
    account = getattr(request.user, "account", None)
    if not account:
        raise PermissionDenied
    seeker = account.active_role == "seeker"
    profile = getattr(request.user, "seeker_profile" if seeker else "employer_profile", None)
    if profile is None:
        raise PermissionDenied
    form_class = ProfileForm if seeker else EmployerForm
    form = form_class(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been saved.")
        return redirect("profile_detail", pk=profile.pk) if seeker else redirect("employer_jobs")
    return render(
        request,
        "skillmatch/profile_form.html",
        {"form": form, "seeker": seeker, "profile": profile, "active": "profile"},
    )


@login_required
def profile_detail(request, pk):
    profile = get_object_or_404(profiles(), pk=pk)
    account = getattr(request.user, "account", None)
    if profile.user_id != request.user.id and not request.user.is_staff:
        if (
            not account
            or account.active_role != "employer"
            or not hasattr(request.user, "employer_profile")
            or not profile.is_complete
        ):
            raise PermissionDenied
    return render(
        request,
        "skillmatch/profile_detail.html",
        {
            "profile": profile,
            "active": "profile",
            "candidate_is_saved": request.user.saved_candidates.filter(candidate=profile).exists()
            if account and account.active_role == "employer"
            else False,
        },
    )


@role_required("seeker")
def recommendations(request):
    profile = get_object_or_404(profiles(), user=request.user)
    matches = MatchingAlgorithm().rank_jobs(
        profile, active_jobs().exclude(employer__user=request.user)
    )
    page = Paginator(matches, 10).get_page(request.GET.get("page"))
    hour = timezone.localtime().hour
    greeting = (
        "Good morning"
        if 5 <= hour < 12
        else "Good afternoon"
        if 12 <= hour < 17
        else "Good evening"
    )
    saved_job_ids = set(
        request.user.saved_jobs.filter(job_id__in=[match.item.pk for match in page]).values_list(
            "job_id", flat=True
        )
    )
    return render(
        request,
        "skillmatch/recommendations.html",
        {
            "profile": profile,
            "page_obj": page,
            "active": "recommendations",
            "greeting": greeting,
            "saved_job_ids": saved_job_ids,
        },
    )


@role_required("seeker")
def saved_jobs(request):
    queryset = request.user.saved_jobs.select_related("job__employer__user")
    return render(
        request,
        "skillmatch/saved_jobs.html",
        {
            "profile": request.user.seeker_profile,
            "page_obj": Paginator(queryset, 10).get_page(request.GET.get("page")),
            "active": "saved_jobs",
        },
    )


def saved_job_return(request):
    destination = request.POST.get("next", "")
    if destination.startswith("/") and url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(destination)
    return redirect("recommendations")


@role_required("seeker")
@require_POST
def job_save(request, pk):
    job = get_object_or_404(active_jobs().exclude(employer__user=request.user), pk=pk)
    SavedJob.objects.get_or_create(user=request.user, job=job)
    return saved_job_return(request)


@role_required("seeker")
@require_POST
def job_unsave(request, pk):
    # A closed or unavailable job can still be removed from this user's bookmarks.
    request.user.saved_jobs.filter(job_id=pk).delete()
    return saved_job_return(request)


@role_required("seeker")
def jobs(request):
    query = request.GET.get("q", "").strip()[:150]
    queryset = active_jobs()
    if query:
        from django.db.models import Q

        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(required_skills__icontains=query)
        )
    return render(
        request,
        "skillmatch/jobs.html",
        {
            "page_obj": Paginator(queryset, 10).get_page(request.GET.get("page")),
            "query": query,
            "active": "jobs",
        },
    )


@login_required
def job_detail(request, pk):
    job = get_object_or_404(JobPost.objects.select_related("employer__user"), pk=pk)
    owner = job.employer.user_id == request.user.pk
    account = getattr(request.user, "account", None)
    if (
        not owner
        and not request.user.is_staff
        and (
            not account
            or account.active_role != "seeker"
            or not hasattr(request.user, "seeker_profile")
            or not job.is_active
            or not job.employer.user.is_active
        )
    ):
        raise PermissionDenied
    return render(
        request, "skillmatch/job_detail.html", {"job": job, "owner": owner, "active": "jobs"}
    )


@role_required("employer")
def employer_jobs(request):
    queryset = request.user.employer_profile.jobs.all()
    # Home and the full job-management list retain the existing employer URL.
    if request.GET.get("view") == "all" or "page" in request.GET:
        return render(
            request,
            "skillmatch/employer_jobs.html",
            {
                "page_obj": Paginator(queryset, 10).get_page(request.GET.get("page")),
                "active": "jobs",
            },
        )
    recent_jobs = list(queryset[:4])
    match_job = queryset.filter(is_active=True).first()
    candidate_pool = list(profiles().exclude(user=request.user))
    engine = MatchingAlgorithm()
    results = {}
    for job in recent_jobs + ([match_job] if match_job else []):
        if job.pk not in results:
            results[job.pk] = engine.rank_candidates(job.matching_text, candidate_pool)
    matches = results.get(match_job.pk, []) if match_job else []
    top_matches = matches[:3]
    return render(
        request,
        "skillmatch/employer_dashboard.html",
        {
            "active": "employer_home",
            "active_job_count": queryset.filter(is_active=True).count(),
            "candidate_match_count": len(matches),
            "best_match": matches[0] if matches else None,
            "match_job": match_job,
            "top_matches": top_matches,
            "recent_jobs": [
                {"job": job, "match_count": len(results[job.pk])} for job in recent_jobs
            ],
            "saved_candidate_count": request.user.saved_candidates.count(),
            "saved_candidate_ids": set(
                request.user.saved_candidates.filter(
                    candidate_id__in=[match.item.pk for match in top_matches]
                ).values_list("candidate_id", flat=True)
            ),
        },
    )


@role_required("employer")
def saved_candidates(request):
    queryset = request.user.saved_candidates.select_related(
        "candidate__user", "job"
    ).prefetch_related("candidate__skills")
    return render(
        request,
        "skillmatch/saved_candidates.html",
        {
            "page_obj": Paginator(queryset, 10).get_page(request.GET.get("page")),
            "active": "saved_candidates",
        },
    )


def saved_candidate_return(request):
    destination = request.POST.get("next", "")
    if destination.startswith("/") and url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(destination)
    return redirect("saved_candidates")


@role_required("employer")
@require_POST
def candidate_save(request, pk):
    candidate = get_object_or_404(profiles().exclude(user=request.user), pk=pk)
    if not candidate.is_complete:
        raise PermissionDenied
    job = None
    job_id = request.POST.get("job")
    if job_id:
        if not job_id.isascii() or not job_id.isdecimal() or len(job_id) > 19:
            raise PermissionDenied
        job = get_object_or_404(JobPost, pk=job_id, employer=request.user.employer_profile)
    SavedCandidate.objects.get_or_create(
        user=request.user, candidate=candidate, defaults={"job": job}
    )
    return saved_candidate_return(request)


@role_required("employer")
@require_POST
def candidate_unsave(request, pk):
    # Removal remains possible if a saved profile is no longer publicly available.
    request.user.saved_candidates.filter(candidate_id=pk).delete()
    return saved_candidate_return(request)


@role_required("employer")
def job_form(request, pk=None):
    job = (
        get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile)
        if pk
        else JobPost(employer=request.user.employer_profile)
    )
    form = JobForm(request.POST or None, instance=job)
    if request.method == "POST" and form.is_valid():
        job = form.save()
        messages.success(request, "Your job post has been saved.")
        return redirect("job_candidates", pk=job.pk)
    return render(request, "skillmatch/job_form.html", {"form": form, "job": job, "active": "jobs"})


@role_required("employer")
@require_POST
def job_toggle(request, pk):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile)
    job.is_active = not job.is_active
    job.save(update_fields=["is_active"])
    messages.success(
        request,
        "Job reopened." if job.is_active else "Job closed and removed from recommendations.",
    )
    return redirect("employer_jobs")


@role_required("employer")
def job_delete(request, pk):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile)
    if request.method == "POST":
        job.delete()
        messages.success(request, "Job post deleted.")
        return redirect("employer_jobs")
    return render(request, "skillmatch/job_delete.html", {"job": job, "active": "jobs"})


@role_required("employer")
def candidates(request, pk=None):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile) if pk else None
    form = SearchForm(request.GET if "q" in request.GET else None)
    matches = []
    searched = bool(job)
    if job:
        matches = MatchingAlgorithm().rank_candidates(
            job.matching_text, profiles().exclude(user=job.employer.user)
        )
    elif form.is_bound and form.is_valid():
        searched = True
        matches = MatchingAlgorithm().rank_candidates(form.cleaned_data["q"], profiles())
    page = Paginator(matches, 10).get_page(request.GET.get("page"))
    return render(
        request,
        "skillmatch/candidates.html",
        {
            "job": job,
            "form": form,
            "searched": searched,
            "page_obj": page,
            "active": "candidates",
            "saved_candidate_ids": set(
                request.user.saved_candidates.filter(
                    candidate_id__in=[match.item.pk for match in page]
                ).values_list("candidate_id", flat=True)
            ),
        },
    )


def methodology(request):
    return render(request, "skillmatch/methodology.html", {"active": "methodology"})
