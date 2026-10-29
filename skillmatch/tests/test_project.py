import csv
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.evaluation import precision_at_k, rule_relevance, sus_score
from skillmatch.forms import ProfileForm, parse_skills
from skillmatch.matching import CERT_MULTIPLIERS, EXP_MULTIPLIERS, MatchingAlgorithm
from skillmatch.models import Account, EmployerProfile, JobPost, JobSeekerProfile, Skill


class ProjectCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer_user = User.objects.create_user("employer", password="Workplace-Test-832!")
        Account.objects.create(user=cls.employer_user, active_role="employer")
        cls.employer = EmployerProfile.objects.create(
            user=cls.employer_user, company_name="Test SME"
        )
        cls.other_employer_user = User.objects.create_user(
            "other_employer", password="Workplace-Test-832!"
        )
        Account.objects.create(user=cls.other_employer_user, active_role="employer")
        cls.other_employer = EmployerProfile.objects.create(
            user=cls.other_employer_user, company_name="Other SME"
        )
        cls.seeker = User.objects.create_user(
            "seeker", password="Workplace-Test-832!", first_name="Amina", last_name="Kamau"
        )
        Account.objects.create(user=cls.seeker, active_role="seeker")
        cls.profile = JobSeekerProfile.objects.create(
            user=cls.seeker,
            bio="Python Django software developer",
            portfolio="Built Python Django SQL software",
            certification_level="advanced",
            experience_level="senior",
        )
        for name in ["Python", "Django", "SQL"]:
            Skill.objects.create(profile=cls.profile, name=name)
        cls.second_user = User.objects.create_user("second", first_name="Second")
        Account.objects.create(user=cls.second_user, active_role="seeker")
        cls.second = JobSeekerProfile.objects.create(
            user=cls.second_user, bio=cls.profile.bio, portfolio=cls.profile.portfolio
        )
        for name in ["Python", "Django", "SQL"]:
            Skill.objects.create(profile=cls.second, name=name)
        cls.job = JobPost.objects.create(
            employer=cls.employer,
            title="Python developer",
            description="Build Django software with SQL",
            required_skills=["Python", "Django", "SQL"],
            certification_level="intermediate",
            experience_level="mid",
        )
        cls.unrelated = JobPost.objects.create(
            employer=cls.employer,
            title="Carpenter",
            description="Timber joinery furniture",
            required_skills=["Woodwork"],
        )

    def profile_data(self):
        return {
            "first_name": "Amina",
            "last_name": "Kamau",
            "skills_json": json.dumps(["Python", "Django"]),
            "certification_level": "advanced",
            "experience_level": "senior",
            "bio": "I develop Django applications",
            "portfolio": "Built an inventory application",
            "links": "https://example.com/project",
        }

    def test_weighted_formula_and_equal_text_ranking(self):
        results = MatchingAlgorithm().rank_candidates(
            self.job.matching_text, [self.second, self.profile]
        )
        self.assertEqual(results[0].item, self.profile)
        self.assertAlmostEqual(results[0].base, results[1].base)
        self.assertAlmostEqual(results[0].score, results[0].base * 1.6 * 1.5)

    def test_every_multiplier_combination(self):
        engine = MatchingAlgorithm()
        for cert, cert_weight in CERT_MULTIPLIERS.items():
            for exp, exp_weight in EXP_MULTIPLIERS.items():
                self.profile.certification_level = cert
                self.profile.experience_level = exp
                self.assertAlmostEqual(
                    engine.apply_multipliers(0.5, self.profile)[2], 0.5 * cert_weight * exp_weight
                )

    def test_term_repetition_is_capped_before_normalization(self):
        engine = MatchingAlgorithm()
        score_a = engine.compute_similarity("Python Django", ["Python Python Django SQL"])[0]
        score_b = engine.compute_similarity("Python Django", [("Python " * 1000) + "Django SQL"])[0]
        self.assertAlmostEqual(score_a, score_b, places=12)

    def test_empty_stopword_and_unrelated_queries(self):
        engine = MatchingAlgorithm()
        self.assertEqual(engine.compute_similarity("the and", ["or but"]), [0])
        self.assertEqual(engine.compute_similarity("Python", []), [])
        self.assertEqual(engine.compute_similarity("woodwork", ["Python Django"]), [0])

    def test_technical_punctuation_is_preserved(self):
        engine = MatchingAlgorithm()
        self.assertGreater(engine.compute_similarity("C++", ["C++ developer"])[0], 0)
        self.assertEqual(engine.compute_similarity("C++", ["C# developer"])[0], 0)
        self.assertGreater(engine.compute_similarity("Python", ["Python."])[0], 0)
        self.assertGreater(engine.compute_similarity(".NET", [".NET developer"])[0], 0)

    def test_portfolio_and_bio_contribute(self):
        self.profile.bio = "Accounting records"
        self.profile.portfolio = "Timber joinery furniture"
        matches = MatchingAlgorithm().rank_candidates("Timber", [self.profile])
        self.assertGreater(matches[0].base, 0)

    def test_evidence_links_do_not_contribute(self):
        engine = MatchingAlgorithm()
        before = engine.rank_candidates("Python", [self.profile])[0].score
        self.profile.evidence_links.create(url="https://example.com/python/python")
        after = engine.rank_candidates("Python", [self.profile])[0].score
        self.assertEqual(before, after)

    def test_incomplete_and_inactive_profiles_excluded(self):
        self.second.portfolio = ""
        self.profile.user.is_active = False
        self.assertEqual(
            MatchingAlgorithm().rank_candidates("Python", [self.second, self.profile]), []
        )

    def test_reverse_matching_excludes_closed_and_inactive_jobs(self):
        self.job.is_active = False
        results = MatchingAlgorithm().rank_jobs(self.profile, [self.job, self.unrelated])
        self.assertEqual([m.item for m in results], [self.unrelated])
        self.unrelated.employer.user.is_active = False
        self.assertEqual(MatchingAlgorithm().rank_jobs(self.profile, [self.unrelated]), [])

    def test_job_recommendations_keep_order_when_profile_multipliers_change(self):
        engine = MatchingAlgorithm()
        before = engine.rank_jobs(self.profile, [self.job, self.unrelated])
        self.profile.certification_level = "expert"
        after = engine.rank_jobs(self.profile, [self.job, self.unrelated])
        self.assertEqual([m.item.pk for m in before], [m.item.pk for m in after])
        self.assertGreater(after[0].score, before[0].score)

    def test_equal_scores_have_stable_tie_break(self):
        self.profile.certification_level = "basic"
        self.profile.experience_level = "junior"
        matches = MatchingAlgorithm().rank_candidates("Python", [self.second, self.profile])
        self.assertEqual([m.item.pk for m in matches], sorted([self.profile.pk, self.second.pk]))

    def test_skills_are_normalized_and_case_insensitive(self):
        self.assertEqual(parse_skills('["  Data   Analysis  "]'), ["Data Analysis"])
        from django.core.exceptions import ValidationError

        for value in [
            '["Python","python"]',
            '[" Ｐｙｔｈｏｎ ","Python"]',
            "{}",
            "[]",
            "[1]",
            '[""]',
        ]:
            with self.assertRaises(ValidationError):
                parse_skills(value)

    def test_database_rejects_duplicate_skills(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Skill.objects.create(profile=self.profile, name="  PYTHON ")

    def test_database_rejects_invalid_levels(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobSeekerProfile.objects.filter(pk=self.profile.pk).update(
                certification_level="invented"
            )

    def test_profile_save_adds_removes_and_persists_evidence(self):
        data = self.profile_data()
        data["skills_json"] = '["Python","HTML"]'
        form = ProfileForm(data, instance=self.profile)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(
            set(self.profile.skills.values_list("name", flat=True)), {"Python", "HTML"}
        )
        self.assertEqual(self.profile.evidence_links.get().url, "https://example.com/project")

    def test_evidence_disallows_unsafe_schemes(self):
        for url in ["javascript:alert(1)", "file:///etc/passwd", "ftp://example.com/file"]:
            data = self.profile_data()
            data["links"] = url
            form = ProfileForm(data, instance=self.profile)
            self.assertFalse(form.is_valid())
            self.assertIn("links", form.errors)

    def test_registration_creates_selected_role_with_hashed_password(self):
        data = {
            "username": "new_person",
            "first_name": "Test",
            "last_name": "Person",
            "email": "test@example.test",
            "role": "seeker",
            "password1": "New-Account-832#!",
            "password2": "New-Account-832#!",
        }
        response = self.client.post(reverse("register"), data)
        self.assertRedirects(response, reverse("profile_edit"))
        user = User.objects.get(username="new_person")
        self.assertTrue(user.check_password(data["password1"]))
        self.assertEqual(user.account.active_role, "seeker")
        self.assertFalse(user.seeker_profile.is_complete)

    def test_employer_registration_requires_company(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new_employer",
                "first_name": "Test",
                "last_name": "Employer",
                "email": "test@example.test",
                "role": "employer",
                "password1": "New-Account-832#!",
                "password2": "New-Account-832#!",
            },
        )
        self.assertContains(response, "Enter your company name.")
        self.assertFalse(User.objects.filter(username="new_employer").exists())

    def test_registration_cannot_escalate_role(self):
        response = self.client.post(
            reverse("register"),
            {"username": "intruder", "role": "admin", "is_staff": True, "is_superuser": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="intruder").exists())

    def test_anonymous_protected_routes_redirect_to_login(self):
        for name in ["profile_edit", "recommendations", "jobs", "employer_jobs", "candidates"]:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/accounts/login/", response.url)

    def test_seeker_cannot_use_employer_tools_or_read_other_candidates(self):
        self.client.force_login(self.seeker)
        for name in ["employer_jobs", "candidates", "job_create"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("profile_detail", args=[self.second.pk])).status_code, 403
        )

    def test_employer_cannot_edit_close_delete_or_rank_another_employers_job(self):
        self.client.force_login(self.other_employer_user)
        for name in ["job_edit", "job_candidates", "job_delete"]:
            self.assertEqual(self.client.get(reverse(name, args=[self.job.pk])).status_code, 404)
            self.assertEqual(
                self.client.post(reverse(name, args=[self.job.pk]), {}).status_code, 404
            )
        self.assertEqual(
            self.client.post(reverse("job_toggle", args=[self.job.pk])).status_code, 404
        )
        self.assertTrue(JobPost.objects.filter(pk=self.job.pk, is_active=True).exists())

    def test_employer_can_view_complete_candidate_profile(self):
        self.client.force_login(self.employer_user)
        self.assertContains(
            self.client.get(reverse("profile_detail", args=[self.profile.pk])), "Amina Kamau"
        )

    def test_html_profile_content_is_escaped(self):
        self.client.force_login(self.employer_user)
        self.profile.bio = "<script>alert(1)</script>"
        self.profile.save()
        response = self.client.get(reverse("profile_detail", args=[self.profile.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_job_creation_ignores_forged_ownership(self):
        self.client.force_login(self.employer_user)
        response = self.client.post(
            reverse("job_create"),
            {
                "title": "A new job",
                "description": "Python work",
                "skills_json": '["Python"]',
                "certification_level": "basic",
                "experience_level": "junior",
                "employer": self.other_employer.pk,
            },
        )
        job = JobPost.objects.get(title="A new job")
        self.assertEqual(job.employer_id, self.employer.pk)
        self.assertRedirects(response, reverse("job_candidates", args=[job.pk]))

    def test_invalid_job_skill_payload_returns_form_errors(self):
        self.client.force_login(self.employer_user)
        for payload in ["[]", "{}", '["Python", "python"]']:
            response = self.client.post(
                reverse("job_create"),
                {
                    "title": "Invalid skill job",
                    "description": "Python work",
                    "skills_json": payload,
                    "certification_level": "basic",
                    "experience_level": "junior",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("skills_json", response.context["form"].errors)
        self.assertFalse(JobPost.objects.filter(title="Invalid skill job").exists())

    def test_job_lifecycle(self):
        self.client.force_login(self.employer_user)
        self.assertEqual(
            self.client.get(reverse("job_toggle", args=[self.job.pk])).status_code, 405
        )
        self.client.post(reverse("job_toggle", args=[self.job.pk]))
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_active)
        self.client.force_login(self.seeker)
        self.assertNotContains(self.client.get(reverse("jobs")), self.job.title)
        self.assertEqual(
            self.client.get(reverse("job_detail", args=[self.job.pk])).status_code, 403
        )
        self.client.force_login(self.employer_user)
        self.client.get(reverse("job_delete", args=[self.job.pk]))
        self.assertTrue(JobPost.objects.filter(pk=self.job.pk).exists())
        self.client.post(reverse("job_delete", args=[self.job.pk]))
        self.assertFalse(JobPost.objects.filter(pk=self.job.pk).exists())

    def test_post_requires_csrf_and_logout_is_post_only(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employer_user)
        self.assertEqual(client.post(reverse("job_toggle", args=[self.job.pk])).status_code, 403)
        self.assertEqual(client.get(reverse("logout")).status_code, 405)

    def test_login_rejects_external_redirect(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": "seeker",
                "password": "Workplace-Test-832!",
                "next": "https://example.com/evil",
            },
        )
        self.assertRedirects(response, reverse("mfa_reminder"))
        response = self.client.post(reverse("mfa_reminder"), {"action": "later"})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_invalid_search_does_not_run_matching(self):
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("candidates"), {"q": "a" * 8001})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["searched"])

    def test_all_role_pages_render_and_results_paginate(self):
        for user, routes in [
            (self.seeker, ["profile_edit", "recommendations", "jobs", "methodology"]),
            (self.employer_user, ["profile_edit", "employer_jobs", "candidates", "job_create"]),
        ]:
            self.client.force_login(user)
            for name in routes:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        response = self.client.get(reverse("candidates"), {"q": "Python", "page": "invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Why this match?")
        self.client.logout()
        for name in ["landing", "login", "register", "methodology"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_evaluation_relevance_threshold_and_levels(self):
        self.assertTrue(rule_relevance(self.profile, self.job)[1])
        self.assertFalse(rule_relevance(self.second, self.job)[1])
        self.job.required_skills = ["Python", "Django", "SQL", "Git", "Linux"]
        self.assertFalse(rule_relevance(self.profile, self.job)[1])

    def test_seeker_switch_requires_company_then_allows_job_creation(self):
        self.client.force_login(self.seeker)
        response = self.client.post(reverse("switch_role"), {"active_role": "employer"})
        self.assertContains(response, "Company name")
        self.seeker.account.refresh_from_db()
        self.assertEqual(self.seeker.account.active_role, "seeker")
        self.assertFalse(EmployerProfile.objects.filter(user=self.seeker).exists())
        for company_name in ("", "   ", "x" * 151):
            response = self.client.post(
                reverse("switch_role"),
                {"active_role": "employer", "company_name": company_name},
            )
            self.assertIn("company_name", response.context["form"].errors)
            self.assertFalse(EmployerProfile.objects.filter(user=self.seeker).exists())
        response = self.client.post(
            reverse("switch_role"),
            {"active_role": "employer", "company_name": "  Amina Studio  "},
        )
        self.assertRedirects(response, reverse("employer_jobs"))
        employer = EmployerProfile.objects.get(user=self.seeker)
        self.assertEqual(employer.company_name, "Amina Studio")
        self.seeker.account.refresh_from_db()
        self.assertEqual(self.seeker.account.active_role, "employer")
        response = self.client.post(
            reverse("job_create"),
            {
                "title": "Studio developer",
                "description": "Python work",
                "skills_json": '["Python"]',
                "certification_level": "basic",
                "experience_level": "junior",
            },
        )
        job = JobPost.objects.get(title="Studio developer")
        self.assertEqual(job.employer, employer)
        self.assertRedirects(response, reverse("job_candidates", args=[job.pk]))

    def test_employer_switch_creates_empty_seeker_and_opens_profile_edit(self):
        self.client.force_login(self.employer_user)
        response = self.client.post(reverse("switch_role"), {"active_role": "seeker"})
        self.assertRedirects(response, reverse("profile_edit"))
        profile = JobSeekerProfile.objects.get(user=self.employer_user)
        self.assertEqual(profile.bio, "")
        self.assertEqual(profile.portfolio, "")
        self.assertFalse(profile.skills.exists())
        self.assertFalse(profile.evidence_links.exists())
        self.employer_user.account.refresh_from_db()
        self.assertEqual(self.employer_user.account.active_role, "seeker")
        self.assertRedirects(self.client.get(reverse("home")), reverse("recommendations"))

    def test_switching_preserves_both_profiles_skills_evidence_and_jobs(self):
        employer = EmployerProfile.objects.create(
            user=self.seeker, company_name="Amina Studio", description="Existing business"
        )
        self.profile.evidence_links.create(url="https://example.test/portfolio")
        JobPost.objects.create(
            employer=employer,
            title="Existing job",
            description="Python",
            required_skills=["Python"],
        )

        def snapshot():
            return (
                list(JobSeekerProfile.objects.filter(user=self.seeker).values()),
                list(EmployerProfile.objects.filter(user=self.seeker).values()),
                list(self.profile.skills.values()),
                list(self.profile.evidence_links.values()),
                list(employer.jobs.values()),
            )

        before = snapshot()
        self.client.force_login(self.seeker)
        for target, destination in [
            ("employer", "employer_jobs"),
            ("employer", "employer_jobs"),
            ("seeker", "recommendations"),
            ("employer", "employer_jobs"),
            ("seeker", "recommendations"),
        ]:
            response = self.client.post(
                reverse("switch_role"),
                {"active_role": target, "company_name": "Must not overwrite"},
            )
            self.assertRedirects(response, reverse(destination))
            self.assertEqual(snapshot(), before)
            self.assertRedirects(self.client.get(reverse("home")), reverse(destination))
            response = self.client.get(reverse("profile_edit"))
            self.assertEqual(response.context["seeker"], target == "seeker")

    def test_dual_profile_access_follows_active_role(self):
        EmployerProfile.objects.create(user=self.seeker, company_name="Amina Studio")
        self.client.force_login(self.seeker)
        for target, denied, allowed in [
            ("seeker", ["employer_jobs", "candidates", "job_create"], ["recommendations", "jobs"]),
            (
                "employer",
                ["recommendations", "jobs"],
                ["employer_jobs", "candidates", "job_create"],
            ),
        ]:
            self.client.post(reverse("switch_role"), {"active_role": target})
            for name in denied:
                self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
            for name in allowed:
                self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
            self.assertEqual(
                self.client.get(reverse("profile_detail", args=[self.second.pk])).status_code,
                200 if target == "employer" else 403,
            )
            self.assertEqual(
                self.client.get(reverse("job_detail", args=[self.job.pk])).status_code,
                200 if target == "seeker" else 403,
            )

    def test_missing_matching_profile_denies_role_access(self):
        self.client.force_login(self.employer_user)
        self.employer.delete()
        for name in ["employer_jobs", "candidates", "job_create", "profile_edit"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("profile_detail", args=[self.profile.pk])).status_code, 403
        )
        self.client.force_login(self.seeker)
        self.profile.delete()
        for name in ["recommendations", "jobs", "profile_edit"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_recommendations_exclude_own_jobs(self):
        employer = EmployerProfile.objects.create(user=self.seeker, company_name="Amina Studio")
        own_job = JobPost.objects.create(
            employer=employer,
            title="Own Python job",
            description="Python",
            required_skills=["Python"],
        )
        self.client.force_login(self.seeker)
        response = self.client.get(reverse("recommendations"))
        ids = [match.item.pk for match in response.context["page_obj"]]
        self.assertNotIn(own_job.pk, ids)
        self.assertIn(self.job.pk, ids)

    def test_candidates_exclude_job_owner_but_include_other_users_in_employer_mode(self):
        owner_profile = JobSeekerProfile.objects.create(
            user=self.employer_user, bio="Python", portfolio="Python project"
        )
        Skill.objects.create(profile=owner_profile, name="Python")
        EmployerProfile.objects.create(user=self.seeker, company_name="Amina Studio")
        Account.objects.filter(user=self.seeker).update(active_role="employer")
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("job_candidates", args=[self.job.pk]))
        ids = [match.item.pk for match in response.context["page_obj"]]
        self.assertNotIn(owner_profile.pk, ids)
        self.assertIn(self.profile.pk, ids)
        response = self.client.get(reverse("candidates"), {"q": "Python"})
        self.assertIn(self.profile.pk, [match.item.pk for match in response.context["page_obj"]])
        self.assertEqual(
            self.client.get(reverse("profile_detail", args=[self.profile.pk])).status_code, 200
        )

    def test_switch_requires_post_csrf_and_valid_account_role(self):
        self.client.force_login(self.seeker)
        self.assertEqual(self.client.get(reverse("switch_role")).status_code, 405)
        for target in ("admin", "", "staff"):
            self.assertEqual(
                self.client.post(reverse("switch_role"), {"active_role": target}).status_code, 403
            )
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.seeker)
        self.assertEqual(
            csrf_client.post(reverse("switch_role"), {"active_role": "employer"}).status_code, 403
        )
        self.seeker.account.refresh_from_db()
        self.assertEqual(self.seeker.account.active_role, "seeker")
        self.client.logout()
        self.assertEqual(
            self.client.post(reverse("switch_role"), {"active_role": "employer"}).status_code, 302
        )
        user = User.objects.create_user("no_account")
        self.client.force_login(user)
        self.assertEqual(
            self.client.post(reverse("switch_role"), {"active_role": "seeker"}).status_code, 403
        )

    def test_switch_cannot_bypass_required_mfa(self):
        TOTPDevice.objects.create(user=self.seeker, confirmed=True)
        self.client.force_login(self.seeker)
        response = self.client.post(
            reverse("switch_role"), {"active_role": "employer", "company_name": "Not allowed"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EmployerProfile.objects.filter(user=self.seeker).exists())
        self.seeker.account.refresh_from_db()
        self.assertEqual(self.seeker.account.active_role, "seeker")
        admin_user = User.objects.create_superuser("switch_admin", password="Admin-Test-832!")
        Account.objects.create(user=admin_user, active_role="seeker")
        JobSeekerProfile.objects.create(user=admin_user)
        self.client.force_login(admin_user)
        response = self.client.post(
            reverse("switch_role"), {"active_role": "employer", "company_name": "Not allowed"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(EmployerProfile.objects.filter(user=admin_user).exists())

    def test_valid_registration_ignores_privilege_fields(self):
        for role in ("seeker", "employer"):
            self.client.logout()
            response = self.client.post(
                reverse("register"),
                {
                    "username": "safe_" + role,
                    "first_name": "Test",
                    "last_name": "Person",
                    "email": "safe@example.test",
                    "role": role,
                    "company_name": "Test business",
                    "password1": "New-Account-832#!",
                    "password2": "New-Account-832#!",
                    "active_role": "admin",
                    "is_staff": True,
                    "is_superuser": True,
                },
            )
            self.assertRedirects(response, reverse("profile_edit"))
            user = User.objects.get(username="safe_" + role)
            self.assertEqual(user.account.active_role, role)
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)

    def test_database_rejects_invalid_active_role(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.filter(user=self.seeker).update(active_role="admin")

    def test_sidebar_switch_label_follows_active_role(self):
        self.client.force_login(self.seeker)
        response = self.client.get(reverse("profile_edit"))
        self.assertContains(response, 'class="workspace-switch"')
        self.assertContains(response, 'value="employer"')
        self.assertContains(response, "Switch to hiring")
        self.client.force_login(self.employer_user)
        response = self.client.get(reverse("profile_edit"))
        self.assertContains(response, 'value="seeker"')
        self.assertContains(response, "Switch to job seeking")

    def test_seed_demo_includes_user_with_both_profiles(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(BASE_DIR=Path(directory).resolve()),
        ):
            call_command("seed_demo", stdout=StringIO())
            user = User.objects.get(username="demo_dual")
            self.assertEqual(user.account.active_role, "seeker")
            self.assertTrue(user.seeker_profile.is_complete)
            self.assertTrue(user.employer_profile.company_name)
            self.assertFalse(user.is_staff)
            self.assertEqual(
                JobSeekerProfile.objects.filter(user__username__startswith="demo_").count(), 31
            )

    def test_precision_denominator_and_sus(self):
        self.assertEqual(precision_at_k([1, 2], {1, 2}, 5), 0.4)
        self.assertEqual(sus_score([5, 1] * 5), 100)
        self.assertEqual(sus_score([1, 5] * 5), 0)
        self.assertEqual(sus_score([3] * 10), 50)
        with self.assertRaises(ValueError):
            sus_score([6] * 10)
        with self.assertRaises(ValueError):
            sus_score([1] * 9)
        with self.assertRaises(ValueError):
            precision_at_k([1, 1], {1}, 5)

    def test_offline_evaluation_requires_manual_labels(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "labels.csv"
            call_command("evaluate_matching", export_labels=path, stdout=StringIO())
            with self.assertRaises(CommandError):
                call_command("evaluate_matching", labels=path, stdout=StringIO())
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                rows = list(reader)
            # Test-only labels; these are deliberately NOT a research study.
            for row in rows:
                row["relevant"] = row["rule_suggestion"]
                row["reviewer"] = "automated unit-test fixture"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            output = StringIO()
            call_command("evaluate_matching", labels=path, stdout=output)
            self.assertIn("P@5", output.getvalue())
            self.assertIn("baseline", output.getvalue())
            self.profile.bio = "Changed after manual review"
            self.profile.save()
            with self.assertRaises(CommandError):
                call_command("evaluate_matching", labels=path, stdout=StringIO())

    def test_sus_csv_rejects_empty_and_duplicate_participants(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sus.csv"
            header = "participant_id," + ",".join(f"q{i}" for i in range(1, 11)) + "\n"
            path.write_text(header, encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("score_sus", path, stdout=StringIO())
            row = "test," + ",".join(["5", "1"] * 5) + "\n"
            path.write_text(header + row, encoding="utf-8")
            output = StringIO()
            call_command("score_sus", path, stdout=output)
            self.assertEqual(json.loads(output.getvalue())["mean_sus"], 100)
            path.write_text(header + row * 2, encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("score_sus", path, stdout=StringIO())


class ActiveRoleMigrationTests(TransactionTestCase):
    def test_role_rename_preserves_values_and_profiles(self):
        previous = ("skillmatch", "0002_mfa_recovery_codes")
        current = ("skillmatch", "0003_account_active_role")
        executor = MigrationExecutor(connection)
        executor.migrate([previous])
        try:
            apps = executor.loader.project_state([previous]).apps
            UserModel = apps.get_model("auth", "User")
            AccountModel = apps.get_model("skillmatch", "Account")
            SeekerModel = apps.get_model("skillmatch", "JobSeekerProfile")
            EmployerModel = apps.get_model("skillmatch", "EmployerProfile")
            user_ids = []
            for role in ("seeker", "employer"):
                user = UserModel.objects.create(username="migration_" + role)
                user_ids.append(user.pk)
                AccountModel.objects.create(user=user, role=role)
                SeekerModel.objects.create(user=user, bio="Keep this profile")
                EmployerModel.objects.create(user=user, company_name="Keep this company")
            executor = MigrationExecutor(connection)
            executor.migrate([current])
            apps = executor.loader.project_state([current]).apps
            accounts = apps.get_model("skillmatch", "Account")
            self.assertEqual(
                list(
                    accounts.objects.filter(user_id__in=user_ids)
                    .order_by("user_id")
                    .values_list("active_role", flat=True)
                ),
                ["seeker", "employer"],
            )
            self.assertEqual(
                apps.get_model("skillmatch", "JobSeekerProfile")
                .objects.filter(user_id__in=user_ids, bio="Keep this profile")
                .count(),
                2,
            )
            self.assertEqual(
                apps.get_model("skillmatch", "EmployerProfile")
                .objects.filter(user_id__in=user_ids, company_name="Keep this company")
                .count(),
                2,
            )
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
