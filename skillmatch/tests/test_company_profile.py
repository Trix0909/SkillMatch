from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from skillmatch.forms import EmployerForm
from skillmatch.models import Account, EmployerProfile, JobPost, JobSeekerProfile, Skill


class CompanyProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("company_editor", first_name="Sam", last_name="Otieno")
        Account.objects.create(user=cls.user, active_role="employer")
        cls.company = EmployerProfile.objects.create(
            user=cls.user,
            company_name="Nairobi Test Studio",
            description="We build accessible websites for Kenyan businesses.",
        )
        cls.seeker = JobSeekerProfile.objects.create(
            user=cls.user, bio="Python developer", portfolio="Built a scheduling app"
        )
        Skill.objects.create(profile=cls.seeker, name="Python")
        cls.job = JobPost.objects.create(
            employer=cls.company, title="Developer", description="Build accessible websites"
        )
        JobPost.objects.create(
            employer=cls.company, title="Closed role", description="Testing", is_active=False
        )
        cls.other_user = User.objects.create_user("other_company")
        Account.objects.create(user=cls.other_user, active_role="employer")
        cls.other = EmployerProfile.objects.create(user=cls.other_user, company_name="Other Studio")
        JobPost.objects.create(employer=cls.other, title="Another role", description="Testing")

    def setUp(self):
        self.client.force_login(self.user)

    def test_real_company_identity_fields_previews_and_owned_active_count(self):
        response = self.client.get(reverse("profile_edit"))
        self.assertTemplateUsed(response, "skillmatch/employer_base.html")
        self.assertContains(response, "Shape your <em>company story</em>")
        self.assertEqual(
            set(response.context["form"].fields),
            {
                "company_name",
                "logo",
                "cover_image",
                "tagline",
                "location",
                "company_size",
                "industry",
                "summary",
                "description",
                "workplace_culture",
                "focus_areas",
                "website",
                "linkedin",
                "twitter",
            },
        )
        self.assertEqual(
            response.context["form"]["company_name"].value(), self.company.company_name
        )
        self.assertEqual(response.context["form"]["description"].value(), self.company.description)
        self.assertEqual(response.context["active_job_count"], 1)
        self.assertContains(response, "1 active role", count=2)
        self.assertEqual(response.context["form"].preview["percent"], 22)
        self.assertContains(response, 'aria-valuenow="22"')
        html = response.content.decode()
        identity = html.split('class="sd-account-name"', 1)[1].split("</span>", 1)[0]
        self.assertIn(self.company.company_name, identity)
        self.assertIn("Employer account", identity)
        self.assertNotIn("Sam", identity)
        self.assertContains(response, 'class="profile-avatar"')
        self.assertEqual(response.context["profile_dropdown"]["initial"], "N")
        self.assertContains(response, 'title="Switch to job seeking"')
        self.assertContains(response, 'class="sd-notifications"')
        self.assertContains(response, f'href="{reverse("recruitment_connections")}"')
        self.assertNotContains(response, 'class="sd-notification-count"')

    def test_security_moves_to_account_menu_without_being_removed(self):
        response = self.client.get(reverse("profile_edit"))
        html = response.content.decode()
        main = html.split("<main ", 1)[1].split("</main>", 1)[0]
        self.assertNotIn("Account security", main)
        self.assertNotIn(reverse("account_security"), main)
        self.assertNotIn(reverse("social_connections"), main)
        self.assertContains(response, "View company profile")
        for route in ["account_security", "social_connections"]:
            self.assertContains(response, reverse(route))
            self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)

    def test_save_preserves_redirect_and_updates_only_the_current_company(self):
        response = self.client.post(
            reverse("profile_edit"),
            {
                "company_name": "Updated Studio",
                "description": "A new introduction.",
                "user": self.other_user.pk,
                "pk": self.other.pk,
                "active_role": "seeker",
            },
        )
        self.assertRedirects(response, reverse("employer_jobs"))
        self.company.refresh_from_db()
        self.other.refresh_from_db()
        self.user.account.refresh_from_db()
        self.assertEqual(self.company.company_name, "Updated Studio")
        self.assertEqual(self.company.description, "A new introduction.")
        self.assertEqual(self.other.company_name, "Other Studio")
        self.assertEqual(self.user.account.active_role, "employer")
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.context["form"]["description"].value(), "A new introduction.")
        self.assertContains(response, "Updated Studio")

    def test_invalid_values_remain_bound_and_preview_without_changing_saved_identity(self):
        response = self.client.post(
            reverse("profile_edit"), {"company_name": "", "description": "Unsaved introduction"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("company_name", response.context["form"].errors)
        self.assertContains(response, 'id="id_company_name_error"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertEqual(response.context["form"]["description"].value(), "Unsaved introduction")
        self.assertContains(response, self.company.company_name)
        self.assertEqual(response.context["form"].preview["description"], "Unsaved introduction")
        self.assertContains(response, "Your company")
        self.company.refresh_from_db()
        self.assertEqual(
            self.company.description, "We build accessible websites for Kenyan businesses."
        )

    def test_existing_length_limits_still_apply(self):
        for field, value in [("company_name", "N" * 151), ("description", "D" * 2001)]:
            with self.subTest(field=field):
                data = {"company_name": "Test Studio", "description": "Company introduction"}
                data[field] = value
                response = self.client.post(reverse("profile_edit"), data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

    def test_description_remains_optional_and_empty_preview_is_honest(self):
        self.client.force_login(self.other_user)
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.context["form"].preview["percent"], 11)
        self.assertFalse(
            next(
                check
                for check in response.context["form"].preview["checks"]
                if check["key"] == "description"
            )["complete"]
        )
        self.assertFalse(response.context["form"].fields["description"].required)
        self.assertRedirects(
            self.client.post(
                reverse("profile_edit"), {"company_name": "Other Studio", "description": ""}
            ),
            reverse("employer_jobs"),
        )
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.context["active_job_count"], 0)
        self.assertContains(response, "0 active roles", count=2)
        self.assertContains(response, "Opportunities when you post them")

    def test_csrf_and_authentication_remain_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        data = {"company_name": "CSRF Studio", "description": "Company story"}
        self.assertEqual(client.post(reverse("profile_edit"), data).status_code, 403)
        client.get(reverse("profile_edit"))
        data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        self.assertRedirects(client.post(reverse("profile_edit"), data), reverse("employer_jobs"))
        client.logout()
        self.assertEqual(client.get(reverse("profile_edit")).status_code, 302)

    def test_role_switch_preserves_company_seeker_and_job_data(self):
        self.company.tagline = "Made for local businesses"
        self.company.focus_areas = ["Accessibility", "Community"]
        self.company.save()
        for role, destination in [("seeker", "recommendations"), ("employer", "employer_jobs")]:
            self.assertRedirects(
                self.client.post(reverse("switch_role"), {"active_role": role}),
                reverse(destination),
            )
            response = self.client.get(reverse("profile_edit"))
            if role == "seeker":
                self.assertContains(response, 'id="seeker-profile-form"')
                self.assertNotContains(response, "company-profile.css")
            else:
                self.assertContains(response, 'id="company-profile-form"')
                self.assertNotContains(response, "seeker-profile.css")
        self.company.refresh_from_db()
        self.seeker.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.company.company_name, "Nairobi Test Studio")
        self.assertEqual(self.company.tagline, "Made for local businesses")
        self.assertEqual(self.company.focus_areas, ["Accessibility", "Community"])
        self.assertEqual(self.seeker.bio, "Python developer")
        self.assertEqual(self.seeker.skills.get().name, "Python")
        self.assertEqual(self.job.employer_id, self.company.pk)

    def company_data(self, **overrides):
        return {
            "company_name": "Kijani Studio",
            "tagline": "Useful tools for local businesses.",
            "location": "Kisumu, Kenya",
            "company_size": "11-20",
            "industry": "technology",
            "summary": "An independent software studio.",
            "description": self.company.description,
            "workplace_culture": "We learn together.",
            "focus_areas": "Accessibility\nCommunity\nSustainability",
            "website": "https://example.org",
            "linkedin": "https://www.linkedin.com/company/example",
            "twitter": "https://x.com/example",
            **overrides,
        }

    def test_all_company_fields_save_and_prepopulate_after_reload(self):
        data = self.company_data()
        response = self.client.post(reverse("profile_edit"), data)
        self.assertRedirects(response, reverse("employer_jobs"))
        self.company.refresh_from_db()
        response = self.client.get(reverse("profile_edit"))
        for name, value in data.items():
            with self.subTest(field=name):
                stored = value.splitlines() if name == "focus_areas" else value
                self.assertEqual(getattr(self.company, name), stored)
                self.assertEqual(response.context["form"][name].value(), value)
        preview = response.context["form"].preview
        self.assertEqual(preview["percent"], 100)
        self.assertEqual(preview["company_size"], "11–20 employees")
        self.assertEqual(preview["industry"], "Technology & Software")
        self.assertEqual(len(preview["links"]), 3)
        self.assertEqual(response.context["active_job_count"], 1)

    def test_new_fields_are_optional_and_only_company_name_is_required(self):
        form = EmployerForm(data={"company_name": "Minimal Studio"}, instance=self.company)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            [name for name, field in form.fields.items() if field.required], ["company_name"]
        )
        form.save()
        self.company.refresh_from_db()
        self.assertEqual(self.company.focus_areas, [])
        self.assertEqual(self.company.company_size, "")

    def test_focus_areas_normalize_and_reject_duplicates_or_more_than_three(self):
        cases = [
            "Innovation\n innovation ",
            "Ｔｅｃｈ\nTech",
            "Straße\nSTRASSE",
            "One\nTwo\nThree\nFour",
            "X" * 41,
        ]
        for focus in cases:
            with self.subTest(focus=focus):
                response = self.client.post(
                    reverse("profile_edit"), self.company_data(focus_areas=focus)
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("focus_areas", response.context["form"].errors)
                self.assertEqual(response.context["form"]["focus_areas"].value(), focus)
        form = EmployerForm(
            data=self.company_data(focus_areas="  Local   Growth \n\n Ｔｅｃｈ "),
            instance=self.company,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().focus_areas, ["Local Growth", "Tech"])

    def test_focus_areas_are_also_validated_on_the_model(self):
        for value in [
            "text",
            {"focus": "Technology"},
            [3],
            [""],
            ["A", "a"],
            ["A"] * 4,
            ["X" * 41],
        ]:
            with self.subTest(value=value):
                self.company.focus_areas = value
                with self.assertRaises(ValidationError) as raised:
                    self.company.full_clean()
                self.assertIn("focus_areas", raised.exception.message_dict)

    def test_new_length_limits_and_controlled_choices(self):
        cases = {
            "tagline": "X" * 161,
            "location": "X" * 151,
            "summary": "X" * 301,
            "workplace_culture": "X" * 501,
            "company_size": "unlimited",
            "industry": "invented",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                response = self.client.post(
                    reverse("profile_edit"), self.company_data(**{field: value})
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
        self.company.refresh_from_db()
        self.assertEqual(self.company.tagline, "")
        self.assertEqual(
            self.company.description, "We build accessible websites for Kenyan businesses."
        )

    def test_links_require_valid_http_urls_and_remain_optional(self):
        for field in ["website", "linkedin", "twitter"]:
            for url in [
                "javascript:alert(1)",
                "data:text/html,hello",
                "ftp://example.org/file",
                "https://",
                "not a url",
            ]:
                with self.subTest(field=field, url=url):
                    form = EmployerForm(
                        data=self.company_data(**{field: url}), instance=self.company
                    )
                    self.assertFalse(form.is_valid())
                    self.assertIn(field, form.errors)
                    self.assertNotIn(url, [link["url"] for link in form.preview["links"]])
        form = EmployerForm(
            data=self.company_data(website="example.org", linkedin="", twitter=""),
            instance=self.company,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["website"], "https://example.org")

    def test_completion_uses_nine_essentials_and_does_not_require_social_links(self):
        form = EmployerForm(data=self.company_data(website="", linkedin="", twitter=""))
        self.assertEqual(form.preview["percent"], 100)
        form = EmployerForm(
            data=self.company_data(workplace_culture="", focus_areas="", location="")
        )
        self.assertEqual(form.preview["completed"], 6)
        self.assertEqual(form.preview["percent"], 67)
        checks = {item["key"]: item["complete"] for item in form.preview["checks"]}
        self.assertFalse(checks["location_size"])
        self.assertFalse(checks["workplace_culture"])
        self.assertFalse(checks["focus_areas"])

    def test_preview_guidance_requires_both_parts_of_grouped_information(self):
        form = EmployerForm(data=self.company_data(tagline="", industry=""))
        checks = {item["key"]: item["complete"] for item in form.preview["checks"]}
        self.assertFalse(checks["identity"])
        self.assertFalse(checks["focus_areas"])
        self.assertTrue(checks["summary"])
        self.assertEqual(form.preview["completed"], 7)

    def test_empty_preview_links_to_existing_fields_without_inventing_values(self):
        response = self.client.get(reverse("profile_edit"))
        self.assertContains(response, 'class="cp-pill cp-hiring-pill">Hiring</span>')
        self.assertNotIn("hiring", response.context["form"].fields)
        for field in ["tagline", "location", "company_size", "industry", "summary", "focus_areas"]:
            self.assertContains(response, f'data-cp-fill="{field}"')
            self.assertContains(response, f'href="#id_{field}"')
        self.assertEqual(response.context["form"].preview["percent"], 22)
        self.company.refresh_from_db()
        self.assertEqual(self.company.tagline, "")
        self.assertEqual(self.company.location, "")
        self.assertEqual(self.company.summary, "")

    def test_preview_is_escaped_has_safe_links_and_does_not_persist_unsaved_input(self):
        payload = '<img src=x onerror="alert(1)">'
        response = self.client.post(
            reverse("profile_edit"),
            self.company_data(
                company_name="",
                summary=payload,
                website="javascript:alert(1)",
                tagline=payload,
            ),
        )
        self.assertContains(response, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;")
        self.assertNotContains(response, payload)
        self.assertNotContains(response, 'href="javascript:')
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertContains(response, 'id="company-live-preview"')
        self.assertContains(response, 'aria-modal="true"')
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_name, "Nairobi Test Studio")
        self.assertEqual(self.company.summary, "")
        self.assertEqual(self.company.tagline, "")


class CompanyProfileMigrationTests(TransactionTestCase):
    def test_existing_company_information_survives_additive_migration(self):
        executor = MigrationExecutor(connection)
        previous = [("skillmatch", "0005_saved_candidate")]
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(previous)
            apps = executor.loader.project_state(previous).apps
            user = apps.get_model("auth", "User").objects.create(username="legacy_company")
            company = apps.get_model("skillmatch", "EmployerProfile").objects.create(
                user_id=user.pk,
                company_name="Legacy Kenyan Studio",
                description="Our existing company story.",
            )
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            migrated = EmployerProfile.objects.get(pk=company.pk)
            self.assertEqual(migrated.user_id, user.pk)
            self.assertEqual(migrated.company_name, "Legacy Kenyan Studio")
            self.assertEqual(migrated.description, "Our existing company story.")
            for name in [
                "tagline",
                "location",
                "company_size",
                "industry",
                "summary",
                "workplace_culture",
                "website",
                "linkedin",
                "twitter",
            ]:
                self.assertEqual(getattr(migrated, name), "")
            self.assertEqual(migrated.focus_areas, [])
        finally:
            MigrationExecutor(connection).migrate(latest)
