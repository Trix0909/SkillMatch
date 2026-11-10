from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from django.contrib import admin
from django_otp.plugins.otp_totp.models import TOTPDevice

from .models import (
    Account,
    Connection,
    ConnectionActivity,
    EmployerProfile,
    EvidenceLink,
    JobPost,
    JobSeekerProfile,
    Message,
    Skill,
    SkillCategory,
)

admin.site.site_header = "SkillMatch administration"
admin.site.site_title = "SkillMatch"
admin.site.index_title = "Manage users and project data"

# Enrollment must verify a code. Do not expose secret editing, manual confirmation,
# or device deletion as an administrative bypass/recovery mechanism.
if admin.site.is_registered(TOTPDevice):
    admin.site.unregister(TOTPDevice)

# Provider identities must be managed through the re-authenticated connection
# flow; credentials come exclusively from environment settings.
for social_model in (SocialAccount, SocialApp, SocialToken, EmailAddress):
    if admin.site.is_registered(social_model):
        admin.site.unregister(social_model)


class SkillInline(admin.TabularInline):
    model = Skill
    extra = 0


class EvidenceInline(admin.TabularInline):
    model = EvidenceLink
    extra = 0


@admin.register(JobSeekerProfile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "certification_level", "experience_level", "updated_at"]
    list_filter = ["certification_level", "experience_level"]
    search_fields = ["user__username", "bio"]
    inlines = [SkillInline, EvidenceInline]


@admin.register(JobPost)
class JobAdmin(admin.ModelAdmin):
    list_display = ["title", "employer", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["title", "description"]


admin.site.register([Account, EmployerProfile, SkillCategory])


class InspectionAdmin(admin.ModelAdmin):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Connection)
class ConnectionAdmin(InspectionAdmin):
    list_display = ["job", "seeker", "initiated_by", "status", "stage", "updated_at"]
    list_filter = ["status", "stage", "initiated_by", "job"]
    search_fields = ["job__title", "job__employer__company_name", "seeker__user__username"]


@admin.register(Message)
class MessageAdmin(InspectionAdmin):
    list_display = ["connection", "sender", "created_at", "read_at"]
    search_fields = ["body", "sender__username", "connection__job__title"]
    list_select_related = ["connection__job", "connection__seeker__user", "sender"]


@admin.register(ConnectionActivity)
class ActivityAdmin(InspectionAdmin):
    list_display = ["connection", "actor", "event", "stage", "created_at"]
    list_filter = ["event", "stage"]
    search_fields = ["connection__job__title", "actor__username"]
    list_select_related = ["connection__job", "connection__seeker__user", "actor"]
