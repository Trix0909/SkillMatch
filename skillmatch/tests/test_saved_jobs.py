from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.models import Account, EmployerProfile, JobPost, JobSeekerProfile, SavedJob, Skill


class SavedJobTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("saved_seeker", first_name="Amina")
        Account.objects.create(user=cls.user, active_role="seeker")
        cls.profile = JobSeekerProfile.objects.create(
            user=cls.user, bio="Python developer", portfolio="Built Python software"
        )
        Skill.objects.create(profile=cls.profile, name="Python")
        cls.employer_user = User.objects.create_user("saved_employer")
        Account.objects.create(user=cls.employer_user, active_role="employer")
        cls.employer = EmployerProfile.objects.create(
            user=cls.employer_user, company_name="Nakuru Digital Studio"
        )
        cls.job = JobPost.objects.create(
            employer=cls.employer,
            title="Python developer",
            description="Build Python software",
            required_skills=["Python"],
        )
        cls.other = User.objects.create_user("other_seeker")
        Account.objects.create(user=cls.other, active_role="seeker")
        JobSeekerProfile.objects.create(user=cls.other)

    def setUp(self):
        self.client.force_login(self.user)
        self.save_url = reverse("job_save", args=[self.job.pk])
        self.unsave_url = reverse("job_unsave", args=[self.job.pk])
        self.list_url = reverse("saved_jobs")

    def test_save_unsave_are_idempotent_and_constraint_prevents_duplicates(self):
        for _ in range(2):
            self.assertRedirects(self.client.post(self.save_url), reverse("recommendations"))
        saved = SavedJob.objects.get(user=self.user, job=self.job)
        self.assertIsNotNone(saved.created_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedJob.objects.create(user=self.user, job=self.job)
        for _ in range(2):
            self.assertRedirects(self.client.post(self.unsave_url), reverse("recommendations"))
        self.assertFalse(SavedJob.objects.filter(user=self.user).exists())

    def test_post_and_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for url in (self.save_url, self.unsave_url):
            self.assertEqual(client.get(url).status_code, 405)
            self.assertEqual(client.post(url).status_code, 403)
        client.get(reverse("recommendations"))
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(self.save_url, {"csrfmiddlewaretoken": token}).status_code, 302
        )
        self.assertTrue(SavedJob.objects.filter(user=self.user, job=self.job).exists())
        self.assertEqual(
            client.post(self.unsave_url, {"csrfmiddlewaretoken": token}).status_code, 302
        )
        self.assertFalse(SavedJob.objects.filter(user=self.user).exists())

    def test_records_are_private_and_request_cannot_select_another_owner(self):
        other_save = SavedJob.objects.create(user=self.other, job=self.job)
        self.assertContains(self.client.get(self.list_url), "No saved jobs yet")
        self.client.post(self.unsave_url, {"user": self.other.pk})
        self.assertTrue(SavedJob.objects.filter(pk=other_save.pk).exists())
        self.client.post(self.save_url, {"user": self.other.pk})
        self.assertEqual(SavedJob.objects.filter(user=self.user).count(), 1)
        self.assertEqual(SavedJob.objects.filter(user=self.other).count(), 1)

    def test_access_requires_signed_in_seeker_mode_and_profile(self):
        for user, expected in [(None, 302), (self.employer_user, 403)]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url, method in [
                (self.list_url, "get"),
                (self.save_url, "post"),
                (self.unsave_url, "post"),
            ]:
                with self.subTest(user=user, url=url):
                    self.assertEqual(getattr(self.client, method)(url).status_code, expected)
        JobSeekerProfile.objects.filter(user=self.other).delete()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.post(self.save_url).status_code, 403)
        self.assertFalse(SavedJob.objects.exists())

    def test_mfa_gate_still_protects_new_routes(self):
        TOTPDevice.objects.create(user=self.user, confirmed=True)
        for url, method in [
            (self.list_url, "get"),
            (self.save_url, "post"),
            (self.unsave_url, "post"),
        ]:
            self.client.force_login(self.user)
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("login") + "?next="))
            self.assertNotIn("_auth_user_id", self.client.session)
            self.assertFalse(SavedJob.objects.exists())

    def test_bookmark_survives_role_switch_and_new_login(self):
        self.client.post(self.save_url)
        saved = SavedJob.objects.get(user=self.user, job=self.job)
        profile_before = (self.profile.bio, self.profile.portfolio)
        response = self.client.post(
            reverse("switch_role"), {"active_role": "employer", "company_name": "Amina Studio"}
        )
        self.assertRedirects(response, reverse("employer_jobs"))
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertTrue(SavedJob.objects.filter(pk=saved.pk).exists())
        self.assertRedirects(
            self.client.post(reverse("switch_role"), {"active_role": "seeker"}),
            reverse("recommendations"),
        )
        self.client.logout()
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.list_url), self.job.title)
        self.profile.refresh_from_db()
        self.assertEqual((self.profile.bio, self.profile.portfolio), profile_before)
        self.assertEqual(self.profile.skills.get().name, "Python")
        saved.refresh_from_db()
        self.assertEqual(saved.user_id, self.user.pk)

    def test_own_closed_missing_and_inactive_employer_jobs_cannot_be_saved(self):
        own_company = EmployerProfile.objects.create(user=self.user, company_name="Own studio")
        own_job = JobPost.objects.create(
            employer=own_company, title="Own role", description="Python", required_skills=["Python"]
        )
        self.assertEqual(self.client.post(reverse("job_save", args=[own_job.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("job_save", args=[999999])).status_code, 404)
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.save_url).status_code, 404)
        self.job.is_active = True
        self.job.save(update_fields=["is_active"])
        self.employer_user.is_active = False
        self.employer_user.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.save_url).status_code, 404)
        self.assertFalse(SavedJob.objects.exists())

    def test_closed_saved_jobs_remain_removable_without_detail_access(self):
        self.client.post(self.save_url)
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertContains(response, "No longer available")
        self.assertNotContains(response, f'href="{reverse("job_detail", args=[self.job.pk])}"')
        self.assertEqual(
            self.client.get(reverse("job_detail", args=[self.job.pk])).status_code, 403
        )
        self.client.post(self.unsave_url, {"next": self.list_url})
        self.assertContains(self.client.get(self.list_url), "No saved jobs yet")

    def test_inactive_employer_saved_job_has_no_detail_link(self):
        self.client.post(self.save_url)
        self.employer_user.is_active = False
        self.employer_user.save(update_fields=["is_active"])
        response = self.client.get(self.list_url)
        self.assertContains(response, "No longer available")
        self.assertNotContains(response, f'href="{reverse("job_detail", args=[self.job.pk])}"')
        self.client.post(self.unsave_url)
        self.assertFalse(SavedJob.objects.exists())

    def test_return_preserves_page_and_anchor_but_rejects_external_urls(self):
        for url in (self.save_url, self.unsave_url):
            for destination in ["/recommendations/?page=2#job-1", "/saved-jobs/?page=2"]:
                response = self.client.post(url, {"next": destination})
                self.assertRedirects(response, destination, fetch_redirect_response=False)
            for destination in [
                "https://example.org/",
                "//example.org/",
                "///example.org/",
                r"/\example.org/",
                "javascript:alert(1)",
                "http://testserver/",
                "not_a_route",
                "#fragment",
            ]:
                response = self.client.post(url, {"next": destination}, secure=True)
                self.assertRedirects(
                    response, reverse("recommendations"), fetch_redirect_response=False
                )

    def test_saved_indicator_is_per_user_without_changing_match_ranking(self):
        def ranked_values(response):
            return [
                (m.item.pk, m.base, m.cert, m.experience, m.score)
                for m in response.context["page_obj"].paginator.object_list
            ]

        before = self.client.get(reverse("recommendations"))
        self.assertContains(before, f'aria-label="Save job: {self.job.title}"')
        SavedJob.objects.create(user=self.other, job=self.job)
        self.assertContains(
            self.client.get(reverse("recommendations")), f'aria-label="Save job: {self.job.title}"'
        )
        self.client.post(self.save_url)
        after = self.client.get(reverse("recommendations"))
        self.assertContains(after, f'aria-label="Remove saved job: {self.job.title}"')
        self.assertEqual(ranked_values(before), ranked_values(after))
        self.client.post(self.unsave_url)
        self.assertEqual(
            ranked_values(before), ranked_values(self.client.get(reverse("recommendations")))
        )

    def test_saved_page_is_newest_first_paginated_and_user_scoped(self):
        bookmarks = []
        for index in range(12):
            job = JobPost.objects.create(
                employer=self.employer,
                title=f"Saved opportunity {index}",
                description="Python",
                required_skills=["Python"],
            )
            bookmarks.append(SavedJob.objects.create(user=self.user, job=job))
        SavedJob.objects.create(user=self.other, job=self.job)
        response = self.client.get(self.list_url)
        self.assertEqual(response.context["page_obj"].paginator.count, 12)
        self.assertEqual(
            [s.pk for s in response.context["page_obj"]], [s.pk for s in reversed(bookmarks[2:])]
        )
        self.assertEqual(len(self.client.get(self.list_url, {"page": 2}).context["page_obj"]), 2)
        self.assertNotContains(response, f'aria-label="Remove saved job: {self.job.title}"')
        self.assertContains(response, 'aria-current="page"')

    def test_job_deletion_cleans_up_bookmarks_without_deleting_other_jobs(self):
        self.client.post(self.save_url)
        another = JobPost.objects.create(
            employer=self.employer, title="Another", description="Python"
        )
        self.job.delete()
        self.assertFalse(SavedJob.objects.exists())
        self.assertTrue(JobPost.objects.filter(pk=another.pk).exists())
        self.assertContains(self.client.get(self.list_url), "No saved jobs yet")
