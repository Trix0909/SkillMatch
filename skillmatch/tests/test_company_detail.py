from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from skillmatch.job_dates import business_date
from skillmatch.models import Account, Connection, EmployerProfile, JobPost, JobSeekerProfile, Skill


class CompanyDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("company_owner", email="private@example.test")
        Account.objects.create(user=cls.owner, active_role="employer")
        cls.company = EmployerProfile.objects.create(
            user=cls.owner,
            company_name="Local Studio",
            tagline="Useful software",
            location="Nairobi",
            summary="Our company summary",
            description="Existing story",
            workplace_culture="Learning together",
            focus_areas=["Community"],
            website="https://example.test/",
            logo="profiles/company.png",
            cover_image="profiles/banner.png",
        )
        cls.user = User.objects.create_user("candidate")
        Account.objects.create(user=cls.user, active_role="seeker")
        cls.profile = JobSeekerProfile.objects.create(
            user=cls.user, bio="My summary", portfolio="My portfolio"
        )
        Skill.objects.create(profile=cls.profile, name="Python")
        cls.job = JobPost.objects.create(
            employer=cls.company,
            title="Developer",
            description="Python",
            required_skills=["Python"],
        )
        JobPost.objects.create(
            employer=cls.company, title="Expired", close_date=business_date() - timedelta(days=1)
        )
        JobPost.objects.create(employer=cls.company, title="Closed", is_active=False)

    def test_saved_company_preview_is_read_only_and_does_not_expose_account_email(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("company_detail", args=[self.company.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "skillmatch/includes/company_preview_card.html")
        for value in (
            "Local Studio",
            "Useful software",
            "Nairobi",
            "Our company summary",
            "Existing story",
            "Learning together",
            "Community",
            "https://example.test/",
            "profiles/company.png",
            "profiles/banner.png",
            "1 active role",
        ):
            self.assertContains(response, value)
        for value in (
            "private@example.test",
            "Edit company logo",
            "Edit company cover image",
            "Save company profile",
            "Add a company tagline",
        ):
            self.assertNotContains(response, value)
        self.client.post(
            reverse("company_detail", args=[self.company.pk]), {"company_name": "Tampered"}
        )
        self.company.refresh_from_db()
        self.assertEqual(self.company.company_name, "Local Studio")

    def test_company_access_requires_seeker_mode_and_active_company(self):
        url = reverse("company_detail", args=[self.company.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.user)
        self.owner.is_active = False
        self.owner.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("company_detail", args=[999999])).status_code, 404)

    def test_company_links_on_all_seeker_opportunity_surfaces(self):
        self.client.force_login(self.user)
        self.client.post(reverse("job_save", args=[self.job.pk]))
        link = reverse("company_detail", args=[self.company.pk])
        for url in (
            reverse("jobs"),
            reverse("recommendations"),
            reverse("saved_jobs"),
            reverse("job_detail", args=[self.job.pk]),
        ):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f'href="{link}"')

    def test_profile_information_precedes_invitation_without_creating_request(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("profile_detail", args=[self.profile.pk]))
        html = response.content.decode()
        for heading in (
            "Professional summary",
            "Project portfolio",
            "Supporting evidence",
            "<h3>Skills</h3>",
        ):
            self.assertLess(html.index(heading), html.index('id="invite"'))
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, reverse("candidate_invite", args=[self.profile.pk]))
        self.assertFalse(Connection.objects.exists())
