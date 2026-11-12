from datetime import timedelta
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from skillmatch import recruitment as flow
from skillmatch.models import Connection
from skillmatch.tests.test_connections import WorkflowCase


class ContactCardTests(WorkflowCase):
    def page(self, user, connection):
        self.login(user)
        return self.client.get(reverse("connection_detail", args=[connection.pk]))

    def test_employer_gets_labelled_candidate_contact_and_correct_copy_values(self):
        connection = self.accepted()
        response = self.page(self.employer, connection)
        self.assertContains(response, 'class="rc-participant-name"')
        self.assertContains(response, "@seeker")
        self.assertContains(response, 'class="rc-contact-tile"', count=2)
        self.assertContains(response, reverse("profile_detail", args=[self.profile.pk]))
        self.assertContains(response, "Email:")
        self.assertContains(response, "Contact:")
        self.assertContains(
            response, f"<span data-copy-value>{self.seeker.email}</span>", html=True
        )
        self.assertContains(
            response, f"<span data-copy-value>{self.profile.phone}</span>", html=True
        )
        self.assertContains(response, 'aria-label="Copy email address"', count=1)
        self.assertContains(response, 'aria-label="Copy phone number"', count=1)
        self.assertNotContains(response, self.employer.email)
        self.assertContains(response, "Contact access is granted by acceptance.")

    def test_seeker_gets_employer_identity_and_full_width_email_tile_without_phone(self):
        response = self.page(self.seeker, self.accepted())
        self.assertContains(
            response, f"<span data-copy-value>{self.employer.email}</span>", html=True
        )
        self.assertNotContains(response, self.seeker.email)
        self.assertNotContains(response, self.profile.phone)
        self.assertContains(response, 'aria-label="Copy email address"', count=1)
        self.assertNotContains(response, "Copy phone number")
        self.assertNotContains(response, 'class="rc-tile-label">Contact:</span>')
        self.assertContains(response, 'class="rc-contact-tile"', count=1)
        card = (
            response.content.decode()
            .split('class="rc-card rc-parties"', 1)[1]
            .split("</section>", 1)[0]
        )
        header, contacts = card.split('class="rc-contact-tiles"', 1)
        self.assertIn(self.company.company_name, header)
        self.assertIn("Job seeker", header)
        self.assertIn("@seeker", header)
        self.assertIn(self.employer.email, contacts)

    def test_blank_phone_or_email_produces_no_empty_row_or_copy_button(self):
        connection = self.accepted()
        for value in ["", "   "]:
            self.profile.phone = value
            self.profile.save(update_fields=["phone"])
            response = self.page(self.employer, connection)
            self.assertNotContains(response, 'class="rc-tile-label">Contact:</span>')
            self.assertNotContains(response, "Copy phone number")
            self.assertContains(response, 'class="rc-contact-tile"', count=1)
        self.seeker.email = ""
        self.seeker.save(update_fields=["email"])
        response = self.page(self.employer, connection)
        self.assertNotContains(response, 'class="rc-tile-label">Email:</span>')
        self.assertNotContains(response, "data-copy-contact")
        self.assertNotContains(response, 'class="rc-contact-tiles"')

    def test_profile_led_header_images_fallbacks_and_full_privacy_explanation(self):
        connection = self.accepted()
        self.seeker.last_name = "Kamau"
        self.seeker.save(update_fields=["last_name"])
        connection.seeker = self.profile
        connection.job.employer = self.company
        context = {"connection": connection, "participant_role": "employer"}
        without_image = render_to_string("skillmatch/connections/participant_card.html", context)
        self.assertIn("AK", without_image)
        self.assertNotIn("Connected</", without_image)
        self.assertNotIn('class="rc-contact-tiles"', without_image)
        self.assertIn("another accepted connection may still grant access.", without_image)
        self.profile.photo = SimpleNamespace(url="/media/profile-photo.jpg")
        with_image = render_to_string("skillmatch/connections/participant_card.html", context)
        self.assertIn('src="/media/profile-photo.jpg"', with_image)
        self.assertNotIn("data-copy-contact", with_image)

        context["participant_role"] = "seeker"
        self.company.logo = SimpleNamespace(url="/media/company-logo.png")
        with_logo = render_to_string("skillmatch/connections/participant_card.html", context)
        self.assertIn('src="/media/company-logo.png"', with_logo)
        self.company.logo = None
        without_logo = render_to_string("skillmatch/connections/participant_card.html", context)
        self.assertIn('data-image-fallback="logo"', without_logo)
        self.assertIn(">K</span>", without_logo)

    def test_unaccepted_and_withdrawn_contacts_are_not_embedded_anywhere(self):
        connection = self.pending()
        for status in ["pending", "declined", "withdrawn"]:
            Connection.objects.filter(pk=connection.pk).update(status=status)
            for user in [self.employer, self.seeker]:
                with self.subTest(status=status, viewer=user.username):
                    response = self.page(user, connection)
                    for private in [self.seeker.email, self.employer.email, self.profile.phone]:
                        self.assertNotContains(response, private)
                    self.assertNotContains(response, "data-copy-contact")
                    self.assertNotContains(response, 'class="rc-contact-tiles"')
                    self.assertContains(response, 'class="rc-contact-privacy"')

    def test_existing_contact_access_policy_survives_new_structure(self):
        connection = self.accepted()
        flow.set_stage(self.employer, connection.pk, "not_selected")
        flow.change_job_state(self.employer, self.job.pk, "close")
        self.assertContains(self.page(self.employer, connection), self.seeker.email)
        self.assertContains(self.page(self.seeker, connection), self.employer.email)
        self.seeker.is_active = False
        self.seeker.save(update_fields=["is_active"])
        self.assertNotContains(self.page(self.employer, connection), self.seeker.email)
        self.seeker.is_active = True
        self.seeker.save(update_fields=["is_active"])
        second = self.pending(job=self.other_job)
        flow.respond(self.third, second.pk, "accept")
        flow.respond(self.seeker, connection.pk, "withdraw")
        # The other employer's acceptance cannot grant this employer contact access.
        self.assertNotContains(self.page(self.employer, connection), self.seeker.email)
        extra_job = self.company.jobs.create(title="Another role", description="Python")
        self.accepted(job=extra_job)
        self.assertContains(self.page(self.employer, connection), self.seeker.email)
        self.assertIsNotNone(second.pk)


class RecruitmentProgressTests(WorkflowCase):
    def page(self, connection, user=None):
        self.login(user or self.employer)
        return self.client.get(reverse("connection_detail", args=[connection.pk]))

    def post(self, connection, stage, **data):
        response = self.page(connection)
        payload = {"stage": stage, "expected_state": response.context["progress_token"], **data}
        return self.client.post(reverse("connection_stage", args=[connection.pk]), payload)

    def date(self, days=1):
        return timezone.localtime(timezone.now() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")

    def test_every_saved_stage_has_correct_labels_and_actions(self):
        connection = self.accepted()
        for stage, label, actions in [
            ("new", "New", ["Move to shortlisted"]),
            ("shortlisted", "Shortlisted", ["Schedule interview", "Confirm interview"]),
            ("interview", "Interview", ["Reschedule", "Save new time", "Mark offer made"]),
            ("offered", "Offer made", []),
            ("not_selected", "Not selected", []),
        ]:
            with self.subTest(stage=stage):
                Connection.objects.filter(pk=connection.pk).update(stage=stage)
                response = self.page(connection)
                self.assertContains(response, "Recruitment progress")
                self.assertContains(response, f"Current stage: <strong>{label}</strong>", html=True)
                self.assertContains(response, f"Accepted · {label} ·")
                self.assertNotContains(response, '<select name="stage"')
                self.assertNotContains(response, "Update progress</button>")
                for action in [
                    "Move to shortlisted",
                    "Schedule interview",
                    "Reschedule",
                    "Mark offer made",
                ]:
                    if action in actions:
                        self.assertContains(response, action)
                    else:
                        self.assertNotContains(response, f">{action}</")
                if stage != "not_selected":
                    self.assertContains(response, "Confirm not selected")
                else:
                    self.assertNotContains(response, "Confirm not selected")
                if stage == "new":
                    self.assertNotContains(response, 'name="interview_at"')

    def test_scheduler_open_cancel_and_invalid_submission_do_not_change_saved_state(self):
        connection = self.accepted()
        flow.set_stage(self.employer, connection.pk, "shortlisted")
        events = connection.activities.count()
        response = self.page(connection)
        token = response.context["progress_token"]
        for query in ["?schedule=1", "?cancel=1", ""]:
            self.client.get(reverse("connection_detail", args=[connection.pk]) + query)
        for date in ["", self.date(-1), "invalid"]:
            response = self.client.post(
                reverse("connection_stage", args=[connection.pk]),
                {"stage": "interview", "expected_state": token, "interview_at": date},
            )
            self.assertEqual(response.status_code, 400)
            self.assertContains(
                response, "Current stage: <strong>Shortlisted</strong>", html=True, status_code=400
            )
            self.assertTrue(response.context["scheduler_open"])
        connection.refresh_from_db()
        self.assertEqual(connection.stage, "shortlisted")
        self.assertIsNone(connection.interview_at)
        self.assertEqual(connection.activities.count(), events)

    def test_schedule_and_reschedule_use_nairobi_time_and_one_event(self):
        connection = self.accepted()
        self.assertEqual(self.post(connection, "shortlisted").status_code, 302)
        date = self.date()
        self.assertEqual(self.post(connection, "interview", interview_at=date).status_code, 302)
        connection.refresh_from_db()
        self.assertEqual(
            timezone.localtime(connection.interview_at).strftime("%Y-%m-%dT%H:%M"), date
        )
        response = self.page(connection)
        self.assertEqual(
            response.context["stage_form"]["interview_at"].value().strftime("%Y-%m-%dT%H:%M"), date
        )
        self.assertContains(response, f'value="{date}"')
        token = response.context["progress_token"]
        events = connection.activities.count()
        payload = {"stage": "interview", "expected_state": token, "interview_at": self.date(2)}
        endpoint = reverse("connection_stage", args=[connection.pk])
        self.assertEqual(self.client.post(endpoint, payload).status_code, 302)
        self.assertEqual(self.client.post(endpoint, payload).status_code, 302)
        self.assertEqual(connection.activities.count(), events + 1)
        self.assertEqual(connection.activities.last().event, "rescheduled")
        stale = self.client.post(endpoint, {**payload, "interview_at": self.date(3)})
        self.assertEqual(stale.status_code, 409)
        connection.refresh_from_db()
        self.assertEqual(
            timezone.localtime(connection.interview_at).strftime("%Y-%m-%dT%H:%M"),
            payload["interview_at"],
        )
        self.assertEqual(connection.activities.count(), events + 1)

    def test_past_recorded_interview_does_not_block_offer_or_viewing(self):
        connection = self.accepted()
        past = timezone.now() - timedelta(days=1)
        Connection.objects.filter(pk=connection.pk).update(stage="interview", interview_at=past)
        response = self.page(connection)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mark offer made")
        self.assertEqual(self.post(connection, "offered").status_code, 302)
        connection.refresh_from_db()
        self.assertEqual(connection.stage, "offered")
        self.assertEqual(connection.interview_at, past)
        for user in [self.employer, self.seeker]:
            response = self.page(connection, user)
            self.assertContains(response, "Accepted · Offer made · Active")
            self.assertContains(response, "Current stage: <strong>Offer made</strong>", html=True)
            self.assertContains(response, "Stage changed: Offer made")
            self.assertContains(response, "does not confirm that the candidate has accepted it")
            self.assertNotContains(response, ": Offered")

    def test_not_selected_needs_confirmation_and_is_terminal_without_revoking_contacts(self):
        connection = self.accepted()
        before = connection.activities.count()
        response = self.post(connection, "not_selected")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context["rejection_open"])
        connection.refresh_from_db()
        self.assertEqual(connection.stage, "new")
        self.assertEqual(connection.activities.count(), before)
        response = self.post(connection, "not_selected", confirm_not_selected="true")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(connection.activities.count(), before + 1)
        self.assertEqual(
            self.post(connection, "not_selected", confirm_not_selected="true").status_code, 302
        )
        self.assertEqual(connection.activities.count(), before + 1)
        response = self.page(connection)
        self.assertContains(response, self.seeker.email)
        self.assertNotContains(response, 'name="body"')
        self.assertNotContains(response, "Confirm not selected")
        flow.change_job_state(self.employer, self.job.pk, "close")
        flow.change_job_state(self.employer, self.job.pk, "reopen")
        self.assertNotContains(self.page(connection), "Mark offer made")

    def test_stale_forward_form_cannot_end_consideration_from_newer_stage(self):
        connection = self.accepted()
        token = self.page(connection).context["progress_token"]
        self.assertEqual(self.post(connection, "shortlisted").status_code, 302)
        events = connection.activities.count()
        response = self.client.post(
            reverse("connection_stage", args=[connection.pk]),
            {"stage": "not_selected", "expected_state": token, "confirm_not_selected": "true"},
        )
        self.assertEqual(response.status_code, 409)
        connection.refresh_from_db()
        self.assertEqual(connection.stage, "shortlisted")
        self.assertEqual(connection.activities.count(), events)

    def test_skipped_backward_and_unsigned_actions_are_rejected(self):
        connection = self.accepted()
        for stage in ["interview", "offered", "new"]:
            response = self.post(connection, stage, interview_at=self.date())
            self.assertEqual(response.status_code, 302 if stage == "new" else 400)
        for token in ["", "tampered"]:
            self.login(self.employer)
            self.assertEqual(
                self.client.post(
                    reverse("connection_stage", args=[connection.pk]),
                    {"stage": "shortlisted", "expected_state": token},
                ).status_code,
                400,
            )
        self.assertEqual(self.post(connection, "shortlisted").status_code, 302)
        self.assertEqual(self.post(connection, "new").status_code, 400)

    def test_seeker_and_restricted_connections_have_no_employer_controls(self):
        connection = self.accepted()
        response = self.page(connection, self.seeker)
        self.assertContains(response, "Current stage:")
        self.assertNotContains(response, "ready for review")
        self.assertNotContains(response, 'name="expected_state"')
        self.assertNotContains(response, "Confirm not selected")
        for status in ["pending", "declined", "withdrawn"]:
            Connection.objects.filter(pk=connection.pk).update(status=status)
            self.assertNotContains(self.page(connection), 'name="expected_state"')
            self.assertEqual(self.post(connection, "shortlisted").status_code, 400)
        Connection.objects.filter(pk=connection.pk).update(status="accepted")
        for target in [self.job, self.seeker]:
            field = "is_active"
            setattr(target, field, False)
            target.save(update_fields=[field])
            self.assertNotContains(self.page(connection), 'name="expected_state"')
            self.assertEqual(self.post(connection, "shortlisted").status_code, 400)
            setattr(target, field, True)
            target.save(update_fields=[field])

    def test_progress_post_remains_csrf_protected(self):
        connection = self.accepted()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employer)
        token = client.get(reverse("connection_detail", args=[connection.pk])).context[
            "progress_token"
        ]
        endpoint = reverse("connection_stage", args=[connection.pk])
        payload = {"stage": "shortlisted", "expected_state": token}
        self.assertEqual(client.post(endpoint, payload).status_code, 403)
        payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        self.assertEqual(client.post(endpoint, payload).status_code, 302)
