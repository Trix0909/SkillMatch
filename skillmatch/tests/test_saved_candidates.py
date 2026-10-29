from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.matching import MatchingAlgorithm
from skillmatch.models import (
    Account,
    EmployerProfile,
    EvidenceLink,
    JobPost,
    JobSeekerProfile,
    SavedCandidate,
    SavedJob,
    Skill,
)
from skillmatch.views import profiles


class HiringCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer = User.objects.create_user("hiring", first_name="Wanjiku")
        Account.objects.create(user=cls.employer, active_role="employer")
        cls.company = EmployerProfile.objects.create(
            user=cls.employer, company_name="Kisumu Studio"
        )
        cls.own_profile = JobSeekerProfile.objects.create(
            user=cls.employer, bio="Python", portfolio="Python"
        )
        Skill.objects.create(profile=cls.own_profile, name="Python")
        cls.other = User.objects.create_user("other_hiring")
        Account.objects.create(user=cls.other, active_role="employer")
        cls.other_company = EmployerProfile.objects.create(
            user=cls.other, company_name="Other studio"
        )
        cls.job = JobPost.objects.create(
            employer=cls.company,
            title="Python developer",
            description="Python Django",
            required_skills=["Python", "Django"],
        )
        cls.other_job = JobPost.objects.create(
            employer=cls.other_company,
            title="Other job",
            description="Python",
            required_skills=["Python"],
        )
        cls.candidate_user = User.objects.create_user(
            "candidate", first_name="Amina", last_name="Kamau"
        )
        Account.objects.create(user=cls.candidate_user, active_role="seeker")
        cls.candidate = JobSeekerProfile.objects.create(
            user=cls.candidate_user,
            bio="Python Django developer",
            portfolio="Built a Django application",
            certification_level="advanced",
            experience_level="senior",
        )
        Skill.objects.create(profile=cls.candidate, name="Python")
        EvidenceLink.objects.create(profile=cls.candidate, url="https://example.com/project")

    def setUp(self):
        self.client.force_login(self.employer)
        self.save_url = reverse("candidate_save", args=[self.candidate.pk])
        self.unsave_url = reverse("candidate_unsave", args=[self.candidate.pk])
        self.list_url = reverse("saved_candidates")


class SavedCandidateTests(HiringCase):
    def test_save_is_private_persistent_and_idempotent(self):
        for _ in range(2):
            self.assertRedirects(
                self.client.post(self.save_url, {"job": self.job.pk}), self.list_url
            )
        saved = SavedCandidate.objects.get(user=self.employer, candidate=self.candidate)
        self.assertEqual(saved.job, self.job)
        self.assertIsNotNone(saved.created_at)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SavedCandidate.objects.create(user=self.employer, candidate=self.candidate)
        response = self.client.get(self.list_url)
        self.assertContains(response, "Amina Kamau")
        self.assertContains(response, "Saved from:")
        self.assertContains(response, self.job.title)
        self.assertNotContains(response, "% match")
        self.assertContains(response, 'aria-pressed="true"')
        self.client.logout()
        self.client.force_login(self.employer)
        self.assertContains(self.client.get(self.list_url), "Amina Kamau")
        self.client.force_login(self.other)
        self.assertContains(self.client.get(self.list_url), "No saved candidates yet")
        self.client.post(self.unsave_url, {"user": self.employer.pk})
        self.assertTrue(SavedCandidate.objects.filter(pk=saved.pk).exists())

    def test_post_and_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employer)
        for url in [self.save_url, self.unsave_url]:
            self.assertEqual(client.get(url).status_code, 405)
            self.assertEqual(client.post(url).status_code, 403)
        client.get(reverse("employer_jobs"))
        csrf = {"csrfmiddlewaretoken": client.cookies["csrftoken"].value}
        self.assertEqual(client.post(self.save_url, csrf).status_code, 302)
        self.assertTrue(SavedCandidate.objects.filter(user=self.employer).exists())
        self.assertEqual(client.post(self.unsave_url, csrf).status_code, 302)
        self.assertFalse(SavedCandidate.objects.exists())

    def test_access_requires_login_hiring_mode_and_employer_profile(self):
        for user, status in [(None, 302), (self.candidate_user, 403)]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url, method in [
                (self.save_url, "post"),
                (self.unsave_url, "post"),
                (self.list_url, "get"),
            ]:
                self.assertEqual(getattr(self.client, method)(url).status_code, status)
        EmployerProfile.objects.filter(user=self.other).delete()
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.save_url).status_code, 403)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertFalse(SavedCandidate.objects.exists())

    def test_mfa_and_admin_gates_still_apply(self):
        for admin, device in [(False, True), (True, False), (True, True)]:
            with self.subTest(admin=admin, device=device):
                self.employer.is_staff = admin
                self.employer.save(update_fields=["is_staff"])
                TOTPDevice.objects.filter(user=self.employer).delete()
                if device:
                    TOTPDevice.objects.create(user=self.employer, confirmed=True)
                for url, method in [
                    (self.save_url, "post"),
                    (self.unsave_url, "post"),
                    (self.list_url, "get"),
                ]:
                    self.client.force_login(self.employer)
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.url.startswith(reverse("login") + "?next="))
                self.assertFalse(SavedCandidate.objects.exists())

    def test_role_switch_retains_profiles_jobs_and_both_kinds_of_bookmark(self):
        SavedJob.objects.create(user=self.employer, job=self.other_job)
        self.client.post(self.save_url, {"job": self.job.pk})
        self.assertRedirects(
            self.client.post(reverse("switch_role"), {"active_role": "seeker"}),
            reverse("recommendations"),
        )
        self.assertEqual(self.client.post(self.save_url).status_code, 403)
        self.assertEqual(self.client.post(self.unsave_url).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("profile_detail", args=[self.candidate.pk])).status_code, 403
        )
        self.assertRedirects(
            self.client.post(reverse("switch_role"), {"active_role": "employer"}),
            reverse("employer_jobs"),
        )
        self.assertContains(self.client.get(self.list_url), "Amina Kamau")
        self.assertEqual(SavedJob.objects.filter(user=self.employer).count(), 1)
        self.assertTrue(JobPost.objects.filter(pk=self.job.pk, employer=self.company).exists())
        self.own_profile.refresh_from_db()
        self.assertEqual(self.own_profile.bio, "Python")
        self.assertEqual(self.own_profile.skills.get().name, "Python")
        self.candidate_user.account.refresh_from_db()
        self.assertEqual(self.candidate_user.account.active_role, "seeker")
        self.assertEqual(self.candidate.evidence_links.get().url, "https://example.com/project")

    def test_incomplete_inactive_missing_and_own_candidates_are_rejected(self):
        self.assertEqual(
            self.client.post(reverse("candidate_save", args=[self.own_profile.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.post(reverse("candidate_save", args=[999999])).status_code, 404
        )
        self.candidate.bio = ""
        self.candidate.save(update_fields=["bio"])
        self.assertEqual(self.client.post(self.save_url).status_code, 403)
        self.candidate_user.is_active = False
        self.candidate_user.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.save_url).status_code, 404)
        self.assertFalse(SavedCandidate.objects.exists())

    def test_candidate_in_hiring_mode_remains_visible_and_saveable(self):
        self.candidate_user.account.active_role = "employer"
        self.candidate_user.account.save(update_fields=["active_role"])
        EmployerProfile.objects.create(user=self.candidate_user, company_name="Amina studio")
        self.assertEqual(
            self.client.get(reverse("profile_detail", args=[self.candidate.pk])).status_code, 200
        )
        self.assertRedirects(self.client.post(self.save_url), self.list_url)

    def test_origin_job_must_belong_to_employer_and_is_not_overwritten(self):
        for job_id, expected in [
            (self.other_job.pk, 404),
            (999999, 404),
            ("invalid", 403),
            ("9" * 20, 403),
            ("9" * 19, 404),
        ]:
            self.assertEqual(self.client.post(self.save_url, {"job": job_id}).status_code, expected)
        self.client.post(self.save_url, {"job": self.job.pk})
        new_job = JobPost.objects.create(
            employer=self.company, title="Second", description="Python"
        )
        self.client.post(self.save_url, {"job": new_job.pk})
        self.assertEqual(SavedCandidate.objects.get(user=self.employer).job_id, self.job.pk)

    def test_deletion_relations_do_not_break_saved_list(self):
        self.client.post(self.save_url, {"job": self.job.pk})
        self.job.delete()
        saved = SavedCandidate.objects.get(user=self.employer)
        self.assertIsNone(saved.job_id)
        self.assertContains(self.client.get(self.list_url), "Amina Kamau")
        self.candidate.delete()
        self.assertFalse(SavedCandidate.objects.exists())
        self.assertContains(self.client.get(self.list_url), "No saved candidates yet")

    def test_candidate_account_deletion_removes_bookmark(self):
        self.client.post(self.save_url)
        self.candidate_user.delete()
        self.assertFalse(SavedCandidate.objects.exists())
        self.assertEqual(self.client.get(self.list_url).status_code, 200)

    def test_unavailable_saved_candidate_hides_private_content_and_can_be_removed(self):
        for inactive in [False, True]:
            with self.subTest(inactive=inactive):
                SavedCandidate.objects.get_or_create(user=self.employer, candidate=self.candidate)
                if inactive:
                    self.candidate_user.is_active = False
                    self.candidate_user.save(update_fields=["is_active"])
                else:
                    self.candidate.portfolio = ""
                    self.candidate.save(update_fields=["portfolio"])
                response = self.client.get(self.list_url)
                self.assertContains(response, "Candidate unavailable")
                self.assertNotContains(response, "Amina Kamau")
                self.assertNotContains(response, self.candidate.bio)
                self.assertNotContains(
                    response, f'href="{reverse("profile_detail", args=[self.candidate.pk])}"'
                )
                self.client.post(self.unsave_url)
                self.assertFalse(SavedCandidate.objects.exists())

    def test_return_paths_preserve_search_page_but_refuse_external_redirects(self):
        for url in [self.save_url, self.unsave_url]:
            target = reverse("candidates") + "?q=Python&page=2#candidate-1"
            self.assertRedirects(
                self.client.post(url, {"next": target}), target, fetch_redirect_response=False
            )
            for target in [
                "//example.com/",
                "https://example.com/",
                r"/\example.com/",
                "javascript:alert(1)",
                "missing_route",
                "http://testserver/",
            ]:
                response = self.client.post(url, {"next": target}, secure=True)
                self.assertRedirects(response, self.list_url, fetch_redirect_response=False)

    def test_save_controls_on_job_search_and_profile_preserve_scores(self):
        urls = [
            reverse("job_candidates", args=[self.job.pk]),
            reverse("candidates") + "?q=Python",
            reverse("profile_detail", args=[self.candidate.pk]),
        ]

        def ranking(response):
            return [
                (m.item.pk, m.base, m.score, m.cert, m.experience)
                for m in response.context["page_obj"]
            ]

        before = ranking(self.client.get(urls[0]))
        for url in urls:
            self.assertContains(self.client.get(url), 'aria-label="Save candidate: Amina Kamau"')
        self.client.post(self.save_url)
        for url in urls:
            self.assertContains(
                self.client.get(url), 'aria-label="Remove saved candidate: Amina Kamau"'
            )
        self.assertEqual(before, ranking(self.client.get(urls[0])))
        self.assertContains(self.client.get(self.list_url), "Amina Kamau")
        self.client.post(self.unsave_url)
        self.assertContains(self.client.get(self.list_url), "No saved candidates yet")

    def test_saved_list_is_paginated_and_newest_first(self):
        bookmarks = []
        for index in range(11):
            user = User.objects.create_user(f"candidate_{index}")
            candidate = JobSeekerProfile.objects.create(user=user, bio="Python", portfolio="Python")
            Skill.objects.create(profile=candidate, name="Python")
            bookmarks.append(SavedCandidate.objects.create(user=self.employer, candidate=candidate))
        response = self.client.get(self.list_url)
        self.assertEqual(response.context["page_obj"].paginator.count, 11)
        self.assertEqual(
            [s.pk for s in response.context["page_obj"]], [s.pk for s in reversed(bookmarks[1:])]
        )
        self.assertEqual(len(self.client.get(self.list_url, {"page": 2}).context["page_obj"]), 1)


class EmployerDashboardTests(HiringCase):
    def test_dashboard_uses_existing_job_specific_rankings_and_real_counts(self):
        SavedCandidate.objects.create(user=self.employer, candidate=self.candidate)
        expected = MatchingAlgorithm().rank_candidates(
            self.job.matching_text, profiles().exclude(user=self.employer)
        )
        response = self.client.get(reverse("employer_jobs"))
        self.assertTemplateUsed(response, "skillmatch/employer_dashboard.html")
        self.assertTemplateUsed(response, "skillmatch/dashboard_base.html")
        self.assertEqual(response.context["active_job_count"], 1)
        self.assertEqual(response.context["candidate_match_count"], len(expected))
        self.assertEqual(response.context["saved_candidate_count"], 1)
        self.assertEqual(response.context["match_job"], self.job)
        self.assertEqual(
            [(m.item.pk, m.base, m.score) for m in response.context["top_matches"]],
            [(m.item.pk, m.base, m.score) for m in expected[:3]],
        )
        self.assertNotIn(self.own_profile.pk, [m.item.pk for m in response.context["top_matches"]])
        self.assertContains(response, "Kisumu Studio")
        self.assertNotContains(response, "Total applicants")
        self.assertNotContains(response, "last month")
        self.assertNotContains(response, 'class="account-card"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_recent_jobs_are_owned_and_full_job_management_list_is_preserved(self):
        for i in range(11):
            JobPost.objects.create(employer=self.company, title=f"Role {i}", description="Python")
        response = self.client.get(reverse("employer_jobs"))
        self.assertEqual(len(response.context["recent_jobs"]), 4)
        self.assertTrue(
            all(
                row["job"].employer_id == self.company.pk for row in response.context["recent_jobs"]
            )
        )
        self.assertContains(response, reverse("employer_jobs") + "?view=all")
        response = self.client.get(reverse("employer_jobs"), {"view": "all"})
        self.assertTemplateUsed(response, "skillmatch/employer_jobs.html")
        self.assertEqual(response.context["page_obj"].paginator.count, 12)
        response = self.client.get(reverse("employer_jobs"), {"page": 2})
        self.assertTemplateUsed(response, "skillmatch/employer_jobs.html")
        self.assertEqual(len(response.context["page_obj"]), 2)

    def test_no_jobs_and_no_active_jobs_have_honest_empty_states(self):
        self.job.is_active = False
        self.job.save(update_fields=["is_active"])
        response = self.client.get(reverse("employer_jobs"))
        self.assertEqual(response.context["active_job_count"], 0)
        self.assertEqual(response.context["candidate_match_count"], 0)
        self.assertIsNone(response.context["best_match"])
        self.assertIsNone(response.context["match_job"])
        self.assertContains(response, "Closed")
        self.job.delete()
        self.assertContains(
            self.client.get(reverse("employer_jobs")), "Your first great match starts with a job."
        )

    def test_latest_active_job_context_ignores_other_employers_and_closed_jobs(self):
        JobPost.objects.create(
            employer=self.company, title="Closed newest", description="Python", is_active=False
        )
        response = self.client.get(reverse("employer_jobs"))
        self.assertEqual(response.context["match_job"], self.job)
        self.assertContains(response, self.job.title)
        self.assertNotContains(response, self.other_job.title)

    def test_shared_header_uses_company_profile_and_secure_logout(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employer)
        response = client.get(reverse("employer_jobs"))
        self.assertContains(response, "Employer account")
        self.assertContains(response, reverse("profile_edit"))
        self.assertContains(response, "Hiring")
        self.assertContains(response, "sd-notifications")
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(reverse("logout"), {"csrfmiddlewaretoken": csrf}).status_code, 302
        )
        self.assertNotIn("_auth_user_id", client.session)
