import unicodedata
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.core.validators import URLValidator, MaxLengthValidator
from django.core.exceptions import ValidationError


def normalize_skill(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split())


CERTIFICATIONS = [('basic', 'Basic'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced'), ('expert', 'Expert')]
EXPERIENCES = [('junior', 'Junior'), ('mid', 'Mid'), ('senior', 'Senior'), ('lead', 'Lead')]


class Account(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='account')
    role = models.CharField(max_length=10, choices=[('seeker', 'Job seeker'), ('employer', 'Employer')])

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(role__in=['seeker', 'employer']), name='valid_account_role')]

    def __str__(self):
        return f'{self.user} ({self.get_role_display()})'


class JobSeekerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='seeker_profile')
    certification_level = models.CharField(max_length=12, choices=CERTIFICATIONS, default='basic')
    experience_level = models.CharField(max_length=8, choices=EXPERIENCES, default='junior')
    bio = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])
    portfolio = models.TextField(blank=True, validators=[MaxLengthValidator(6000)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(certification_level__in=dict(CERTIFICATIONS)), name='valid_profile_cert'),
            models.CheckConstraint(condition=models.Q(experience_level__in=dict(EXPERIENCES)), name='valid_profile_exp'),
        ]

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def is_complete(self):
        return bool(self.bio.strip() and self.portfolio.strip() and self.skills.all())

    @property
    def matching_text(self):
        return ' '.join([*(s.name for s in self.skills.all()), self.bio, self.portfolio])

    def __str__(self):
        return self.display_name


class SkillCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.name


class Skill(models.Model):
    profile = models.ForeignKey(JobSeekerProfile, on_delete=models.CASCADE, related_name='skills')
    name = models.CharField(max_length=80)
    normalized_name = models.CharField(max_length=80, editable=False)
    category = models.ForeignKey(SkillCategory, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['profile', 'normalized_name'], name='unique_profile_skill'),
                       models.UniqueConstraint(Lower('name'), 'profile', name='unique_skill_case_insensitive')]

    def save(self, *args, **kwargs):
        self.name = normalize_skill(self.name)
        self.normalized_name = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class EvidenceLink(models.Model):
    profile = models.ForeignKey(JobSeekerProfile, on_delete=models.CASCADE, related_name='evidence_links')
    url = models.URLField(max_length=500, validators=[URLValidator(schemes=['http', 'https'])])

    def __str__(self):
        return self.url


class EmployerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='employer_profile')
    company_name = models.CharField(max_length=150)
    description = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])

    def __str__(self):
        return self.company_name


class JobPost(models.Model):
    employer = models.ForeignKey(EmployerProfile, on_delete=models.CASCADE, related_name='jobs')
    title = models.CharField(max_length=150)
    description = models.TextField(validators=[MaxLengthValidator(8000)])
    required_skills = models.JSONField(default=list)
    certification_level = models.CharField(max_length=12, choices=CERTIFICATIONS, default='basic')
    experience_level = models.CharField(max_length=8, choices=EXPERIENCES, default='junior')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(condition=models.Q(certification_level__in=dict(CERTIFICATIONS)), name='valid_job_cert'),
            models.CheckConstraint(condition=models.Q(experience_level__in=dict(EXPERIENCES)), name='valid_job_exp'),
        ]

    @property
    def matching_text(self):
        return ' '.join([self.title, self.description, *self.required_skills])

    def clean(self):
        super().clean()
        if not isinstance(self.required_skills, list) or not 1 <= len(self.required_skills) <= 40:
            raise ValidationError({'required_skills': 'Provide a list of 1–40 unique skill names.'})
        normalized = []
        for name in self.required_skills:
            if not isinstance(name, str) or not 1 <= len(normalize_skill(name)) <= 80:
                raise ValidationError({'required_skills': 'Each skill must contain 1–80 characters.'})
            normalized.append(normalize_skill(name))
        if len(set(n.casefold() for n in normalized)) != len(normalized):
            raise ValidationError({'required_skills': 'Required skills must be unique.'})
        self.required_skills = normalized

    def __str__(self):
        return self.title
