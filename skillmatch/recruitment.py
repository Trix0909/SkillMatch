"""Recruitment permissions and transactional state changes, shared by every entry point."""

import time
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Account,
    Connection,
    ConnectionActivity,
    EmployerProfile,
    JobPost,
    JobSeekerProfile,
    Message,
    SavedJob,
)


class WorkflowError(ValidationError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def serialized(function):
    @wraps(function)
    def wrapped(user, *args, **kwargs):
        for attempt in range(5):
            try:
                with transaction.atomic():
                    # This first statement acquires SQLite's write reservation BEFORE reads.
                    # select_for_update alone does nothing on SQLite. The user-row lock
                    # also serializes this actor's rolling-limit checks on other databases.
                    get_user_model().objects.filter(pk=user.pk).update(last_login=F("last_login"))
                    return function(user, *args, **kwargs)
            except (OperationalError, IntegrityError) as error:
                locked = isinstance(error, OperationalError) and any(
                    word in str(error).lower() for word in ("locked", "busy", "deadlock")
                )
                duplicate = isinstance(error, IntegrityError) and "unique" in str(error).lower()
                if not locked and not duplicate:
                    raise
                if attempt == 4:
                    raise WorkflowError(
                        "Another update is in progress. Please try again shortly.", 503
                    ) from error
                # Retry the WHOLE transaction, never its remaining statements.
                time.sleep(0.03 * (attempt + 1))

    return wrapped


def require_role(user, role):
    if (
        not user.is_authenticated
        or not get_user_model().objects.filter(pk=user.pk, is_active=True).exists()
    ):
        raise PermissionDenied
    if not Account.objects.filter(user=user, active_role=role).exists():
        raise PermissionDenied
    profile = EmployerProfile if role == "employer" else JobSeekerProfile
    if not profile.objects.filter(user=user).exists():
        raise PermissionDenied
    return role


def participants(user):
    account = getattr(user, "account", None)
    role = account.active_role if account else ""
    if role not in {"seeker", "employer"}:
        raise PermissionDenied
    require_role(user, role)
    query = Q(seeker__user=user) if role == "seeker" else Q(job__employer__user=user)
    return (
        Connection.objects.filter(query)
        .select_related("job__employer__user", "seeker__user")
        .prefetch_related("seeker__skills")
    )


def participant_role(user, connection):
    if user.pk == connection.seeker.user_id:
        return require_role(user, "seeker")
    if user.pk == connection.job.employer.user_id:
        return require_role(user, "employer")
    raise PermissionDenied


def get_connection(user, pk):
    connection = get_object_or_404(
        Connection.objects.select_related("job__employer__user", "seeker__user"), pk=pk
    )
    participant_role(user, connection)
    return connection


def can_view_contact(employer_user, seeker_profile):
    account = getattr(employer_user, "account", None)
    return bool(
        account
        and account.active_role == "employer"
        and employer_user.is_active
        and seeker_profile.user.is_active
        and EmployerProfile.objects.filter(user=employer_user).exists()
        and Connection.objects.filter(
            job__employer__user=employer_user,
            job__employer__user__is_active=True,
            seeker=seeker_profile,
            seeker__user__is_active=True,
            status="accepted",
        ).exists()
    )


def text(value, limit, label, required=False):
    value = (value or "").strip()
    if (required and not value) or len(value) > limit:
        raise WorkflowError(
            f"{label} must contain {'1' if required else '0'}–{limit:,} characters."
        )
    return value


def activity(connection, user, event):
    ConnectionActivity.objects.create(
        connection=connection,
        actor=user,
        event=event,
        stage=connection.stage,
        interview_at=connection.interview_at,
    )


def available(connection):
    if not connection.is_available:
        raise WorkflowError(
            "This action is unavailable while the job is closed or a participant account is inactive."
        )


def locked_connection(user, pk):
    # Shared job lock coordinates actions with job closing/reopening/deletion.
    job_id = get_object_or_404(Connection.objects.only("job_id"), pk=pk).job_id
    JobPost.objects.select_for_update().get(pk=job_id)
    return get_connection(user, pk)


@serialized
def initiate(user, job_pk, seeker_pk=None, note="", role="seeker"):
    require_role(user, role)
    job = get_object_or_404(
        JobPost.objects.select_for_update().select_related("employer__user"), pk=job_pk
    )
    seeker = (
        get_object_or_404(
            JobSeekerProfile.objects.select_related("user").prefetch_related("skills"), pk=seeker_pk
        )
        if role == "employer"
        else get_object_or_404(
            JobSeekerProfile.objects.prefetch_related("skills").select_related("user"), user=user
        )
    )
    if job.employer.user_id == seeker.user_id or (
        role == "employer" and job.employer.user_id != user.pk
    ):
        raise PermissionDenied
    note = text(note, 500, "Introduction")
    existing = Connection.objects.filter(job=job, seeker=seeker).first()
    if existing and (existing.status != "pending" or existing.initiated_by == role):
        return existing, "This request already exists; its current state is shown below."
    if existing:
        # Accepting an incoming request is existing recruitment, not a new application.
        # Deadlines do not pause it; manual closure and inactive accounts still do.
        available(existing)
        existing.status = "accepted"
        existing.responded_at = timezone.now()
        existing.save(update_fields=["status", "responded_at", "updated_at"])
        activity(existing, user, "accepted")
        return (
            existing,
            "The existing incoming request was accepted. Its original introduction is preserved; send any further text in the thread.",
        )
    if not job.accepts_new_applications or not seeker.user.is_active or not seeker.is_complete:
        raise WorkflowError(
            "An active job with an open application deadline, active accounts and a complete seeker profile are required."
        )
    cutoff = timezone.now() - timedelta(hours=24)
    initiated = Connection.objects.filter(initiated_by=role, created_at__gte=cutoff)
    initiated = (
        initiated.filter(seeker__user=user)
        if role == "seeker"
        else initiated.filter(job__employer__user=user)
    )
    if initiated.count() >= settings.CONNECTION_REQUEST_LIMIT:
        raise WorkflowError(
            f"You can send up to {settings.CONNECTION_REQUEST_LIMIT} new requests per workspace in a rolling 24 hours. Please try again later.",
            429,
        )
    connection = Connection.objects.create(job=job, seeker=seeker, initiated_by=role, note=note)
    activity(connection, user, "created")
    return connection, "Application sent." if role == "seeker" else "Invitation sent."


@serialized
def respond(user, pk, action):
    connection = locked_connection(user, pk)
    role = participant_role(user, connection)
    if action not in {"accept", "decline", "withdraw"}:
        raise WorkflowError("Choose a valid response.")
    if action in {"accept", "decline"} and role == connection.initiated_by:
        raise PermissionDenied
    if action == "withdraw":
        if connection.status == "pending" and role != connection.initiated_by:
            raise PermissionDenied
        if connection.status == "accepted" and role != "seeker":
            raise PermissionDenied
        if connection.status not in {"pending", "accepted"}:
            return connection, "This connection is already closed."
        connection.status = "withdrawn"
    else:
        if connection.status != "pending":
            return connection, "This request has already been answered or withdrawn."
        if action == "accept":
            available(connection)
        connection.status = "accepted" if action == "accept" else "declined"
        connection.responded_at = timezone.now()
        if action == "accept":
            connection.stage = "new"
    connection.save(update_fields=["status", "stage", "responded_at", "updated_at"])
    activity(connection, user, connection.status)
    return connection, f"Request {connection.get_status_display().lower()}."


def next_stages(connection):
    forward = {"new": "shortlisted", "shortlisted": "interview", "interview": "offered"}
    if (
        connection.status != "accepted"
        or connection.stage == "not_selected"
        or not connection.is_available
    ):
        return []
    names = (
        ([forward[connection.stage]] if connection.stage in forward else [])
        + (["interview"] if connection.stage == "interview" else [])
        + ["not_selected"]
    )
    return [
        (
            name,
            dict(Connection.STAGES)[name]
            + (" (reschedule)" if name == "interview" and connection.stage == "interview" else ""),
        )
        for name in names
    ]


def stage_snapshot(connection):
    return {
        "connection": connection.pk,
        "stage": connection.stage,
        "interview_at": connection.interview_at.isoformat() if connection.interview_at else None,
    }


@serialized
def set_stage(user, pk, stage, interview_at=None, expected_state=None):
    connection = locked_connection(user, pk)
    if participant_role(user, connection) != "employer":
        raise PermissionDenied
    if connection.status != "accepted":
        raise WorkflowError("Only accepted connections have recruitment stages.")
    available(connection)
    if stage == connection.stage and (
        stage != "interview" or interview_at == connection.interview_at
    ):
        return connection, "This stage is already current."
    if expected_state is not None and expected_state != stage_snapshot(connection):
        raise WorkflowError(
            "Recruitment progress has changed. Review the current stage and try again.", 409
        )
    if stage not in dict(next_stages(connection)):
        raise WorkflowError(
            "Choose the next stage; backward, skipped and terminal transitions are unavailable."
        )
    if stage == "interview":
        if not interview_at or timezone.is_naive(interview_at) or interview_at <= timezone.now():
            raise WorkflowError(
                "Choose a future interview date and time in the displayed timezone."
            )
    event = "rescheduled" if connection.stage == stage == "interview" else "stage"
    connection.stage = stage
    if stage == "interview":
        connection.interview_at = interview_at
    connection.save(update_fields=["stage", "interview_at", "updated_at"])
    activity(connection, user, event)
    return connection, "Recruitment progress updated."


@serialized
def send_message(user, pk, body, submission_key=None):
    connection = locked_connection(user, pk)
    if submission_key:
        previous = Message.objects.filter(submission_key=submission_key).first()
        if previous:
            if previous.sender_id != user.pk or previous.connection_id != connection.pk:
                raise PermissionDenied
            return previous
    if not connection.allows_messages:
        raise WorkflowError("This conversation is read-only in its current state.")
    body = text(body, 2000, "Message", required=True)
    message = Message.objects.create(
        connection=connection,
        sender=user,
        body=body,
        **({"submission_key": submission_key} if submission_key else {}),
    )
    Connection.objects.filter(pk=connection.pk).update(updated_at=timezone.now())
    return message


def message_deadline(message):
    return message.created_at + timedelta(minutes=15)


def owned_message(user, connection, message_pk, *, lock=False):
    participant_role(user, connection)
    queryset = Message.objects.select_for_update() if lock else Message.objects.all()
    message = get_object_or_404(queryset, pk=message_pk, connection=connection)
    if message.sender_id != user.pk:
        raise PermissionDenied
    return message


def message_action_problem(user, connection, message, *, now=None):
    """One eligibility policy for rendering controls and validating locked mutations."""
    participant_role(user, connection)
    if message.connection_id != connection.pk or message.sender_id != user.pk:
        raise PermissionDenied
    if message.unsent_at is not None:
        return "This message was already unsent and cannot be changed."
    if not connection.allows_messages:
        return "This conversation is read-only in its current state."
    if (now if now is not None else timezone.now()) >= message_deadline(message):
        return "The 15-minute window has expired. This message can no longer be edited or unsent."
    return ""


@serialized
def edit_message(user, pk, message_pk, body):
    connection = locked_connection(user, pk)
    message = owned_message(user, connection, message_pk, lock=True)
    now = timezone.now()
    problem = message_action_problem(user, connection, message, now=now)
    if problem:
        raise WorkflowError(problem)
    body = text(body, 2000, "Message", required=True)
    if body != message.body:
        message.body = body
        message.edited_at = now
        message.save(update_fields=["body", "edited_at"])
    return message


@serialized
def unsend_message(user, pk, message_pk):
    connection = locked_connection(user, pk)
    message = owned_message(user, connection, message_pk, lock=True)
    now = timezone.now()
    problem = message_action_problem(user, connection, message, now=now)
    if problem:
        raise WorkflowError(problem)
    message.body = ""
    message.unsent_at = now
    message.edited_at = None
    message.save(update_fields=["body", "unsent_at", "edited_at"])
    return message


_UNCHANGED_DEADLINE = object()


@serialized
def change_job_state(user, pk, action, close_date=_UNCHANGED_DEADLINE):
    require_role(user, "employer")
    job = get_object_or_404(JobPost.objects.select_for_update(), pk=pk, employer__user=user)
    if action not in {"close", "reopen"}:
        raise WorkflowError("Choose Close or Reopen explicitly.")
    fields = ["is_active", "updated_at"]
    if action == "reopen":
        from .job_dates import business_date

        if close_date is not _UNCHANGED_DEADLINE:
            if close_date is not None and close_date < business_date():
                raise WorkflowError(
                    "Choose today or a later deadline, or explicitly choose no deadline."
                )
            job.close_date = close_date
            fields.append("close_date")
        if job.deadline_passed:
            raise WorkflowError(
                "Set a new deadline or explicitly choose no deadline before reopening."
            )
    job.is_active = action == "reopen"
    job.save(update_fields=fields)
    return job


@serialized
def save_job_edit(user, pk, data):
    """Validate against the latest job under the same lock used by workflow mutations."""
    from .forms import JobForm

    require_role(user, "employer")
    job = (
        get_object_or_404(JobPost.objects.select_for_update(), pk=pk, employer__user=user)
        if pk
        else JobPost(employer=user.employer_profile)
    )
    form = JobForm(data, instance=job)
    if form.is_valid():
        form.save()
    return form


@serialized
def save_job_bookmark(user, pk):
    require_role(user, "seeker")
    # Evaluate the runtime deadline after obtaining the mutation lock, even for stale pages.
    job = get_object_or_404(
        JobPost.objects.select_for_update()
        .select_related("employer__user")
        .exclude(employer__user=user),
        pk=pk,
    )
    if not job.accepts_new_applications:
        from django.http import Http404

        raise Http404
    return SavedJob.objects.get_or_create(user=user, job=job)[0]


@serialized
def delete_job(user, pk):
    require_role(user, "employer")
    job = get_object_or_404(JobPost.objects.select_for_update(), pk=pk, employer__user=user)
    job.delete()


def job_states(user, jobs):
    ids = [job.pk for job in jobs]
    return {c.job_id: c for c in participants(user).filter(job_id__in=ids)}


def candidate_states(user, job, candidates):
    if not job:
        return {}
    return {
        c.seeker_id: c
        for c in participants(user).filter(
            job=job, seeker_id__in=[candidate.pk for candidate in candidates]
        )
    }
