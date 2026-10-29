import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from skillmatch.models import Account, EmployerProfile, JobSeekerProfile, Skill


class ProfileEditorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "profile_editor", first_name="Njeri", last_name="Otieno"
        )
        Account.objects.create(user=cls.user, active_role="seeker")
        cls.profile = JobSeekerProfile.objects.create(
            user=cls.user,
            bio="I build accessible websites.",
            portfolio="Built a booking website for a local business.",
            certification_level="intermediate",
            experience_level="mid",
        )
        Skill.objects.create(profile=cls.profile, name="HTML")
        cls.profile.evidence_links.create(url="https://example.com/work")
        EmployerProfile.objects.create(user=cls.user, company_name="Test Studio")

    def setUp(self):
        self.client.force_login(self.user)

    def data(self):
        return {
            "first_name": "Njeri Updated",
            "last_name": "Otieno Updated",
            "bio": "I build Python applications for small businesses.",
            "portfolio": "Built an inventory app with Python and SQL.",
            "skills_json": json.dumps(["Python", "SQL"]),
            "certification_level": "advanced",
            "experience_level": "senior",
            "links": "https://example.com/project\nhttps://example.com/portfolio",
        }

    def test_existing_profile_uses_seeker_shell_and_prepopulates_all_fields(self):
        response = self.client.get(reverse("profile_edit"))
        self.assertTemplateUsed(response, "skillmatch/dashboard_base.html")
        self.assertContains(response, "Build your <em>professional profile</em>")
        self.assertContains(response, 'aria-current="page">')
        form = response.context["form"]
        for name, expected in {
            "first_name": "Njeri",
            "last_name": "Otieno",
            "bio": self.profile.bio,
            "portfolio": self.profile.portfolio,
            "certification_level": "intermediate",
            "experience_level": "mid",
            "links": "https://example.com/work",
        }.items():
            self.assertEqual(form[name].value(), expected)
            self.assertContains(response, f'id="id_{name}"', count=1)
        self.assertEqual(json.loads(form["skills_json"].value()), ["HTML"])
        self.assertContains(response, "data-skill-editor", count=1)
        self.assertContains(response, reverse("account_security"))
        self.assertContains(response, reverse("social_connections"))
        self.assertNotContains(response, 'name="location"')
        self.assertNotContains(response, 'name="headline"')

    def test_whole_form_saves_and_prepopulates_on_reload(self):
        data = self.data()
        response = self.client.post(reverse("profile_edit"), data)
        self.assertRedirects(response, reverse("profile_detail", args=[self.profile.pk]))
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.user.first_name, data["first_name"])
        self.assertEqual(self.user.last_name, data["last_name"])
        for field in ["bio", "portfolio", "certification_level", "experience_level"]:
            self.assertEqual(getattr(self.profile, field), data[field])
        self.assertEqual(set(self.profile.skills.values_list("name", flat=True)), {"Python", "SQL"})
        self.assertEqual(
            set(self.profile.evidence_links.values_list("url", flat=True)),
            set(data["links"].splitlines()),
        )
        form = self.client.get(reverse("profile_edit")).context["form"]
        for field in ["first_name", "last_name", "bio", "portfolio"]:
            self.assertEqual(form[field].value(), data[field])

    def test_bound_errors_keep_entered_values_without_saving(self):
        data = self.data()
        data.update(first_name="", certification_level="invented", links="javascript:alert(1)")
        response = self.client.post(reverse("profile_edit"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.context["form"].errors), {"first_name", "certification_level", "links"}
        )
        self.assertContains(response, 'id="id_first_name_error"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, data["bio"])
        self.assertEqual(response.context["form"]["skills_json"].value(), data["skills_json"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, "I build accessible websites.")
        self.assertEqual(self.profile.skills.get().name, "HTML")

    def test_duplicate_skills_and_existing_length_limits_still_reject(self):
        for overrides, field in [
            ({"skills_json": '["Python", " python "]'}, "skills_json"),
            ({"bio": "x" * 2001}, "bio"),
            ({"portfolio": "x" * 6001}, "portfolio"),
        ]:
            with self.subTest(field=field):
                response = self.client.post(reverse("profile_edit"), self.data() | overrides)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)

    def test_csrf_rejects_missing_token_and_accepts_rendered_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(reverse("profile_edit"), self.data()).status_code, 403)
        response = client.get(reverse("profile_edit"))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        response = client.post(
            reverse("profile_edit"),
            self.data() | {"csrfmiddlewaretoken": client.cookies["csrftoken"].value},
        )
        self.assertEqual(response.status_code, 302)

    def test_new_empty_profile_uses_same_form_and_can_be_completed(self):
        user = User.objects.create_user("new_profile", first_name="New", last_name="Seeker")
        Account.objects.create(user=user, active_role="seeker")
        profile = JobSeekerProfile.objects.create(user=user)
        self.client.force_login(user)
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["bio"].value(), "")
        self.assertEqual(json.loads(response.context["form"]["skills_json"].value()), [])
        response = self.client.post(reverse("profile_edit"), self.data())
        self.assertRedirects(response, reverse("profile_detail", args=[profile.pk]))
        profile.refresh_from_db()
        self.assertTrue(profile.is_complete)

    def test_role_round_trip_preserves_profile_and_company_editor(self):
        self.client.post(reverse("profile_edit"), self.data())
        self.assertRedirects(
            self.client.post(reverse("switch_role"), {"active_role": "employer"}),
            reverse("employer_jobs"),
        )
        response = self.client.get(reverse("profile_edit"))
        self.assertContains(response, "Company profile")
        self.assertContains(response, 'name="company_name"')
        self.assertNotContains(response, "seeker-profile.css")
        self.assertNotContains(response, 'id="seeker-profile-form"')
        self.assertRedirects(
            self.client.post(reverse("switch_role"), {"active_role": "seeker"}),
            reverse("recommendations"),
        )
        response = self.client.get(reverse("profile_edit"))
        self.assertEqual(response.context["form"]["bio"].value(), self.data()["bio"])
        self.assertEqual(
            set(json.loads(response.context["form"]["skills_json"].value())), {"Python", "SQL"}
        )
        self.assertEqual(self.profile.evidence_links.count(), 2)
