from functools import wraps
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .forms import RegistrationForm, ProfileForm, EmployerForm, JobForm, SearchForm
from .models import JobSeekerProfile, JobPost
from .matching import MatchingAlgorithm


def role_required(role):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            account = getattr(request.user, 'account', None)
            if not account or account.role != role:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def profiles():
    return JobSeekerProfile.objects.filter(user__is_active=True, user__account__role='seeker').select_related('user').prefetch_related('skills', 'evidence_links')


def active_jobs():
    return JobPost.objects.filter(is_active=True, employer__user__is_active=True).select_related('employer__user')


def landing(request):
    if request.user.is_authenticated:
        return redirect('home')
    return render(request, 'skillmatch/landing.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Your account is ready. Complete your profile to get started.')
        return redirect('profile_edit')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def home(request):
    account = getattr(request.user, 'account', None)
    if not account:
        if request.user.is_staff:
            return redirect('admin:index')
        raise PermissionDenied
    return redirect('recommendations' if account.role == 'seeker' else 'employer_jobs')


@login_required
def profile_edit(request):
    account = getattr(request.user, 'account', None)
    if not account:
        raise PermissionDenied
    seeker = account.role == 'seeker'
    profile = request.user.seeker_profile if seeker else request.user.employer_profile
    form_class = ProfileForm if seeker else EmployerForm
    form = form_class(request.POST or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Your profile has been saved.')
        return redirect('profile_detail', pk=profile.pk) if seeker else redirect('employer_jobs')
    return render(request, 'skillmatch/profile_form.html', {'form': form, 'seeker': seeker, 'profile': profile, 'active': 'profile'})


@login_required
def profile_detail(request, pk):
    profile = get_object_or_404(profiles(), pk=pk)
    account = getattr(request.user, 'account', None)
    if profile.user_id != request.user.id and not request.user.is_staff:
        if not account or account.role != 'employer' or not profile.is_complete:
            raise PermissionDenied
    return render(request, 'skillmatch/profile_detail.html', {'profile': profile, 'active': 'profile'})


@role_required('seeker')
def recommendations(request):
    profile = get_object_or_404(profiles(), user=request.user)
    matches = MatchingAlgorithm().rank_jobs(profile, active_jobs())
    page = Paginator(matches, 10).get_page(request.GET.get('page'))
    return render(request, 'skillmatch/recommendations.html', {'profile': profile, 'page_obj': page, 'active': 'recommendations'})


@role_required('seeker')
def jobs(request):
    query = request.GET.get('q', '').strip()[:150]
    queryset = active_jobs()
    if query:
        from django.db.models import Q
        queryset = queryset.filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(required_skills__icontains=query))
    return render(request, 'skillmatch/jobs.html', {'page_obj': Paginator(queryset, 10).get_page(request.GET.get('page')), 'query': query, 'active': 'jobs'})


@login_required
def job_detail(request, pk):
    job = get_object_or_404(JobPost.objects.select_related('employer__user'), pk=pk)
    owner = job.employer.user_id == request.user.pk
    account = getattr(request.user, 'account', None)
    if not owner and not request.user.is_staff and (not account or account.role != 'seeker' or not job.is_active or not job.employer.user.is_active):
        raise PermissionDenied
    return render(request, 'skillmatch/job_detail.html', {'job': job, 'owner': owner, 'active': 'jobs'})


@role_required('employer')
def employer_jobs(request):
    queryset = request.user.employer_profile.jobs.all()
    return render(request, 'skillmatch/employer_jobs.html', {'page_obj': Paginator(queryset, 10).get_page(request.GET.get('page')), 'active': 'jobs'})


@role_required('employer')
def job_form(request, pk=None):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile) if pk else JobPost(employer=request.user.employer_profile)
    form = JobForm(request.POST or None, instance=job)
    if request.method == 'POST' and form.is_valid():
        job = form.save()
        messages.success(request, 'Your job post has been saved.')
        return redirect('job_candidates', pk=job.pk)
    return render(request, 'skillmatch/job_form.html', {'form': form, 'job': job, 'active': 'jobs'})


@role_required('employer')
@require_POST
def job_toggle(request, pk):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile)
    job.is_active = not job.is_active
    job.save(update_fields=['is_active'])
    messages.success(request, 'Job reopened.' if job.is_active else 'Job closed and removed from recommendations.')
    return redirect('employer_jobs')


@role_required('employer')
def job_delete(request, pk):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile)
    if request.method == 'POST':
        job.delete()
        messages.success(request, 'Job post deleted.')
        return redirect('employer_jobs')
    return render(request, 'skillmatch/job_delete.html', {'job': job, 'active': 'jobs'})


@role_required('employer')
def candidates(request, pk=None):
    job = get_object_or_404(JobPost, pk=pk, employer=request.user.employer_profile) if pk else None
    form = SearchForm(request.GET if 'q' in request.GET else None)
    matches = []
    searched = bool(job)
    if job:
        matches = MatchingAlgorithm().rank_candidates(job.matching_text, profiles())
    elif form.is_bound and form.is_valid():
        searched = True
        matches = MatchingAlgorithm().rank_candidates(form.cleaned_data['q'], profiles())
    return render(request, 'skillmatch/candidates.html', {
        'job': job, 'form': form, 'searched': searched,
        'page_obj': Paginator(matches, 10).get_page(request.GET.get('page')),
        'active': 'candidates',
    })


def methodology(request):
    return render(request, 'skillmatch/methodology.html', {'active': 'methodology'})
