from datetime import timedelta
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db import connection as database
from django.db.models.deletion import ProtectedError
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch import recruitment as flow
from skillmatch.connection_forms import StageForm
from skillmatch.forms import ProfileForm
from skillmatch.models import (
    Account,
    Connection,
    ConnectionActivity,
    EmployerProfile,
    JobPost,
    JobSeekerProfile,
    Message,
    SavedCandidate,
    Skill,
)


class WorkflowCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer = User.objects.create_user("employer", email="private-employer@example.com")
        Account.objects.create(user=cls.employer, active_role="employer")
        cls.company = EmployerProfile.objects.create(
            user=cls.employer, company_name="Kisumu Studio"
        )
        cls.job = JobPost.objects.create(
            employer=cls.company,
            title="Python developer",
            description="Python",
            required_skills=["Python"],
        )
        cls.seeker = User.objects.create_user(
            "seeker", first_name="Amina", email="private-seeker@example.com"
        )
        Account.objects.create(user=cls.seeker, active_role="seeker")
        cls.profile = JobSeekerProfile.objects.create(
            user=cls.seeker,
            bio="Python developer",
            portfolio="Python project",
            phone="+254 712 345 678",
        )
        Skill.objects.create(profile=cls.profile, name="Python")
        cls.third = User.objects.create_user("third")
        Account.objects.create(user=cls.third, active_role="employer")
        cls.other_company = EmployerProfile.objects.create(
            user=cls.third, company_name="Other studio"
        )
        cls.other_job = JobPost.objects.create(
            employer=cls.other_company, title="Other job", description="Python"
        )

    def pending(self, initiator="seeker", job=None):
        return flow.initiate(
            self.seeker if initiator == "seeker" else self.employer,
            (job or self.job).pk,
            seeker_pk=self.profile.pk,
            role=initiator,
            note="Original introduction",
        )[0]

    def accepted(self, initiator="seeker", job=None):
        result = self.pending(initiator, job)
        flow.respond(self.employer if initiator == "seeker" else self.seeker, result.pk, "accept")
        result.refresh_from_db()
        return result

    def login(self, user):
        self.client.force_login(user)


class TransitionTests(WorkflowCase):
    def test_application_and_invitation_acceptance(self):
        for initiator in ["seeker", "employer"]:
            with self.subTest(initiator=initiator):
                Connection.objects.all().delete()
                c = self.accepted(initiator)
                self.assertEqual(c.status, "accepted")
                self.assertEqual(c.stage, "new")
                self.assertIsNotNone(c.responded_at)
                self.assertEqual(
                    list(c.activities.values_list("event", flat=True)), ["created", "accepted"]
                )
                self.assertEqual(c.messages.count(), 0)

    def test_duplicate_and_opposing_requests_preserve_original_note(self):
        c = self.pending()
        original = c.created_at
        retry, _ = flow.initiate(self.seeker, self.job.pk, note="Second intro")
        self.assertEqual(retry.pk, c.pk)
        self.assertEqual(retry.note, "Original introduction")
        accepted, text = flow.initiate(
            self.employer,
            self.job.pk,
            seeker_pk=self.profile.pk,
            role="employer",
            note="A second intro",
        )
        self.assertEqual(accepted.pk, c.pk)
        self.assertEqual(accepted.status, "accepted")
        self.assertIn("further text", text)
        self.assertEqual(accepted.initiated_by, "seeker")
        self.assertEqual(accepted.note, "Original introduction")
        self.assertEqual(accepted.created_at, original)
        self.assertEqual(accepted.activities.count(), 2)

    def test_only_recipient_can_accept_or_decline_pending_and_initiator_withdraw(self):
        c = self.pending()
        for action in ["accept", "decline"]:
            with self.assertRaises(PermissionDenied):
                flow.respond(self.seeker, c.pk, action)
        with self.assertRaises(PermissionDenied):
            flow.respond(self.employer, c.pk, "withdraw")
        flow.respond(self.employer, c.pk, "decline")
        c.refresh_from_db()
        self.assertEqual(c.status, "declined")
        self.assertIsNotNone(c.responded_at)

    def test_withdrawal_and_terminal_pairs_never_reopen(self):
        c = self.pending()
        flow.respond(self.seeker, c.pk, "withdraw")
        for user, role in [(self.seeker, "seeker"), (self.employer, "employer")]:
            retry, _ = flow.initiate(user, self.job.pk, seeker_pk=self.profile.pk, role=role)
            self.assertEqual(retry.status, "withdrawn")
        flow.respond(self.employer, c.pk, "accept")
        self.assertEqual(c.activities.count(), 2)
        c.refresh_from_db()
        self.assertEqual(c.status, "withdrawn")

    def test_declined_pair_stays_declined(self):
        c = self.pending()
        flow.respond(self.employer, c.pk, "decline")
        flow.initiate(self.seeker, self.job.pk)
        c.refresh_from_db()
        self.assertEqual(c.status, "declined")
        self.assertEqual(Connection.objects.count(), 1)

    def test_accepted_employer_cannot_withdraw_but_seeker_can(self):
        c = self.accepted()
        with self.assertRaises(PermissionDenied):
            flow.respond(self.employer, c.pk, "withdraw")
        flow.respond(self.seeker, c.pk, "withdraw")
        c.refresh_from_db()
        self.assertEqual(c.status, "withdrawn")

    def test_forward_stages_and_historical_interview(self):
        c = self.accepted()
        accepted_at = c.responded_at
        for invalid in ["interview", "offered", "unknown"]:
            with self.assertRaises(flow.WorkflowError):
                flow.set_stage(self.employer, c.pk, invalid)
        flow.set_stage(self.employer, c.pk, "shortlisted")
        for date in [
            None,
            timezone.now() - timedelta(minutes=1),
            timezone.now().replace(tzinfo=None),
        ]:
            with self.assertRaises(flow.WorkflowError):
                flow.set_stage(self.employer, c.pk, "interview", date)
        date = timezone.now() + timedelta(days=2)
        flow.set_stage(self.employer, c.pk, "interview", date)
        later = date + timedelta(hours=1)
        flow.set_stage(self.employer, c.pk, "interview", later)
        event = c.activities.last()
        self.assertEqual(event.event, "rescheduled")
        self.assertEqual(event.interview_at, later)
        flow.set_stage(self.employer, c.pk, "offered")
        self.assertTrue(flow.get_connection(self.seeker, c.pk).allows_messages)
        flow.send_message(self.seeker, c.pk, "Discuss the offer")
        flow.set_stage(self.employer, c.pk, "not_selected")
        c.refresh_from_db()
        self.assertEqual(c.interview_at, later)
        self.assertEqual(c.responded_at, accepted_at)
        with self.assertRaises(flow.WorkflowError):
            flow.set_stage(self.employer, c.pk, "offered")
        with self.assertRaises(flow.WorkflowError):
            flow.send_message(self.seeker, c.pk, "Cannot send")
        flow.respond(self.seeker, c.pk, "withdraw")

    def test_end_consideration_from_every_forward_stage(self):
        for stage in ["new", "shortlisted", "interview", "offered"]:
            with self.subTest(stage=stage):
                Connection.objects.all().delete()
                c = self.accepted()
                Connection.objects.filter(pk=c.pk).update(stage=stage)
                flow.set_stage(self.employer, c.pk, "not_selected")
                c.refresh_from_db()
                self.assertEqual(c.stage, "not_selected")

    def test_stages_only_for_accepted_employer_and_no_backward_moves(self):
        c = self.pending()
        with self.assertRaises(flow.WorkflowError):
            flow.set_stage(self.employer, c.pk, "shortlisted")
        flow.respond(self.employer, c.pk, "accept")
        with self.assertRaises(PermissionDenied):
            flow.set_stage(self.seeker, c.pk, "shortlisted")
        flow.set_stage(self.employer, c.pk, "shortlisted")
        with self.assertRaises(flow.WorkflowError):
            flow.set_stage(self.employer, c.pk, "new")

    def test_repeated_responses_and_stage_updates_have_one_activity(self):
        c = self.accepted()
        flow.respond(self.employer, c.pk, "accept")
        flow.set_stage(self.employer, c.pk, "shortlisted")
        flow.set_stage(self.employer, c.pk, "shortlisted")
        self.assertEqual(c.activities.count(), 3)

    def test_interview_form_uses_nairobi_timezone(self):
        form = StageForm({"stage": "interview", "interview_at": "2030-05-01T14:30"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(timezone.is_aware(form.cleaned_data["interview_at"]))
        self.assertEqual(timezone.localtime(form.cleaned_data["interview_at"]).hour, 14)
        self.assertIn("Africa/Nairobi", form.fields["interview_at"].label)


class EligibilityTests(WorkflowCase):
    def test_self_apply_self_invite_and_other_employer_denied(self):
        own = JobSeekerProfile.objects.create(user=self.employer, bio="Python", portfolio="Project")
        Skill.objects.create(profile=own, name="Python")
        with self.assertRaises(PermissionDenied):
            flow.initiate(self.employer, self.job.pk, seeker_pk=own.pk, role="employer")
        with self.assertRaises(PermissionDenied):
            flow.initiate(self.third, self.job.pk, seeker_pk=self.profile.pk, role="employer")
        self.employer.account.active_role = "seeker"
        self.employer.account.save()
        with self.assertRaises(PermissionDenied):
            flow.initiate(self.employer, self.job.pk)

    def test_incomplete_profile_or_inactive_accounts_block_new_requests(self):
        for target, field, value in [
            (self.profile, "bio", ""),
            (self.seeker, "is_active", False),
            (self.employer, "is_active", False),
            (self.job, "is_active", False),
        ]:
            old = getattr(target, field)
            setattr(target, field, value)
            target.save()
            with self.assertRaises((flow.WorkflowError, PermissionDenied)):
                flow.initiate(self.seeker, self.job.pk)
            setattr(target, field, old)
            target.save()
        self.assertEqual(Connection.objects.count(), 0)

    def test_closed_job_pending_response_restrictions_and_reopen(self):
        c = self.pending()
        flow.change_job_state(self.employer, self.job.pk, "close")
        for operation in [
            lambda: flow.respond(self.employer, c.pk, "accept"),
            lambda: flow.initiate(
                self.employer, self.job.pk, seeker_pk=self.profile.pk, role="employer"
            ),
        ]:
            with self.assertRaises(flow.WorkflowError):
                operation()
        flow.change_job_state(self.employer, self.job.pk, "reopen")
        flow.respond(self.employer, c.pk, "accept")
        flow.change_job_state(self.employer, self.job.pk, "close")
        for operation in [
            lambda: flow.send_message(self.seeker, c.pk, "hi"),
            lambda: flow.set_stage(self.employer, c.pk, "shortlisted"),
        ]:
            with self.assertRaises(flow.WorkflowError):
                operation()
        flow.respond(self.seeker, c.pk, "withdraw")
        flow.change_job_state(self.employer, self.job.pk, "reopen")
        c.refresh_from_db()
        self.assertEqual(c.status, "withdrawn")

    def test_closed_pending_allows_recipient_decline_and_sender_withdraw(self):
        for action, actor in [("decline", self.employer), ("withdraw", self.seeker)]:
            Connection.objects.all().delete()
            c = self.pending()
            JobPost.objects.filter(pk=self.job.pk).update(is_active=False)
            flow.respond(actor, c.pk, action)
            JobPost.objects.filter(pk=self.job.pk).update(is_active=True)

    def test_inactive_other_account_preserves_history_and_blocks_actions(self):
        c = self.accepted()
        self.seeker.is_active = False
        self.seeker.save()
        self.login(self.employer)
        response = self.client.get(reverse("connection_detail", args=[c.pk]))
        self.assertContains(response, "Original introduction")
        self.assertNotContains(response, self.seeker.email)
        self.assertNotContains(response, self.profile.phone)
        for operation in [
            lambda: flow.send_message(self.employer, c.pk, "hi"),
            lambda: flow.set_stage(self.employer, c.pk, "shortlisted"),
        ]:
            with self.assertRaises(flow.WorkflowError):
                operation()

    def test_history_survives_incomplete_profile(self):
        c = self.accepted()
        self.profile.bio = ""
        self.profile.save()
        self.login(self.seeker)
        self.assertContains(
            self.client.get(reverse("connection_detail", args=[c.pk])), "Original introduction"
        )
        self.assertContains(self.client.get(reverse("recruitment_connections")), self.job.title)

    def test_job_delete_protected_in_view_orm_and_admin(self):
        c = self.pending()
        with self.assertRaises(ProtectedError):
            self.job.delete()
        self.login(self.employer)
        response = self.client.post(reverse("job_delete", args=[self.job.pk]), follow=True)
        self.assertContains(response, "Close the job instead")
        self.assertTrue(Connection.objects.filter(pk=c.pk).exists())
        with self.assertRaises(ProtectedError):
            admin.site._registry[JobPost].delete_model(RequestFactory().get("/"), self.job)
        self.login(self.third)
        self.assertRedirects(
            self.client.post(reverse("job_delete", args=[self.other_job.pk])),
            reverse("employer_jobs"),
        )


class ContactAndMessageTests(WorkflowCase):
    def test_contacts_only_after_acceptance_then_revoked_by_withdrawal(self):
        c = self.pending()
        for actor, hidden in [
            (self.employer, self.seeker.email),
            (self.seeker, self.employer.email),
        ]:
            self.login(actor)
            html = self.client.get(reverse("connection_detail", args=[c.pk]))
            self.assertNotContains(html, hidden)
        self.assertFalse(flow.can_view_contact(self.employer, self.profile))
        flow.respond(self.employer, c.pk, "accept")
        self.assertTrue(flow.can_view_contact(self.employer, self.profile))
        self.login(self.employer)
        response = self.client.get(reverse("profile_detail", args=[self.profile.pk]))
        self.assertContains(response, self.seeker.email)
        self.assertContains(response, self.profile.phone)
        flow.set_stage(self.employer, c.pk, "not_selected")
        flow.change_job_state(self.employer, self.job.pk, "close")
        self.assertTrue(flow.can_view_contact(self.employer, self.profile))
        flow.respond(self.seeker, c.pk, "withdraw")
        self.assertFalse(flow.can_view_contact(self.employer, self.profile))
        response = self.client.get(reverse("connection_detail", args=[c.pk]))
        self.assertNotContains(response, self.seeker.email)

    def test_another_accepted_connection_preserves_employer_contact_access(self):
        first = self.accepted()
        job = JobPost.objects.create(
            employer=self.company, title="Second role", description="Python"
        )
        self.accepted(job=job)
        flow.respond(self.seeker, first.pk, "withdraw")
        self.assertTrue(flow.can_view_contact(self.employer, self.profile))
        self.assertFalse(flow.can_view_contact(self.third, self.profile))

    def test_no_contact_in_lists_dashboards_or_saved_cards_after_acceptance(self):
        self.accepted()
        SavedCandidate.objects.create(user=self.employer, candidate=self.profile, job=self.job)
        self.login(self.employer)
        for route, args in [
            ("recruitment_connections", []),
            ("candidates", []),
            ("job_candidates", [self.job.pk]),
            ("employer_jobs", []),
            ("saved_candidates", []),
        ]:
            response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, self.seeker.email)
            self.assertNotContains(response, self.profile.phone)

    def test_message_validation_escaping_and_submission_idempotency(self):
        c = self.accepted()
        for body in ["", " \n\t", "x" * 2001]:
            with self.assertRaises(flow.WorkflowError):
                flow.send_message(self.seeker, c.pk, body)
        key = uuid4()
        message = flow.send_message(
            self.seeker, c.pk, '<script>alert("x")</script>', submission_key=key
        )
        retry = flow.send_message(self.seeker, c.pk, "double click", submission_key=key)
        self.assertEqual(message.pk, retry.pk)
        self.assertEqual(c.messages.count(), 1)
        self.login(self.employer)
        response = self.client.get(reverse("connection_detail", args=[c.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("x")</script>')
        with self.assertRaises(PermissionDenied):
            flow.send_message(self.employer, c.pk, "reuse other's token", submission_key=key)

    def test_note_validation_and_escaping(self):
        with self.assertRaises(flow.WorkflowError):
            flow.initiate(self.seeker, self.job.pk, note="x" * 501)
        c, _ = flow.initiate(self.seeker, self.job.pk, note="  <img src=x onerror=alert(1)>  ")
        self.assertEqual(c.note, "<img src=x onerror=alert(1)>")
        self.login(self.employer)
        self.assertNotContains(self.client.get(reverse("connection_detail", args=[c.pk])), c.note)

    def test_message_read_receipts_only_for_displayed_received_page(self):
        c = self.accepted()
        incoming = [
            Message.objects.create(connection=c, sender=self.seeker, body=str(i)) for i in range(35)
        ]
        mine = Message.objects.create(connection=c, sender=self.employer, body="own message")
        self.login(self.employer)
        response = self.client.get(reverse("connection_detail", args=[c.pk]))
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertEqual(Message.objects.filter(read_at__isnull=False).count(), 5)
        incoming[0].refresh_from_db()
        mine.refresh_from_db()
        self.assertIsNone(incoming[0].read_at)
        self.assertIsNone(mine.read_at)
        self.client.get(reverse("connection_detail", args=[c.pk]) + "?page=1")
        self.assertEqual(Message.objects.filter(read_at__isnull=False).count(), 35)

    def test_activity_unread_independent_and_snapshots_are_historical(self):
        c = self.accepted()
        date = timezone.now() + timedelta(days=3)
        flow.set_stage(self.employer, c.pk, "shortlisted")
        flow.set_stage(self.employer, c.pk, "interview", date)
        flow.set_stage(self.employer, c.pk, "interview", date + timedelta(days=1))
        self.login(self.seeker)
        response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["connection_counts"]["messages"], 0)
        self.assertEqual(response.context["connection_counts"]["updates"], 4)
        response = self.client.get(reverse("connection_detail", args=[c.pk]))
        self.assertContains(response, "Interview rescheduled")
        self.assertEqual(c.activities.filter(actor=self.employer, read_at__isnull=True).count(), 0)
        self.assertEqual(c.activities.filter(actor=self.seeker, read_at__isnull=True).count(), 1)
        first_interview = c.activities.filter(event="stage", stage="interview").get()
        self.assertEqual(first_interview.interview_at, date)

    def test_profile_contact_edit_is_transactional_and_not_matching_input(self):
        payload = {
            "first_name": "Amina",
            "last_name": "Kamau",
            "email": "updated@example.com",
            "phone": "+254 700-123 456",
            "skills_json": '["Python"]',
            "bio": "Python developer",
            "portfolio": "Python project",
            "certification_level": "basic",
            "experience_level": "junior",
            "links": "",
        }
        before = self.profile.matching_text
        form = ProfileForm(payload, instance=self.profile)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.seeker.refresh_from_db()
        self.assertEqual(self.seeker.email, "updated@example.com")
        self.profile.refresh_from_db()
        self.assertEqual(before, self.profile.matching_text)
        for phone in ["abc", "+ --", "123()", "1" * 21]:
            form = ProfileForm({**payload, "phone": phone}, instance=self.profile)
            self.assertFalse(form.is_valid())
            self.assertIn("phone", form.errors)
        form = ProfileForm({**payload, "email": "not-email"}, instance=self.profile)
        self.assertFalse(form.is_valid())


class PresentationTests(WorkflowCase):
    def test_same_name_accounts_do_not_share_invitations_or_notifications(self):
        same_name = User.objects.create_user("another_amina", first_name="Amina")
        Account.objects.create(user=same_name, active_role="seeker")
        other_profile = JobSeekerProfile.objects.create(
            user=same_name, bio="Python developer", portfolio="Python project"
        )
        Skill.objects.create(profile=other_profile, name="Python")
        self.assertEqual(other_profile.display_name, self.profile.display_name)

        self.login(self.employer)
        confirmation = self.client.get(
            reverse("profile_detail", args=[self.profile.pk]) + f"?job={self.job.pk}"
        )
        self.assertContains(confirmation, "Invitation recipient: Amina (@seeker).")
        self.assertContains(
            self.client.get(reverse("employer_jobs")),
            '<div class="profile-menu-identity"><span>Signed in as</span><strong>@employer</strong></div>',
            html=True,
        )
        response = self.client.post(
            reverse("candidate_invite", args=[self.profile.pk]), {"job": self.job.pk}
        )
        connection = Connection.objects.get()
        self.assertRedirects(response, reverse("connection_detail", args=[connection.pk]))

        self.login(same_name)
        response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertEqual(
            response.context["connection_counts"], {"pending": 0, "messages": 0, "updates": 0}
        )
        self.assertNotContains(response, "Review invitation")
        self.assertEqual(
            self.client.get(reverse("connection_detail", args=[connection.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.post(reverse("connection_accept", args=[connection.pk])).status_code, 403
        )
        connection.refresh_from_db()
        self.assertEqual(connection.status, "pending")

        self.login(self.seeker)
        response = self.client.get(reverse("recommendations"))
        self.assertEqual(response.context["connection_counts"]["pending"], 1)
        self.assertEqual(response.context["connection_counts"]["updates"], 1)
        self.assertContains(response, 'class="sd-notification-count"')
        self.assertContains(
            response,
            '<div class="profile-menu-identity"><span>Signed in as</span><strong>@seeker</strong></div>',
            html=True,
        )
        response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(list(response.context["page_obj"]), [connection])
        self.assertContains(response, "Invitation from Kisumu Studio")
        self.assertContains(response, "Review invitation")
        self.assertEqual(connection.activities.filter(read_at__isnull=True).count(), 1)

    def test_recipient_can_accept_invitation_with_csrf_and_exchange_messages(self):
        connection = self.pending("employer")
        recipient = Client(enforce_csrf_checks=True)
        recipient.force_login(self.seeker)
        detail_url = reverse("connection_detail", args=[connection.pk])
        accept_url = reverse("connection_accept", args=[connection.pk])
        message_url = reverse("connection_message", args=[connection.pk])
        response = recipient.get(detail_url)
        self.assertContains(response, "Invitation from Kisumu Studio")
        self.assertContains(response, "Accept invitation")
        self.assertContains(response, "Original introduction")
        self.assertNotContains(response, 'name="body"')
        self.assertEqual(recipient.get(accept_url).status_code, 405)
        self.assertEqual(recipient.post(accept_url).status_code, 403)
        token = recipient.cookies["csrftoken"].value
        response = recipient.post(
            message_url,
            {"csrfmiddlewaretoken": token, "body": "Before acceptance", "submission_key": uuid4()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(connection.messages.count(), 0)
        response = recipient.post(accept_url, {"csrfmiddlewaretoken": token}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="body"')
        self.assertNotContains(response, "Accept invitation")
        connection.refresh_from_db()
        self.assertEqual(connection.status, "accepted")
        response = recipient.post(
            message_url,
            {
                "csrfmiddlewaretoken": token,
                "body": "Thank you for the invitation.",
                "submission_key": uuid4(),
            },
            follow=True,
        )
        self.assertContains(response, "Thank you for the invitation.")

        employer = Client(enforce_csrf_checks=True)
        employer.force_login(self.employer)
        response = employer.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["connection_counts"]["messages"], 1)
        response = employer.get(detail_url)
        self.assertContains(response, "Thank you for the invitation.")
        token = employer.cookies["csrftoken"].value
        response = employer.post(
            message_url,
            {
                "csrfmiddlewaretoken": token,
                "body": "Welcome. Let us discuss the role.",
                "submission_key": uuid4(),
            },
            follow=True,
        )
        self.assertContains(response, "Welcome. Let us discuss the role.")
        response = recipient.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["connection_counts"]["messages"], 1)
        self.assertContains(recipient.get(detail_url), "Welcome. Let us discuss the role.")
        self.assertEqual(connection.messages.count(), 2)

    def test_dashboard_activity_stays_below_hero_and_counts_remain_separate(self):
        for user, url in [(self.seeker, "recommendations"), (self.employer, "employer_jobs")]:
            self.login(user)
            response = self.client.get(reverse(url))
            self.assertContains(response, "No new activity")
            self.assertNotContains(response, 'class="rc-overview"')
            self.assertContains(response, 'href="/connections/"')
        c = self.pending()
        self.login(self.employer)
        response = self.client.get(reverse("employer_jobs"))
        self.assertEqual(response.context["connection_counts"]["pending"], 1)
        self.assertContains(response, 'aria-label="1 requests waiting for you"')
        self.assertContains(response, 'aria-label="0 unread messages"')
        self.assertContains(response, 'aria-label="1 unread updates"')
        self.assertContains(response, 'class="rc-employer-stack"')
        self.assertContains(response, 'class="ed-panel rc-dashboard-panel"')
        self.assertEqual(c.activities.filter(read_at__isnull=True).count(), 1)

    def test_invite_entry_opens_existing_confirmation_without_sending(self):
        self.login(self.employer)
        response = self.client.get(reverse("employer_jobs"))
        entry = reverse("profile_detail", args=[self.profile.pk]) + f"?job={self.job.pk}#invite"
        self.assertContains(response, f'href="{entry}"')
        self.assertContains(response, f'aria-label="Invite Amina to {self.job.title}"')
        self.assertNotContains(response, 'class="rc-consent"')
        response = self.client.get(entry)
        self.assertContains(response, "Invite Amina")
        self.assertContains(response, 'class="rc-consent"')
        self.assertContains(response, "Introduction (optional)")
        self.assertEqual(response.context["invitation_form"].initial["job"], self.job.pk)
        self.assertContains(response, reverse("candidate_invite", args=[self.profile.pk]))
        self.assertEqual(Connection.objects.count(), 0)
        self.assertEqual(ConnectionActivity.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        response = self.client.post(
            reverse("candidate_invite", args=[self.profile.pk]),
            {"job": self.job.pk, "note": "Let's discuss the role."},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Connection.objects.get().initiated_by, "employer")

    def test_apply_entry_preserves_cards_and_confirms_before_post(self):
        self.login(self.seeker)
        self.seeker.saved_jobs.create(job=self.job)
        entry = reverse("job_detail", args=[self.job.pk]) + "#apply"
        for url in ["recommendations", "saved_jobs"]:
            response = self.client.get(reverse(url))
            self.assertContains(response, f'href="{entry}"')
            self.assertContains(response, "View opportunity")
            self.assertContains(
                response, f'aria-label="Apply for {self.job.title} at Kisumu Studio"'
            )
            self.assertNotContains(response, 'class="rc-consent"')
        response = self.client.get(entry)
        self.assertContains(response, "Python developer")
        self.assertContains(response, "Kisumu Studio")
        self.assertContains(response, 'class="rc-consent"')
        self.assertContains(response, 'name="note"')
        self.assertContains(response, reverse("job_apply", args=[self.job.pk]))
        self.assertEqual(Connection.objects.count(), 0)
        self.assertEqual(ConnectionActivity.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)
        response = self.client.post(reverse("job_apply", args=[self.job.pk]), {"note": "Hello"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Connection.objects.get().initiated_by, "seeker")

    def test_existing_pairs_keep_state_links_instead_of_fresh_actions(self):
        c = self.pending()
        for user, url, label in [
            (self.seeker, "recommendations", "Applied"),
            (self.employer, "employer_jobs", "Review application"),
        ]:
            self.login(user)
            response = self.client.get(reverse(url))
            self.assertContains(response, label)
            self.assertContains(response, reverse("connection_detail", args=[c.pk]))
            self.assertNotContains(
                response, 'aria-label="Apply for Python developer at Kisumu Studio"'
            )
            self.assertNotContains(response, 'aria-label="Invite Amina to Python developer"')
        flow.respond(self.employer, c.pk, "accept")
        for user, url in [(self.seeker, "recommendations"), (self.employer, "employer_jobs")]:
            self.login(user)
            self.assertContains(self.client.get(reverse(url)), "Open connection")
        flow.change_job_state(self.employer, self.job.pk, "close")
        self.login(self.employer)
        response = self.client.get(
            reverse("profile_detail", args=[self.profile.pk]) + f"?job={self.job.pk}"
        )
        self.assertContains(response, "Paused")
        self.assertNotContains(response, "Send invitation")
        flow.respond(self.seeker, c.pk, "withdraw")
        response = self.client.get(
            reverse("profile_detail", args=[self.profile.pk]) + f"?job={self.job.pk}"
        )
        self.assertContains(response, "Withdrawn")
        self.assertNotContains(response, "Send invitation")


class EndpointTests(WorkflowCase):
    def test_employer_wrong_workspace_cannot_invite_or_access_its_connection(self):
        c = self.accepted()
        own = JobSeekerProfile.objects.create(user=self.employer)
        self.employer.account.active_role = "seeker"
        self.employer.account.save()
        self.login(self.employer)
        self.assertEqual(
            self.client.post(
                reverse("candidate_invite", args=[self.profile.pk]), {"job": self.job.pk}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("job_invite", args=[self.job.pk, self.profile.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("connection_detail", args=[c.pk])).status_code, 403
        )
        response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertIsNotNone(own.pk)

    def test_terminal_candidate_pair_has_history_link_instead_of_fresh_invite(self):
        c = self.pending()
        flow.respond(self.employer, c.pk, "decline")
        self.login(self.employer)
        response = self.client.get(
            reverse("profile_detail", args=[self.profile.pk]) + f"?job={self.job.pk}"
        )
        self.assertContains(response, "Declined")
        self.assertNotContains(response, "Send invitation")
        self.assertContains(response, reverse("connection_detail", args=[c.pk]))

    def test_invalid_stage_request_is_400_with_unchanged_state_and_activity(self):
        c = self.accepted()
        count = c.activities.count()
        self.login(self.employer)
        response = self.client.post(reverse("connection_stage", args=[c.pk]), {"stage": "offered"})
        self.assertEqual(response.status_code, 400)
        c.refresh_from_db()
        self.assertEqual(c.stage, "new")
        self.assertEqual(c.activities.count(), count)

    def test_pending_mfa_session_does_not_grant_workflow_access(self):
        from skillmatch.mfa import PENDING_KEY

        client = Client()
        session = client.session
        session[PENDING_KEY] = {"user_id": self.employer.pk}
        session.save()
        c = self.pending()
        self.assertEqual(client.get(reverse("connection_detail", args=[c.pk])).status_code, 302)
        self.assertEqual(client.post(reverse("connection_accept", args=[c.pk])).status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.status, "pending")

    def test_application_invitation_http_flows(self):
        self.login(self.seeker)
        response = self.client.post(
            reverse("job_apply", args=[self.job.pk]), {"note": "Introduction"}
        )
        c = Connection.objects.get()
        self.assertRedirects(response, reverse("connection_detail", args=[c.pk]))
        self.login(self.employer)
        self.assertRedirects(
            self.client.post(reverse("connection_accept", args=[c.pk])),
            reverse("connection_detail", args=[c.pk]),
        )
        response = self.client.post(
            reverse("connection_message", args=[c.pk]),
            {"body": "Welcome", "submission_key": uuid4(), "sender": self.third.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(c.messages.get().sender, self.employer)

    def test_third_party_and_staff_have_no_bypass(self):
        c = self.accepted()
        for staff in [False, True]:
            self.third.is_staff = staff
            self.third.is_superuser = staff
            self.third.save()
            with self.assertRaises(PermissionDenied):
                flow.get_connection(self.third, c.pk)
            self.login(self.third)
            if staff:
                device = TOTPDevice.objects.create(user=self.third, confirmed=True)
                session = self.client.session
                session[DEVICE_ID_SESSION_KEY] = device.persistent_id
                session.save()
            for route in [
                "connection_detail",
                "connection_accept",
                "connection_decline",
                "connection_withdraw",
                "connection_stage",
                "connection_message",
            ]:
                response = (
                    self.client.get(reverse(route, args=[c.pk]))
                    if route == "connection_detail"
                    else self.client.post(reverse(route, args=[c.pk]))
                )
                self.assertEqual(response.status_code, 403, route)

    def test_wrong_active_role_denied_every_connection_endpoint(self):
        c = self.accepted()
        EmployerProfile.objects.create(user=self.seeker, company_name="Side business")
        self.seeker.account.active_role = "employer"
        self.seeker.account.save()
        self.login(self.seeker)
        for route in [
            "connection_detail",
            "connection_accept",
            "connection_decline",
            "connection_withdraw",
            "connection_stage",
            "connection_message",
        ]:
            path = reverse(route, args=[c.pk])
            response = (
                self.client.get(path) if route == "connection_detail" else self.client.post(path)
            )
            self.assertEqual(response.status_code, 403, route)
        self.assertEqual(
            self.client.post(reverse("job_apply", args=[self.job.pk])).status_code, 403
        )
        self.assertFalse(flow.can_view_contact(self.seeker, self.profile))

    def test_post_only_csrf_anonymous_and_redirects(self):
        c = self.pending()
        self.login(self.employer)
        for route, args in [
            ("job_apply", [self.job.pk]),
            ("candidate_invite", [self.profile.pk]),
            ("job_invite", [self.job.pk, self.profile.pk]),
            *[
                (name, [c.pk])
                for name in [
                    "connection_accept",
                    "connection_decline",
                    "connection_withdraw",
                    "connection_stage",
                    "connection_message",
                ]
            ],
        ]:
            self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.employer)
        self.assertEqual(protected.post(reverse("connection_accept", args=[c.pk])).status_code, 403)
        protected.get(reverse("connection_detail", args=[c.pk]))
        token = protected.cookies["csrftoken"].value
        response = protected.post(
            reverse("connection_accept", args=[c.pk]),
            {"csrfmiddlewaretoken": token, "next": "https://evil.example"},
        )
        self.assertEqual(response.url, reverse("connection_detail", args=[c.pk]))
        self.assertEqual(Client().get(reverse("connection_detail", args=[c.pk])).status_code, 302)

    def test_job_selection_and_filter_ownership(self):
        self.login(self.employer)
        response = self.client.get(reverse("profile_detail", args=[self.profile.pk]))
        self.assertIsNone(response.context["invitation_form"]["job"].value())
        response = self.client.get(
            reverse("profile_detail", args=[self.profile.pk]) + f"?job={self.job.pk}"
        )
        self.assertEqual(response.context["invitation_form"]["job"].value(), self.job.pk)
        self.assertEqual(
            self.client.post(
                reverse("candidate_invite", args=[self.profile.pk]), {"job": self.other_job.pk}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                reverse("recruitment_connections") + f"?job={self.other_job.pk}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("job_invite", args=[self.other_job.pk, self.profile.pk])
            ).status_code,
            403,
        )
        JobPost.objects.filter(employer=self.company).update(is_active=False)
        self.assertContains(
            self.client.get(reverse("profile_detail", args=[self.profile.pk])), "An active job"
        )

    def test_rate_limit_duplicates_incoming_acceptance_and_expiry(self):
        with override_settings(CONNECTION_REQUEST_LIMIT=1):
            c = self.pending()
            flow.initiate(self.seeker, self.job.pk)
            self.login(self.seeker)
            response = self.client.post(reverse("job_apply", args=[self.other_job.pk]))
            self.assertEqual(response.status_code, 429)
            flow.respond(self.seeker, c.pk, "withdraw")
            with self.assertRaises(flow.WorkflowError):
                flow.initiate(self.seeker, self.other_job.pk)
            Connection.objects.filter(pk=c.pk).update(
                created_at=timezone.now() - timedelta(hours=25)
            )
            flow.initiate(self.seeker, self.other_job.pk)
        # Incoming acceptance is not a new initiated request in either role.
        with override_settings(CONNECTION_REQUEST_LIMIT=0):
            c, _ = flow.initiate(
                self.third, self.other_job.pk, seeker_pk=self.profile.pk, role="employer"
            )
            self.assertEqual(c.status, "accepted")

    def test_notes_and_messages_fail_without_partial_database_writes(self):
        c = self.accepted()
        self.login(self.seeker)
        response = self.client.post(
            reverse("connection_message", args=[c.pk]), {"body": " \t ", "submission_key": uuid4()}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(c.messages.count(), 0)
        response = self.client.post(
            reverse("job_apply", args=[self.other_job.pk]), {"note": "x" * 501}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Connection.objects.count(), 1)

    def test_schema_constraints_and_admin_are_inspection_only(self):
        c = self.pending()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Connection.objects.create(job=self.job, seeker=self.profile, initiated_by="employer")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Connection.objects.filter(pk=c.pk).update(status="bogus")
        request = RequestFactory().get("/")
        request.user = self.employer
        for model in [Connection, Message, ConnectionActivity]:
            handler = admin.site._registry[model]
            self.assertFalse(handler.has_add_permission(request))
            self.assertFalse(handler.has_change_permission(request))
            self.assertFalse(handler.has_delete_permission(request))
            self.assertEqual(
                set(handler.get_readonly_fields(request)),
                {field.name for field in model._meta.fields},
            )

    def test_list_pagination_and_query_growth_is_bounded(self):
        self.pending()
        self.login(self.employer)
        with CaptureQueriesContext(database) as few:
            self.client.get(reverse("recruitment_connections"))
        for i in range(24):
            job = JobPost.objects.create(
                employer=self.company, title=f"Role {i}", description="Python"
            )
            Connection.objects.create(job=job, seeker=self.profile, initiated_by="seeker")
        with CaptureQueriesContext(database) as many:
            response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["page_obj"].paginator.count, 25)
        self.assertEqual(len(response.context["page_obj"]), 20)
        self.assertLessEqual(len(many), len(few) + 2)
