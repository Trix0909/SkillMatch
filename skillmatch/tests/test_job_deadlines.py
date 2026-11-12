from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from skillmatch import recruitment as flow
from skillmatch.admin import JobAdmin
from skillmatch.forms import JobForm, ReopenJobForm
from skillmatch.job_dates import business_date
from skillmatch.matching import MatchingAlgorithm
from skillmatch.models import Connection, JobPost, SavedJob
from skillmatch.tests.test_connections import WorkflowCase

TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 10, tzinfo=UTC)
YESTERDAY = TODAY - timedelta(days=1)
TOMORROW = TODAY + timedelta(days=1)


@override_settings(TIME_ZONE="Africa/Nairobi", USE_TZ=True)
class JobDeadlineTests(WorkflowCase):
    def setUp(self):
        self.clock = patch("skillmatch.job_dates.timezone.now", return_value=NOW).start()
        self.addCleanup(patch.stopall)

    def deadline(self, value, active=True):
        JobPost.objects.filter(pk=self.job.pk).update(close_date=value, is_active=active)
        self.job.refresh_from_db()

    def job_data(self, value=""):
        return {
            "title": "Updated Python job",
            "description": "Python software",
            "skills_json": '["Python"]',
            "certification_level": "basic",
            "experience_level": "junior",
            "close_date": value,
            # Forged/stale state must never override the employer's manual decision.
            "is_active": "True",
        }

    def state_post(self, action, **data):
        self.login(self.employer)
        return self.client.post(
            reverse("job_toggle", args=[self.job.pk]), {"action": action, **data}
        )

    def test_model_and_queryset_agree_for_deadlines_manual_closure_and_inactive_owner(self):
        for value in (None, YESTERDAY, TODAY, TOMORROW):
            for active in (True, False):
                for account_active in (True, False):
                    with self.subTest(value=value, active=active, account_active=account_active):
                        type(self.employer).objects.filter(pk=self.employer.pk).update(
                            is_active=account_active
                        )
                        self.deadline(value, active)
                        expected = active and account_active and (value is None or value >= TODAY)
                        self.assertEqual(self.job.accepts_new_applications, expected)
                        self.assertEqual(
                            JobPost.objects.accepting_applications()
                            .filter(pk=self.job.pk)
                            .exists(),
                            expected,
                        )
                        self.assertEqual(self.job.is_active, active)

    def test_exact_nairobi_midnight_boundary_while_utc_date_is_still_previous_day(self):
        self.deadline(TODAY)
        # A request's activated timezone must not alter the business date.
        with timezone.override("America/New_York"):
            for instant, expected_date, open_now in (
                (datetime(2026, 11, 10, 20, 59, 59, tzinfo=UTC), TODAY, True),
                (datetime(2026, 11, 10, 21, 0, 0, tzinfo=UTC), TOMORROW, False),
            ):
                self.clock.return_value = instant
                self.assertEqual(business_date(), expected_date)
                self.assertEqual(self.job.accepts_new_applications, open_now)
                self.assertEqual(
                    JobPost.objects.accepting_applications().filter(pk=self.job.pk).exists(),
                    open_now,
                )
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_active)  # No read-time state mutation.

    def test_effective_status_admin_and_manual_precedence(self):
        admin = JobAdmin(JobPost, AdminSite())
        for value, active, label in (
            (None, True, "Open"),
            (TODAY, True, "Open"),
            (YESTERDAY, True, "Closed: deadline passed"),
            (YESTERDAY, False, "Closed by employer"),
        ):
            self.deadline(value, active)
            self.assertEqual(self.job.effective_status, label)
            self.assertEqual(admin.availability(self.job), label)
        self.assertIn("close_date", admin.list_display)

    def test_creation_and_edit_date_validation_and_browser_min(self):
        for value, valid in (
            ("", True),
            (str(TODAY), True),
            (str(TOMORROW), True),
            (str(YESTERDAY), False),
            ("bad-date", False),
        ):
            with self.subTest(value=value):
                form = JobForm(self.job_data(value), instance=JobPost(employer=self.company))
                self.assertEqual(form.is_valid(), valid, form.errors)
        self.deadline(YESTERDAY)
        form = JobForm(self.job_data(str(YESTERDAY)), instance=self.job)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.fields["close_date"].widget.attrs["min"], str(YESTERDAY))
        form.save()
        form = JobForm(self.job_data(str(YESTERDAY - timedelta(days=1))), instance=self.job)
        self.assertFalse(form.is_valid())
        self.assertIn("close_date", form.errors)

    def test_create_edit_endpoints_save_and_preserve_historical_dates(self):
        self.login(self.employer)
        count = JobPost.objects.count()
        response = self.client.post(reverse("job_create"), self.job_data(str(YESTERDAY)))
        self.assertEqual(response.status_code, 200)
        self.assertIn("close_date", response.context["form"].errors)
        self.assertEqual(JobPost.objects.count(), count)
        response = self.client.post(reverse("job_create"), self.job_data(str(TOMORROW)))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            JobPost.objects.filter(title="Updated Python job", close_date=TOMORROW).exists()
        )
        self.deadline(YESTERDAY)
        response = self.client.post(
            reverse("job_edit", args=[self.job.pk]), self.job_data(str(YESTERDAY))
        )
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.close_date, YESTERDAY)
        self.assertTrue(self.job.is_active)

    def test_edits_preserve_manual_closure_and_can_extend_automatically_expired_jobs(self):
        for active in (False, True):
            for value in ("", str(TOMORROW)):
                self.deadline(YESTERDAY, active)
                self.login(self.employer)
                response = self.client.post(
                    reverse("job_edit", args=[self.job.pk]), self.job_data(value)
                )
                self.assertEqual(response.status_code, 302)
                self.job.refresh_from_db()
                self.assertEqual(self.job.is_active, active)
                self.assertEqual(self.job.accepts_new_applications, active)

    def test_stale_modelform_cannot_overwrite_concurrent_manual_state(self):
        for action in ("close", "reopen"):
            form = JobForm(
                self.job_data(str(TOMORROW)), instance=JobPost.objects.get(pk=self.job.pk)
            )
            self.assertTrue(form.is_valid(), form.errors)
            flow.change_job_state(self.employer, self.job.pk, action)
            form.save()
            self.job.refresh_from_db()
            self.assertEqual(self.job.is_active, action == "reopen")

    def test_repeated_explicit_close_and_reopen_are_idempotent_and_preserve_deadline(self):
        self.deadline(TODAY)
        for action in ("close", "close", "reopen", "reopen"):
            response = self.state_post(action)
            self.assertEqual(response.status_code, 302)
            self.job.refresh_from_db()
            self.assertEqual(self.job.is_active, action == "reopen")
            self.assertEqual(self.job.close_date, TODAY)

    def test_expired_reopen_open_cancel_and_invalid_forms_do_not_mutate(self):
        self.deadline(YESTERDAY, False)
        before = self.job.updated_at
        response = self.state_post("reopen")
        self.assertContains(response, "Save and reopen")
        self.assertContains(response, "Cancel")
        self.assertContains(response, reverse("job_detail", args=[self.job.pk]))
        self.client.get(reverse("job_detail", args=[self.job.pk]))  # Cancel destination.
        for data in (
            {},
            {"deadline": "date"},
            {"deadline": "date", "close_date": str(YESTERDAY)},
            {"deadline": "bogus"},
        ):
            response = self.state_post("reopen", save_reopen="1", **data)
            self.assertEqual(response.status_code, 400)
            self.job.refresh_from_db()
            self.assertFalse(self.job.is_active)
            self.assertEqual((self.job.close_date, self.job.updated_at), (YESTERDAY, before))
        self.assertFalse(Connection.objects.exists())

    def test_expired_reopen_requires_explicit_new_date_or_no_deadline(self):
        for choice, value, expected in (
            ("date", str(TODAY), TODAY),
            ("date", str(TOMORROW), TOMORROW),
            ("none", "", None),
        ):
            self.deadline(YESTERDAY, False)
            for _ in range(2):
                response = self.state_post(
                    "reopen", save_reopen="1", deadline=choice, close_date=value
                )
                self.assertEqual(response.status_code, 302)
                self.job.refresh_from_db()
                self.assertEqual(self.job.close_date, expected)
                self.assertTrue(self.job.accepts_new_applications)

    def test_reopen_service_revalidates_deadline_at_mutation_time(self):
        self.deadline(TODAY, False)
        form = ReopenJobForm({"deadline": "date", "close_date": str(TODAY)})
        self.assertTrue(form.is_valid())
        self.clock.return_value = datetime(2026, 11, 10, 21, tzinfo=UTC)
        for values in ({}, {"close_date": form.cleaned_data["close_date"]}):
            with self.assertRaises(flow.WorkflowError):
                flow.change_job_state(self.employer, self.job.pk, "reopen", **values)
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_active)

    def test_expired_still_active_job_can_be_manually_paused(self):
        connection = self.accepted()
        self.deadline(YESTERDAY)
        self.login(self.employer)
        page = self.client.get(reverse("job_detail", args=[self.job.pk]))
        self.assertContains(page, 'value="close"')
        self.assertContains(page, 'value="reopen"')
        self.assertEqual(self.state_post("close").status_code, 302)
        connection.refresh_from_db()
        self.assertFalse(connection.is_available)
        self.assertEqual(connection.list_state, "Paused")

    def test_recommendations_browse_counts_and_invitation_selectors_exclude_expired(self):
        self.deadline(YESTERDAY)
        self.assertEqual(MatchingAlgorithm().rank_jobs(self.profile, [self.job]), [])
        self.login(self.seeker)
        for route in ("recommendations", "jobs"):
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            items = [getattr(item, "item", item).pk for item in response.context["page_obj"]]
            self.assertNotIn(self.job.pk, items)
        self.assertEqual(
            self.client.get(reverse("job_detail", args=[self.job.pk])).status_code, 403
        )
        self.login(self.employer)
        dashboard = self.client.get(reverse("employer_jobs"))
        self.assertEqual(dashboard.context["active_job_count"], 0)
        self.assertIsNone(dashboard.context["match_job"])
        self.assertContains(dashboard, "Closed: deadline passed")
        profile = self.client.get(reverse("profile_edit"))
        self.assertEqual(profile.context["active_job_count"], 0)
        candidate = self.client.get(reverse("profile_detail", args=[self.profile.pk]))
        self.assertFalse(candidate.context["invitation_jobs_available"])
        self.assertFalse(candidate.context["invitation_form"].fields["job"].queryset.exists())
        for route in ("job_detail", "job_candidates"):
            self.assertEqual(self.client.get(reverse(route, args=[self.job.pk])).status_code, 200)

    def test_expired_saved_jobs_remain_unavailable_and_removable(self):
        SavedJob.objects.create(user=self.seeker, job=self.job)
        self.deadline(YESTERDAY)
        self.login(self.seeker)
        response = self.client.get(reverse("saved_jobs"))
        self.assertContains(response, self.job.title)
        self.assertContains(response, "No longer available")
        self.assertContains(response, "Application deadline passed:")
        self.assertNotContains(response, f'aria-label="Apply for {self.job.title}')
        self.assertEqual(self.client.post(reverse("job_save", args=[self.job.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("job_unsave", args=[self.job.pk])).status_code, 302
        )
        self.assertFalse(SavedJob.objects.exists())

    def test_stale_page_application_and_bookmark_submissions_after_midnight_are_rejected(self):
        self.deadline(TODAY)
        self.login(self.seeker)
        self.assertContains(
            self.client.get(reverse("job_detail", args=[self.job.pk])), "Send application"
        )
        self.clock.return_value = datetime(2026, 11, 10, 21, tzinfo=UTC)
        self.assertEqual(
            self.client.post(
                reverse("job_apply", args=[self.job.pk]), {"note": "Hello"}
            ).status_code,
            400,
        )
        self.assertEqual(self.client.post(reverse("job_save", args=[self.job.pk])).status_code, 404)
        self.assertFalse(Connection.objects.exists())
        self.assertFalse(SavedJob.objects.exists())

    def test_new_invitations_rejected_by_direct_and_generic_endpoints_after_expiry(self):
        self.deadline(YESTERDAY)
        self.login(self.employer)
        for name, args, data in (
            ("job_invite", [self.job.pk, self.profile.pk], {"note": "Hello"}),
            ("candidate_invite", [self.profile.pk], {"job": self.job.pk, "note": "Hello"}),
        ):
            self.assertEqual(self.client.post(reverse(name, args=args), data).status_code, 400)
        self.assertFalse(Connection.objects.exists())

    def test_existing_pending_requests_can_be_accepted_via_response_after_expiry(self):
        for initiator in ("seeker", "employer"):
            self.deadline(TODAY)
            connection = self.pending(initiator)
            self.deadline(YESTERDAY)
            flow.respond(
                self.employer if initiator == "seeker" else self.seeker, connection.pk, "accept"
            )
            connection.refresh_from_db()
            self.assertEqual(connection.status, "accepted")
            self.assertTrue(connection.is_available)
            self.assertEqual(connection.activities.filter(event="accepted").count(), 1)
            Connection.objects.all().delete()

    def test_opposing_initiate_paths_accept_existing_requests_after_expiry_without_duplicates(self):
        # Both direct and generic employer endpoints must preserve opposing-request acceptance.
        for route in ("job_invite", "candidate_invite", "job_apply"):
            self.deadline(TODAY)
            connection = self.pending("employer" if route == "job_apply" else "seeker")
            self.deadline(YESTERDAY)
            if route == "job_apply":
                self.login(self.seeker)
                args, data = [self.job.pk], {"note": "Extra"}
            else:
                self.login(self.employer)
                args = (
                    [self.job.pk, self.profile.pk] if route == "job_invite" else [self.profile.pk]
                )
                data = {"job": self.job.pk, "note": "Extra"}
            for _ in range(2):
                response = self.client.post(reverse(route, args=args), data)
                self.assertEqual(response.status_code, 302)
            connection.refresh_from_db()
            self.assertEqual(connection.status, "accepted")
            self.assertEqual(connection.note, "Original introduction")
            self.assertEqual(connection.activities.filter(event="accepted").count(), 1)
            self.assertEqual(Connection.objects.count(), 1)
            Connection.objects.all().delete()

    def test_recruitment_continues_after_deadline_but_manual_closure_and_inactivity_pause_it(self):
        connection = self.accepted()
        self.deadline(YESTERDAY)
        flow.send_message(self.seeker, connection.pk, "After deadline")
        flow.set_stage(self.employer, connection.pk, "shortlisted")
        flow.set_stage(self.employer, connection.pk, "interview", NOW + timedelta(days=2))
        for actor in (self.seeker, self.employer):
            self.login(actor)
            self.assertEqual(
                self.client.get(reverse("connection_detail", args=[connection.pk])).status_code, 200
            )
        flow.change_job_state(self.employer, self.job.pk, "close")
        with self.assertRaises(flow.WorkflowError):
            flow.send_message(self.seeker, connection.pk, "Paused")
        with self.assertRaises(flow.WorkflowError):
            flow.set_stage(self.employer, connection.pk, "offered")
        self.deadline(YESTERDAY)
        type(self.employer).objects.filter(pk=self.employer.pk).update(is_active=False)
        with self.assertRaises(flow.WorkflowError):
            flow.send_message(self.seeker, connection.pk, "Inactive counterpart")

    def test_manual_closure_and_inactive_accounts_still_prevent_existing_request_acceptance(self):
        connection = self.pending()
        self.deadline(YESTERDAY, False)
        for operation in (
            lambda: flow.respond(self.employer, connection.pk, "accept"),
            lambda: flow.initiate(self.employer, self.job.pk, self.profile.pk, role="employer"),
        ):
            with self.assertRaises(flow.WorkflowError):
                operation()
        self.deadline(YESTERDAY)
        type(self.seeker).objects.filter(pk=self.seeker.pk).update(is_active=False)
        with self.assertRaises(flow.WorkflowError):
            flow.respond(self.employer, connection.pk, "accept")

    def test_close_reopen_ownership_role_intent_get_and_csrf_protections(self):
        url = reverse("job_toggle", args=[self.job.pk])
        self.login(self.employer)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(self.client.post(url, {"action": "toggle"}).status_code, 400)
        for actor, expected in ((self.third, 404), (self.seeker, 403)):
            self.login(actor)
            self.assertEqual(self.client.post(url, {"action": "close"}).status_code, expected)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employer)
        self.assertEqual(client.post(url, {"action": "close"}).status_code, 403)
        client.force_login(self.seeker)
        self.assertEqual(client.post(reverse("job_apply", args=[self.job.pk])).status_code, 403)
        self.job.refresh_from_db()
        self.assertTrue(self.job.is_active)
        with self.assertRaises(PermissionDenied):
            flow.change_job_state(self.seeker, self.job.pk, "close")
