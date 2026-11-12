"""Dashboard accuracy, authorization, templates, and native admin regression checks."""

from datetime import datetime
from unittest.mock import patch

from django.contrib import admin
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.models import Account, EmployerProfile, JobPost, JobSeekerProfile, SkillCategory


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AdminDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("dashboard_admin", password="Admin-test-123!")
        cls.staff = User.objects.create_user("limited_staff", is_staff=True)
        cls.dual = User.objects.create_user("dual_role")
        Account.objects.create(user=cls.dual, active_role="seeker")
        cls.seeker = JobSeekerProfile.objects.create(user=cls.dual)
        cls.employer = EmployerProfile.objects.create(user=cls.dual, company_name="Test employer")
        cls.job = JobPost.objects.create(
            employer=cls.employer,
            title="Test job",
            description="Python work",
            required_skills=["Python"],
            is_active=False,
        )
        cls.skill = SkillCategory.objects.create(name="Test category")
        cls.device = TOTPDevice.objects.create(user=cls.admin, confirmed=True)
        cls.staff_device = TOTPDevice.objects.create(user=cls.staff, confirmed=True)

    def sign_in(self, user=None, client=None):
        user, client = user or self.admin, client or self.client
        client.force_login(user)
        session = client.session
        session[DEVICE_ID_SESSION_KEY] = (
            self.device if user == self.admin else self.staff_device
        ).persistent_id
        session.save()

    def setUp(self):
        self.sign_in()

    def test_totals_count_both_profiles_and_all_job_statuses(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["value"] for item in response.context["metrics"]], [3, 1, 1, 1])
        self.assertContains(response, "Platform <em>overview</em>")
        self.assertContains(response, "Your latest admin actions")
        self.assertNotContains(response, "12,486")

    def test_administrator_identity_and_existing_photo(self):
        self.admin.first_name, self.admin.last_name = "Amina", "Kamau"
        self.admin.save()
        JobSeekerProfile.objects.create(user=self.admin, photo="profiles/admin.png")
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.context["admin_display_name"], "Amina Kamau")
        self.assertEqual(response.context["admin_initials"], "AK")
        self.assertEqual(response.context["admin_photo_url"], "/media/profiles/admin.png")

    def test_monthly_history_uses_registration_dates_and_carry_in(self):
        zone = timezone.get_current_timezone()
        frozen = timezone.make_aware(datetime(2026, 11, 11, 12), zone)
        for user, date in (
            (self.admin, datetime(2024, 1, 1)),
            (self.staff, datetime(2026, 6, 15)),
            (self.dual, datetime(2026, 11, 1)),
        ):
            User.objects.filter(pk=user.pk).update(date_joined=timezone.make_aware(date, zone))
        # June in Nairobi, still May in UTC: the report must use local months.
        User.objects.create(
            username="boundary", date_joined=timezone.make_aware(datetime(2026, 6, 1, 0, 30), zone)
        )
        with patch("skillmatch.admin_dashboard.timezone.now", return_value=frozen):
            response = self.client.get(reverse("admin:index"), {"period": "6"})
        points = response.context["growth_chart"]["points"]
        self.assertEqual(len(points), 6)
        self.assertEqual(points[0]["label"], "Jun 2026")
        self.assertEqual([point["total"] for point in points], [3, 3, 3, 3, 3, 4])
        self.assertEqual(points[0]["new"], 2)
        self.assertEqual(points[-1]["new"], 1)
        self.assertContains(response, "seeker and employer growth is unavailable")

    def test_period_validation_and_zero_data_chart(self):
        self.sign_in(self.staff)
        self.staff.user_permissions.add(Permission.objects.get(codename="view_user"))
        with patch.object(
            admin.site._registry[User], "get_queryset", return_value=User.objects.none()
        ):
            response = self.client.get(reverse("admin:index"), {"period": "bad"})
        self.assertEqual(response.context["period"], 12)
        self.assertTrue(all(p["total"] == 0 for p in response.context["growth_chart"]["points"]))

    def test_permission_limited_dashboard_search_and_quick_actions(self):
        self.sign_in(self.staff)
        self.staff.user_permissions.add(Permission.objects.get(codename="view_skillcategory"))
        response = self.client.get(reverse("admin:index"))
        self.assertEqual([item["value"] for item in response.context["metrics"]], [None] * 4)
        self.assertIsNone(response.context["growth_chart"])
        self.assertEqual(
            [item["label"] for item in response.context["quick_actions"]],
            ["Manage skills", "View reports"],
        )
        self.assertNotContains(response, reverse("admin:auth_user_changelist"))
        response = self.client.get(reverse("admin:search"), {"q": "secret"})
        self.assertEqual(len(response.context["destinations"]), 1)
        self.assertContains(response, "Search skill categorys")
        self.assertNotContains(response, reverse("admin:auth_user_changelist"))
        self.assertEqual(self.client.get(reverse("admin:auth_user_changelist")).status_code, 403)
        report = self.client.get(reverse("admin:reports"))
        self.assertTrue(
            all(
                row["users"] is None and row["jobs"] is None
                for row in report.context["report_rows"]
            )
        )

    def test_metrics_use_model_admin_queryset_restrictions(self):
        with patch.object(
            admin.site._registry[User],
            "get_queryset",
            return_value=User.objects.filter(pk=self.dual.pk),
        ):
            response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.context["metrics"][0]["value"], 1)
        self.assertEqual(response.context["growth_chart"]["points"][-1]["total"], 1)

    def log(self, user=None, obj=None):
        obj = obj or self.skill
        return LogEntry.objects.create(
            user=user or self.admin,
            content_type=ContentType.objects.get_for_model(obj),
            object_id=str(obj.pk),
            object_repr=str(obj),
            action_flag=ADDITION,
        )

    def test_activity_is_real_personal_and_object_permission_filtered(self):
        self.log()
        self.log(user=self.staff)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(len(response.context["recent_activity"]), 1)
        self.assertEqual(response.context["recent_activity"][0]["object"], "Test category")
        with patch.object(
            admin.site._registry[SkillCategory],
            "has_view_or_change_permission",
            side_effect=lambda request, obj=None: obj is None,
        ):
            response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.context["recent_activity"], [])
        self.assertContains(response, "A clear start")

    def test_all_new_views_require_staff_mfa(self):
        urls = [reverse(f"admin:{name}") for name in ("index", "reports", "settings", "search")]
        for user in (None, self.dual, self.admin):
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 302)

    def test_protected_data_is_not_cached(self):
        for name in ("index", "reports", "settings", "search"):
            response = self.client.get(reverse(f"admin:{name}"))
            self.assertEqual(response.status_code, 200)
            self.assertIn("no-store", response["Cache-Control"])

    def test_admin_templates_render_for_registered_models(self):
        for model in admin.site._registry:
            opts = model._meta
            prefix = f"admin:{opts.app_label}_{opts.model_name}"
            with self.subTest(model=opts.label):
                response = self.client.get(reverse(prefix + "_changelist"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "admin-skillmatch.css")
                if admin.site._registry[model].has_add_permission(response.wsgi_request):
                    self.assertEqual(self.client.get(reverse(prefix + "_add")).status_code, 200)
        for obj in (
            self.admin,
            self.dual.account,
            self.employer,
            self.seeker,
            self.job,
            self.skill,
        ):
            opts = obj._meta
            for action in ("change", "history", "delete"):
                with self.subTest(model=opts.label, action=action):
                    self.assertEqual(
                        self.client.get(
                            reverse(
                                f"admin:{opts.app_label}_{opts.model_name}_{action}", args=[obj.pk]
                            )
                        ).status_code,
                        200,
                    )
        self.assertEqual(self.client.get(reverse("admin:password_change")).status_code, 200)

    def test_native_create_edit_validation_actions_and_history(self):
        add = reverse("admin:skillmatch_skillcategory_add")
        self.assertContains(self.client.post(add, {"name": ""}), "This field is required")
        response = self.client.post(add, {"name": "Admin category", "_continue": "1"})
        category = SkillCategory.objects.get(name="Admin category")
        change = reverse("admin:skillmatch_skillcategory_change", args=[category.pk])
        self.assertRedirects(response, change)
        self.client.post(change, {"name": "Updated category", "_save": "1"})
        self.assertTrue(
            SkillCategory.objects.filter(pk=category.pk, name="Updated category").exists()
        )
        history = self.client.get(
            reverse("admin:skillmatch_skillcategory_history", args=[category.pk])
        )
        self.assertContains(history, "dashboard_admin")
        listing = reverse("admin:skillmatch_skillcategory_changelist")
        response = self.client.post(
            listing, {"action": "delete_selected", "_selected_action": [category.pk]}
        )
        self.assertContains(response, "Are you sure")
        response = self.client.post(
            listing, {"action": "delete_selected", "_selected_action": [category.pk], "post": "yes"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SkillCategory.objects.filter(pk=category.pk).exists())

    def test_native_search_filter_and_pagination(self):
        for index in range(4):
            SkillCategory.objects.create(name=f"Category {index}")
        with patch.object(admin.site._registry[SkillCategory], "list_per_page", 2):
            response = self.client.get(
                reverse("admin:skillmatch_skillcategory_changelist"), {"p": 2}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context["cl"].result_list), 2)
        response = self.client.get(
            reverse("admin:skillmatch_skillcategory_changelist"), {"q": "Test"}
        )
        self.assertEqual(response.context["cl"].result_count, 1)
        response = self.client.get(
            reverse("admin:skillmatch_jobpost_changelist"), {"is_active__exact": "1"}
        )
        self.assertEqual(response.context["cl"].result_count, 0)

    def test_search_safely_encodes_terms_and_retains_model_permissions(self):
        response = self.client.get(reverse("admin:search"), {"q": '<script>&"'})
        self.assertNotContains(response, '<script>&"')
        self.assertContains(response, "%3Cscript%3E%26%22")

    def test_settings_retains_access_to_groups_accounts_and_inspection_models(self):
        response = self.client.get(reverse("admin:settings"))
        for name in (
            "auth_group",
            "skillmatch_account",
            "skillmatch_connection",
            "skillmatch_message",
            "skillmatch_connectionactivity",
        ):
            self.assertContains(response, reverse(f"admin:{name}_changelist"))

    def test_csrf_logout_and_password_change(self):
        strict = Client(enforce_csrf_checks=True)
        self.sign_in(client=strict)
        strict.get(reverse("admin:index"))
        self.assertEqual(strict.post(reverse("admin:logout")).status_code, 403)
        self.assertEqual(strict.get(reverse("admin:logout")).status_code, 405)
        response = strict.post(
            reverse("admin:logout"), {"csrfmiddlewaretoken": strict.cookies["csrftoken"].value}
        )
        self.assertRedirects(response, reverse("landing"))
        self.assertNotIn("_auth_user_id", strict.session)
        response = self.client.post(
            reverse("admin:password_change"),
            {
                "old_password": "Admin-test-123!",
                "new_password1": "Updated-admin-123!",
                "new_password2": "Updated-admin-123!",
            },
        )
        self.assertRedirects(response, reverse("admin:password_change_done"))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Updated-admin-123!"))

    def test_public_pages_do_not_load_admin_theme(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("landing")), "admin-skillmatch.css")
