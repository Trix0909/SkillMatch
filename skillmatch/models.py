import hashlib
import re
import unicodedata
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, RegexValidator, URLValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables
from django_otp.models import Device, ThrottlingMixin, TimestampMixin

from .profile_images import profile_image_path


def normalize_skill(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


class RecoveryDevice(TimestampMixin, ThrottlingMixin, Device):
    """Hashed recovery tokens using django-otp's device/session/throttle contract."""

    authenticator = models.OneToOneField(
        "otp_totp.TOTPDevice", on_delete=models.CASCADE, related_name="recovery_device"
    )

    def get_throttle_factor(self):
        return 1

    @staticmethod
    @sensitive_variables()
    def token_digest(token):
        # 128 random bits make a fast one-way hash appropriate; no password or
        # low-entropy PIN is stored here. Separators/case are presentation only.
        normalized = token.strip().replace("-", "").lower()
        if not re.fullmatch(r"[0-9a-f]{32}", normalized):
            return None
        return hashlib.sha256(normalized.encode("ascii")).hexdigest()

    @sensitive_variables()
    def verify_token(self, token):
        # Callers must lock the user/device inside a transaction, as required by
        # django-otp for stateful verification. Failure counters must commit.
        if not self.verify_is_allowed()[0]:
            return False
        if not self.confirmed or not self.authenticator.confirmed:
            return False
        if self.authenticator.user_id != self.user_id:
            return False
        digest = self.token_digest(token)
        match = None
        for code in self.codes.select_for_update():
            if constant_time_compare(code.digest, digest or ""):
                match = code
        if match is None or not self.codes.filter(pk=match.pk).delete()[0]:
            self.throttle_increment()
            return False
        self.throttle_reset(commit=False)
        self.set_last_used_timestamp(commit=False)
        self.save()
        return True


class RecoveryCode(models.Model):
    device = models.ForeignKey(RecoveryDevice, on_delete=models.CASCADE, related_name="codes")
    digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["device", "digest"], name="unique_recovery_digest")
        ]


CERTIFICATIONS = [
    ("basic", "Basic"),
    ("intermediate", "Intermediate"),
    ("advanced", "Advanced"),
    ("expert", "Expert"),
]
EXPERIENCES = [("junior", "Junior"), ("mid", "Mid"), ("senior", "Senior"), ("lead", "Lead")]


class Account(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account"
    )
    active_role = models.CharField(
        max_length=10, choices=[("seeker", "Job seeker"), ("employer", "Employer")]
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(active_role__in=["seeker", "employer"]),
                name="valid_account_active_role",
            )
        ]

    def __str__(self):
        return f"{self.user} ({self.get_active_role_display()})"


class JobSeekerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="seeker_profile"
    )
    certification_level = models.CharField(max_length=12, choices=CERTIFICATIONS, default="basic")
    experience_level = models.CharField(max_length=8, choices=EXPERIENCES, default="junior")
    photo = models.ImageField(upload_to=profile_image_path, blank=True, default="")
    bio = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])
    portfolio = models.TextField(blank=True, validators=[MaxLengthValidator(6000)])
    phone = models.CharField(
        max_length=20,
        blank=True,
        default="",
        validators=[
            RegexValidator(
                r"^(?=.*\d)[\d +\-]+$", "Use digits, spaces, + or -, including at least one digit."
            )
        ],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(certification_level__in=dict(CERTIFICATIONS)),
                name="valid_profile_cert",
            ),
            models.CheckConstraint(
                condition=models.Q(experience_level__in=dict(EXPERIENCES)), name="valid_profile_exp"
            ),
        ]

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def is_complete(self):
        return bool(self.bio.strip() and self.portfolio.strip() and self.skills.all())

    @property
    def matching_text(self):
        return " ".join([*(s.name for s in self.skills.all()), self.bio, self.portfolio])

    def __str__(self):
        return self.display_name


class SkillCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.name


class Skill(models.Model):
    profile = models.ForeignKey(JobSeekerProfile, on_delete=models.CASCADE, related_name="skills")
    name = models.CharField(max_length=80)
    normalized_name = models.CharField(max_length=80, editable=False)
    category = models.ForeignKey(SkillCategory, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "normalized_name"], name="unique_profile_skill"
            ),
            models.UniqueConstraint(Lower("name"), "profile", name="unique_skill_case_insensitive"),
        ]

    def save(self, *args, **kwargs):
        self.name = normalize_skill(self.name)
        self.normalized_name = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class EvidenceLink(models.Model):
    profile = models.ForeignKey(
        JobSeekerProfile, on_delete=models.CASCADE, related_name="evidence_links"
    )
    url = models.URLField(max_length=500, validators=[URLValidator(schemes=["http", "https"])])

    def __str__(self):
        return self.url


def clean_company_focus(values):
    """A small, ordered list of company values, without a separate tagging model."""
    if not isinstance(values, list) or len(values) > 3:
        raise ValidationError({"focus_areas": "Add up to 3 focus areas."})
    normalized, seen = [], set()
    for value in values:
        if not isinstance(value, str) or not 1 <= len(normalize_skill(value)) <= 40:
            raise ValidationError({"focus_areas": "Each focus area must contain 1–40 characters."})
        value = normalize_skill(value)
        if value.casefold() in seen:
            raise ValidationError(
                {"focus_areas": "Focus areas must be unique. Remove the duplicate."}
            )
        normalized.append(value)
        seen.add(value.casefold())
    return normalized


class EmployerProfile(models.Model):
    COMPANY_SIZES = [
        ("1-10", "1–10 employees"),
        ("11-20", "11–20 employees"),
        ("21-50", "21–50 employees"),
        ("51-100", "51–100 employees"),
        ("101-250", "101–250 employees"),
        ("251-500", "251–500 employees"),
        ("500+", "500+ employees"),
    ]
    INDUSTRIES = [
        ("technology", "Technology & Software"),
        ("finance", "Financial Services"),
        ("retail", "Retail"),
        ("healthcare", "Healthcare"),
        ("professional_services", "Professional Services"),
        ("education", "Education"),
        ("hospitality", "Hospitality"),
        ("creative_media", "Creative & Media"),
        ("construction", "Construction"),
        ("logistics", "Logistics"),
        ("agriculture", "Agriculture"),
        ("other", "Other"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employer_profile"
    )
    company_name = models.CharField(max_length=150)
    logo = models.ImageField(upload_to=profile_image_path, blank=True, default="")
    cover_image = models.ImageField(upload_to=profile_image_path, blank=True, default="")
    tagline = models.CharField(max_length=160, blank=True, default="")
    location = models.CharField(max_length=150, blank=True, default="")
    company_size = models.CharField(max_length=10, choices=COMPANY_SIZES, blank=True, default="")
    industry = models.CharField(max_length=30, choices=INDUSTRIES, blank=True, default="")
    summary = models.TextField(blank=True, default="", validators=[MaxLengthValidator(300)])
    description = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])
    workplace_culture = models.TextField(
        blank=True, default="", validators=[MaxLengthValidator(500)]
    )
    focus_areas = models.JSONField(default=list, blank=True)
    website = models.URLField(
        max_length=500, blank=True, default="", validators=[URLValidator(schemes=["http", "https"])]
    )
    linkedin = models.URLField(
        max_length=500, blank=True, default="", validators=[URLValidator(schemes=["http", "https"])]
    )
    twitter = models.URLField(
        max_length=500, blank=True, default="", validators=[URLValidator(schemes=["http", "https"])]
    )

    def clean(self):
        super().clean()
        self.focus_areas = clean_company_focus(self.focus_areas)

    def __str__(self):
        return self.company_name


class JobPostQuerySet(models.QuerySet):
    def accepting_applications(self):
        from .job_dates import business_date

        return self.filter(
            models.Q(close_date__isnull=True) | models.Q(close_date__gte=business_date()),
            is_active=True,
            employer__user__is_active=True,
        )


class JobPost(models.Model):
    employer = models.ForeignKey(EmployerProfile, on_delete=models.CASCADE, related_name="jobs")
    title = models.CharField(max_length=150)
    description = models.TextField(validators=[MaxLengthValidator(8000)])
    required_skills = models.JSONField(default=list)
    certification_level = models.CharField(max_length=12, choices=CERTIFICATIONS, default="basic")
    experience_level = models.CharField(max_length=8, choices=EXPERIENCES, default="junior")
    is_active = models.BooleanField(default=True)
    close_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobPostQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(certification_level__in=dict(CERTIFICATIONS)),
                name="valid_job_cert",
            ),
            models.CheckConstraint(
                condition=models.Q(experience_level__in=dict(EXPERIENCES)), name="valid_job_exp"
            ),
        ]

    @property
    def deadline_passed(self):
        from .job_dates import business_date

        return self.close_date is not None and self.close_date < business_date()

    @property
    def accepts_new_applications(self):
        return self.is_active and not self.deadline_passed and self.employer.user.is_active

    @property
    def effective_status(self):
        if not self.is_active:
            return "Closed by employer"
        if self.deadline_passed:
            return "Closed: deadline passed"
        if not self.employer.user.is_active:
            return "Unavailable: employer account inactive"
        return "Open"

    @property
    def matching_text(self):
        return " ".join([self.title, self.description, *self.required_skills])

    def clean(self):
        super().clean()
        if not isinstance(self.required_skills, list) or not 1 <= len(self.required_skills) <= 40:
            raise ValidationError({"required_skills": "Provide a list of 1–40 unique skill names."})
        normalized = []
        for name in self.required_skills:
            if not isinstance(name, str) or not 1 <= len(normalize_skill(name)) <= 80:
                raise ValidationError(
                    {"required_skills": "Each skill must contain 1–80 characters."}
                )
            normalized.append(normalize_skill(name))
        if len(set(n.casefold() for n in normalized)) != len(normalized):
            raise ValidationError({"required_skills": "Required skills must be unique."})
        self.required_skills = normalized

    def __str__(self):
        return self.title


class SavedJob(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_jobs"
    )
    job = models.ForeignKey(JobPost, on_delete=models.CASCADE, related_name="saved_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "job"], name="unique_user_saved_job")
        ]

    def __str__(self):
        return f"{self.user} — {self.job}"


class SavedCandidate(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_candidates"
    )
    candidate = models.ForeignKey(
        JobSeekerProfile, on_delete=models.CASCADE, related_name="saved_by"
    )
    job = models.ForeignKey(
        JobPost, null=True, blank=True, on_delete=models.SET_NULL, related_name="saved_candidates"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "candidate"], name="unique_user_saved_candidate"
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.candidate}"


class Connection(models.Model):
    INITIATORS = [("seeker", "Job seeker"), ("employer", "Employer")]
    STATUSES = [
        (value, value.title()) for value in ("pending", "accepted", "declined", "withdrawn")
    ]
    STAGES = [
        ("new", "New"),
        ("shortlisted", "Shortlisted"),
        ("interview", "Interview"),
        ("offered", "Offered"),
        ("not_selected", "Not selected"),
    ]
    job = models.ForeignKey(JobPost, on_delete=models.PROTECT, related_name="connections")
    seeker = models.ForeignKey(
        JobSeekerProfile, on_delete=models.CASCADE, related_name="connections"
    )
    initiated_by = models.CharField(max_length=8, choices=INITIATORS)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    stage = models.CharField(max_length=12, choices=STAGES, default="new")
    interview_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, validators=[MaxLengthValidator(500)])
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["job", "seeker"], name="unique_job_seeker_connection"),
            models.CheckConstraint(
                condition=models.Q(initiated_by__in=["seeker", "employer"]),
                name="valid_connection_initiator",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "accepted", "declined", "withdrawn"]),
                name="valid_connection_status",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    stage__in=["new", "shortlisted", "interview", "offered", "not_selected"]
                ),
                name="valid_connection_stage",
            ),
        ]
        indexes = [
            models.Index(fields=["seeker", "status", "initiated_by"], name="conn_seeker_pending"),
            models.Index(fields=["job", "status", "initiated_by"], name="conn_job_pending"),
            models.Index(fields=["initiated_by", "created_at"], name="conn_rate_window"),
        ]

    @property
    def is_available(self):
        return (
            self.job.is_active and self.job.employer.user.is_active and self.seeker.user.is_active
        )

    @property
    def list_state(self):
        if self.status in {"declined", "withdrawn"} or self.stage == "not_selected":
            return "Closed"
        if self.status == "pending":
            return "Pending"
        return "Active" if self.is_available else "Paused"

    @property
    def allows_messages(self):
        return self.status == "accepted" and self.stage != "not_selected" and self.is_available

    def __str__(self):
        return f"{self.job} / {self.seeker} ({self.status})"


class Message(models.Model):
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField(validators=[MaxLengthValidator(2000)])
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    unsent_at = models.DateTimeField(null=True, blank=True)
    submission_key = models.UUIDField(default=uuid4, unique=True, editable=False)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(fields=["connection", "read_at", "sender"], name="message_received_unread")
        ]


class ConnectionActivity(models.Model):
    EVENTS = [
        ("created", "Request sent"),
        ("accepted", "Request accepted"),
        ("declined", "Request declined"),
        ("withdrawn", "Connection withdrawn"),
        ("stage", "Stage changed"),
        ("rescheduled", "Interview rescheduled"),
    ]
    connection = models.ForeignKey(Connection, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event = models.CharField(max_length=12, choices=EVENTS)
    stage = models.CharField(max_length=12, blank=True, choices=Connection.STAGES)
    interview_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(fields=["connection", "read_at", "actor"], name="activity_received_unread")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    event__in=[
                        "created",
                        "accepted",
                        "declined",
                        "withdrawn",
                        "stage",
                        "rescheduled",
                    ]
                ),
                name="valid_connection_event",
            )
        ]
