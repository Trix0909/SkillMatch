from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import recruitment as workflow
from .connection_forms import CONSENT, IntroductionForm, InvitationForm, MessageForm, StageForm
from .models import ConnectionActivity, JobPost


def shell(request):
    role = getattr(getattr(request.user, "account", None), "active_role", "")
    workflow.require_role(request.user, role)
    return {
        "active": "recruitment_connections",
        "profile": request.user.seeker_profile if role == "seeker" else None,
        "connection_base": "skillmatch/dashboard_base.html"
        if role == "seeker"
        else "skillmatch/employer_base.html",
        "consent": CONSENT,
        "display_timezone": settings.TIME_ZONE,
    }


@login_required
def connections(request):
    context = shell(request)
    queryset = workflow.participants(request.user)
    role = request.user.account.active_role
    job_filter = request.GET.get("job")
    if job_filter:
        if role != "employer":
            raise PermissionDenied
        job = (
            get_object_or_404(JobPost, pk=job_filter, employer__user=request.user)
            if job_filter.isdigit()
            else None
        )
        if job is None:
            raise PermissionDenied
        queryset = queryset.filter(job=job)
        context["selected_job"] = job
    queryset = queryset.annotate(
        unread_messages=Count(
            "messages",
            filter=Q(messages__read_at__isnull=True) & ~Q(messages__sender=request.user),
            distinct=True,
        ),
        unread_updates=Count(
            "activities",
            filter=Q(activities__read_at__isnull=True) & ~Q(activities__actor=request.user),
            distinct=True,
        ),
    )
    context["page_obj"] = Paginator(queryset.order_by("-updated_at", "-pk"), 20).get_page(
        request.GET.get("page")
    )
    context["recent_activity"] = (
        ConnectionActivity.objects.filter(connection__in=queryset)
        .exclude(actor=request.user)
        .select_related("connection__job", "connection__seeker__user")
        .order_by("-created_at", "-pk")[:10]
    )
    context["owned_jobs"] = request.user.employer_profile.jobs.all() if role == "employer" else []
    return render(request, "skillmatch/connections/list.html", context)


def detail_response(request, connection, message_form=None, stage_form=None, status=200):
    context = shell(request)
    role = workflow.participant_role(request.user, connection)
    paginator = Paginator(connection.messages.select_related("sender").all(), 30)
    page = paginator.get_page(request.GET.get("page") or paginator.num_pages)
    displayed = list(page.object_list)
    page.object_list = displayed
    # Freeze the selected IDs before updating receipts: unseen pages/new arrivals stay unread.
    connection.messages.filter(pk__in=[m.pk for m in displayed], read_at__isnull=True).exclude(
        sender=request.user
    ).update(read_at=timezone.now())
    activities = Paginator(connection.activities.select_related("actor"), 20)
    activity_page = activities.get_page(request.GET.get("activity_page") or activities.num_pages)
    events = list(activity_page.object_list)
    activity_page.object_list = events
    connection.activities.filter(
        pk__in=[event.pk for event in events], read_at__isnull=True
    ).exclude(actor=request.user).update(read_at=timezone.now())
    contact = (
        workflow.can_view_contact(request.user, connection.seeker) if role == "employer" else False
    )
    can_accept = (
        connection.status == "pending"
        and connection.initiated_by != role
        and connection.is_available
    )
    progress_form = StageForm(connection=connection, initial={"stage": "interview"})
    context.update(
        connection=connection,
        participant_role=role,
        page_obj=page,
        activity_page=activity_page,
        intro_author=connection.seeker.display_name
        if connection.initiated_by == "seeker"
        else connection.job.employer.company_name,
        can_accept=can_accept,
        can_decline=connection.status == "pending" and connection.initiated_by != role,
        can_withdraw=(connection.status == "pending" and connection.initiated_by == role)
        or (connection.status == "accepted" and role == "seeker"),
        show_seeker_contact=contact,
        show_employer_contact=role == "seeker"
        and connection.status == "accepted"
        and connection.job.employer.user.is_active
        and request.user.is_active,
        message_form=message_form or MessageForm(),
        stage_form=stage_form if stage_form is not None else progress_form,
        progress_token=progress_form.initial["expected_state"],
        progress_actions=dict(workflow.next_stages(connection)) if role == "employer" else {},
        stage_label="Offer made"
        if connection.stage == "offered"
        else connection.get_stage_display(),
        scheduler_open=stage_form is not None and stage_form.data.get("stage") == "interview",
        rejection_open=stage_form is not None and stage_form.data.get("stage") == "not_selected",
        can_set_stage=role == "employer" and bool(workflow.next_stages(connection)),
    )
    response = render(request, "skillmatch/connections/detail.html", context, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def connection_detail(request, pk):
    return detail_response(request, workflow.get_connection(request.user, pk))


def failure(request, error, connection=None):
    messages.error(request, " ".join(error.messages))
    if connection:
        return detail_response(
            request, workflow.get_connection(request.user, connection.pk), status=error.status
        )
    return render(
        request,
        "skillmatch/connections/error.html",
        {**shell(request), "error": " ".join(error.messages)},
        status=error.status,
    )


@login_required
@require_POST
def apply(request, pk):
    workflow.require_role(request.user, "seeker")
    form = IntroductionForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "skillmatch/connections/error.html",
            {**shell(request), "form": form},
            status=400,
        )
    try:
        connection, message = workflow.initiate(request.user, pk, note=form.cleaned_data["note"])
    except workflow.WorkflowError as error:
        return failure(request, error)
    messages.success(request, message)
    return redirect("connection_detail", pk=connection.pk)


@login_required
@require_POST
def invite(request, seeker_pk, job_pk=None):
    workflow.require_role(request.user, "employer")
    jobs = JobPost.objects.filter(employer__user=request.user, is_active=True)
    if job_pk is not None:
        job = get_object_or_404(JobPost, pk=job_pk)
        if job.employer.user_id != request.user.pk:
            raise PermissionDenied
        form = IntroductionForm(request.POST)
    else:
        form = InvitationForm(request.POST, jobs=jobs)
    if not form.is_valid():
        return render(
            request,
            "skillmatch/connections/error.html",
            {**shell(request), "form": form},
            status=400,
        )
    try:
        connection, message = workflow.initiate(
            request.user,
            job_pk or form.cleaned_data["job"].pk,
            seeker_pk=seeker_pk,
            note=form.cleaned_data["note"],
            role="employer",
        )
    except workflow.WorkflowError as error:
        return failure(request, error)
    messages.success(request, message)
    return redirect("connection_detail", pk=connection.pk)


@login_required
@require_POST
def response_action(request, pk, action):
    connection = workflow.get_connection(request.user, pk)
    try:
        connection, message = workflow.respond(request.user, pk, action)
    except workflow.WorkflowError as error:
        return failure(request, error, connection)
    messages.success(request, message)
    return redirect("connection_detail", pk=pk)


@login_required
@require_POST
def stage_action(request, pk):
    connection = workflow.get_connection(request.user, pk)
    if workflow.participant_role(request.user, connection) != "employer":
        raise PermissionDenied
    form = StageForm(request.POST, connection=connection)
    if not form.is_valid():
        return detail_response(request, connection, stage_form=form, status=400)
    try:
        transition = {
            key: value for key, value in form.cleaned_data.items() if key != "confirm_not_selected"
        }
        connection, message = workflow.set_stage(request.user, pk, **transition)
    except workflow.WorkflowError as error:
        return failure(request, error, connection)
    messages.success(request, message)
    return redirect("connection_detail", pk=pk)


@login_required
@require_POST
def message_action(request, pk):
    connection = workflow.get_connection(request.user, pk)
    form = MessageForm(request.POST)
    if not form.is_valid():
        return detail_response(request, connection, message_form=form, status=400)
    try:
        workflow.send_message(request.user, pk, **form.cleaned_data)
    except workflow.WorkflowError as error:
        return failure(request, error, connection)
    return redirect("connection_detail", pk=pk)


def candidate_invitation_context(request, profile):
    """Explicit job selection only: never choose a convenient first job."""
    role = getattr(getattr(request.user, "account", None), "active_role", "")
    if role != "employer" or profile.user_id == request.user.pk:
        return {}
    jobs = JobPost.objects.filter(employer__user=request.user, is_active=True)
    selected = None
    if "job" in request.GET:
        raw = request.GET["job"]
        selected = (
            get_object_or_404(JobPost, pk=raw, employer__user=request.user)
            if raw.isdigit()
            else None
        )
        if selected is None:
            raise PermissionDenied
    existing = workflow.participants(request.user).filter(seeker=profile)
    # Existing pairs have their own response/history link, never a fresh Invite.
    new_jobs = jobs.exclude(connections__seeker=profile)
    return {
        "invitation_form": InvitationForm(
            jobs=new_jobs, initial={"job": selected.pk if selected and selected.is_active else None}
        ),
        "invitation_jobs_available": new_jobs.exists(),
        "candidate_connections": existing,
        "selected_connection": existing.filter(job=selected).first() if selected else None,
        "contact_allowed": workflow.can_view_contact(request.user, profile),
        "consent": CONSENT,
    }
