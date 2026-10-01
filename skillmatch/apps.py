from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class SkillmatchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "skillmatch"


class SkillMatchAdminConfig(AdminConfig):
    default_site = "skillmatch.admin_site.SkillMatchAdminSite"
