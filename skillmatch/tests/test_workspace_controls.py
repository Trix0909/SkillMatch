from django.urls import reverse

from skillmatch.models import JobSeekerProfile, Skill
from skillmatch.tests.test_connections import WorkflowCase


class WorkspaceControlTests(WorkflowCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner_profile = JobSeekerProfile.objects.create(
            user=cls.employer, bio="Python", portfolio="Python project"
        )
        Skill.objects.create(profile=cls.owner_profile, name="Python")

    def set_mode(self, role):
        self.employer.account.active_role = role
        self.employer.account.save(update_fields=["active_role"])
        self.client.force_login(self.employer)

    def test_seeker_mode_hides_owner_management_but_cannot_apply_to_own_job(self):
        self.set_mode("seeker")
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertEqual(response.status_code, 200)
        for route in ("job_edit", "job_toggle", "job_candidates"):
            self.assertNotContains(response, reverse(route, args=[self.job.pk]))
        self.assertNotContains(response, 'id="apply"')
        for route in ("job_edit", "job_delete", "job_candidates"):
            self.assertEqual(self.client.get(reverse(route, args=[self.job.pk])).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("job_toggle", args=[self.job.pk]), {"action": "close"}
            ).status_code,
            403,
        )
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_active)

    def test_hiring_mode_keeps_owner_controls_and_hides_seeker_profile_edit(self):
        self.set_mode("employer")
        response = self.client.get(reverse("job_detail", args=[self.job.pk]))
        for route in ("job_edit", "job_toggle", "job_candidates"):
            self.assertContains(response, reverse(route, args=[self.job.pk]))
        profile = self.client.get(reverse("profile_detail", args=[self.owner_profile.pk]))
        self.assertNotContains(profile, "Edit profile")
        self.assertNotContains(profile, reverse("candidate_save", args=[self.owner_profile.pk]))
        self.set_mode("seeker")
        self.assertContains(
            self.client.get(reverse("profile_detail", args=[self.owner_profile.pk])), "Edit profile"
        )

    def test_company_wording_is_appropriate_for_viewer(self):
        self.company.description = "Our work"
        self.company.save(update_fields=["description"])
        self.set_mode("seeker")
        response = self.client.get(reverse("company_detail", args=[self.company.pk]))
        self.assertContains(response, "What the company does")
        self.assertNotContains(response, "What your company does")
        self.set_mode("employer")
        self.assertContains(self.client.get(reverse("profile_edit")), "What your company does")

    def test_apply_filter_precedes_optional_clear_on_both_shared_surfaces(self):
        for role, route, args in (
            ("seeker", "recommendations", []),
            ("employer", "job_candidates", [self.job.pk]),
        ):
            self.set_mode(role)
            for selection in ("", "50"):
                with self.subTest(role=role, selection=selection):
                    html = self.client.get(
                        reverse(route, args=args), {"min_match": selection}
                    ).content.decode()
                    controls = html.split('class="match-filter-controls"', 1)[1].split(
                        'id="minimum-match-help"', 1
                    )[0]
                    self.assertLess(controls.index("</select>"), controls.index("Apply filter"))
                    if selection:
                        self.assertLess(
                            controls.index("Apply filter"), controls.index("Clear filter")
                        )
                    else:
                        self.assertNotIn("Clear filter", controls)
