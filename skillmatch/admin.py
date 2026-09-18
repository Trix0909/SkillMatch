from django.contrib import admin

from .models import (
    Account,
    EmployerProfile,
    EvidenceLink,
    JobPost,
    JobSeekerProfile,
    Skill,
    SkillCategory,
)

admin.site.site_header = "SkillMatch administration"
admin.site.site_title = "SkillMatch"
admin.site.index_title = "Manage users and project data"


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
