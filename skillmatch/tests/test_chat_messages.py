import re
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.test import Client, RequestFactory
from django.urls import reverse

from skillmatch import recruitment as flow
from skillmatch.models import Connection, Message
from skillmatch.tests.test_connections import WorkflowCase


class ChatMessageTests(WorkflowCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 10, tzinfo=UTC)
        self.clock = patch("skillmatch.recruitment.timezone.now", return_value=self.now).start()
        self.addCleanup(patch.stopall)
        self.connection = self.accepted()
        self.message = flow.send_message(
            self.seeker, self.connection.pk, "Original ordinary message"
        )

    def page(self, actor=None, **query):
        self.login(actor or self.seeker)
        return self.client.get(reverse("connection_detail", args=[self.connection.pk]), query)

    def post(self, action, data=None, *, actor=None, message=None, connection=None):
        self.login(actor or self.seeker)
        return self.client.post(
            reverse(
                action, args=[(connection or self.connection).pk, (message or self.message).pk]
            ),
            data or {},
        )

    def bubble(self, response, message=None):
        return re.search(
            rf'<article\b[^>]*id="message-{(message or self.message).pk}".*?</article>',
            response.content.decode(),
            re.S,
        ).group()

    def test_recipient_heading_subtitle_and_relative_bubbles_for_both_roles(self):
        reply = flow.send_message(self.employer, self.connection.pk, "Employer reply")
        for actor, recipient, own, incoming in (
            (self.seeker, self.company.company_name, self.message, reply),
            (self.employer, self.profile.display_name, reply, self.message),
        ):
            response = self.page(actor)
            self.assertContains(response, f"Chat with {recipient}")
            self.assertContains(response, f"<p>{self.job.title}</p>", html=True)
            self.assertIn("rc-mine", self.bubble(response, own))
            self.assertNotIn("rc-mine", self.bubble(response, incoming))
            self.assertNotIn("rc-message-menu", self.bubble(response, incoming))
            chat = (
                response.content.decode()
                .split('id="chat"', 1)[1]
                .split('class="rc-card rc-activity"', 1)[0]
            )
            self.assertNotIn("<img", chat)
            self.assertNotIn("avatar", chat)
            self.assertNotContains(response, "Messages page 1 of 1")

    def test_introduction_author_alignment_and_no_message_actions(self):
        for actor, mine in ((self.seeker, True), (self.employer, False)):
            response = self.page(actor)
            intro = re.search(
                r'<article class="rc-message rc-introduction.*?</article>',
                response.content.decode(),
                re.S,
            ).group()
            self.assertEqual("rc-mine" in intro, mine)
            self.assertIn("Introduction", intro)
            self.assertNotIn("rc-message-menu", intro)
            self.assertNotIn("data-message-until", intro)
        Connection.objects.filter(pk=self.connection.pk).update(initiated_by="employer")
        response = self.page(self.employer)
        self.assertContains(response, 'class="rc-message rc-introduction rc-mine"')

    def test_multiple_edits_preserve_original_timestamp_position_receipt_and_notifications(self):
        read_at = self.now + timedelta(seconds=10)
        Message.objects.filter(pk=self.message.pk).update(read_at=read_at)
        later = flow.send_message(self.seeker, self.connection.pk, "Later ordinary message")
        activities = self.connection.activities.count()
        connection_updated = self.connection.updated_at
        for minute, body in ((4, "First edit"), (14, "Second edit\nAnother line")):
            self.clock.return_value = self.now + timedelta(minutes=minute)
            response = self.post("message_edit", {"body": body})
            self.assertEqual(response.status_code, 302)
            self.assertIn(f"#message-{self.message.pk}", response.url)
            self.message.refresh_from_db()
            self.assertEqual(self.message.body, body)
            self.assertEqual(self.message.created_at, self.now)
            self.assertEqual(self.message.edited_at, self.clock.return_value)
            self.assertEqual(self.message.read_at, read_at)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.updated_at, connection_updated)
        self.assertEqual(self.connection.activities.count(), activities)
        self.assertEqual(
            list(self.connection.messages.values_list("pk", flat=True)), [self.message.pk, later.pk]
        )
        self.assertContains(self.page(), '<span class="rc-edited">edited</span>', html=True)

    def test_noop_edit_does_not_add_or_change_edited_timestamp(self):
        response = self.post("message_edit", {"body": "  Original ordinary message  "})
        self.assertEqual(response.status_code, 302)
        self.message.refresh_from_db()
        self.assertIsNone(self.message.edited_at)
        self.assertNotIn('class="rc-edited"', self.bubble(self.page()))
        flow.edit_message(self.seeker, self.connection.pk, self.message.pk, "Changed")
        self.message.refresh_from_db()
        edited_at = self.message.edited_at
        self.clock.return_value = self.now + timedelta(minutes=3)
        flow.edit_message(self.seeker, self.connection.pk, self.message.pk, "Changed")
        self.message.refresh_from_db()
        self.assertEqual(self.message.edited_at, edited_at)

    def test_strict_deadline_for_edit_and_unsend_and_edit_does_not_extend_it(self):
        self.clock.return_value = self.now + timedelta(minutes=14, seconds=59, microseconds=999999)
        self.assertEqual(self.post("message_edit", {"body": "Just in time"}).status_code, 302)
        for elapsed in (timedelta(minutes=15), timedelta(minutes=16)):
            self.clock.return_value = self.now + elapsed
            for action, data in (
                ("message_edit", {"body": "Too late"}),
                ("message_unsend", {"confirm": "true"}),
            ):
                response = self.post(action, data)
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "15-minute window has expired", status_code=400)
                self.message.refresh_from_db()
                self.assertEqual(self.message.body, "Just in time")
                self.assertIsNone(self.message.unsent_at)
            self.assertNotIn("rc-message-menu", self.bubble(self.page()))

    def test_unsend_allowed_just_before_deadline(self):
        self.clock.return_value = self.now + timedelta(minutes=15) - timedelta(microseconds=1)
        self.assertEqual(self.post("message_unsend", {"confirm": "true"}).status_code, 302)
        self.message.refresh_from_db()
        self.assertEqual(self.message.unsent_at, self.clock.return_value)

    def test_unsend_clears_body_and_edited_label_for_both_participants(self):
        secret = "REMOVED-CONTENT-unique-<script>alert(42)</script>"
        flow.edit_message(self.seeker, self.connection.pk, self.message.pk, secret)
        response = self.post("message_unsend", {"confirm": "true"})
        self.assertEqual(response.status_code, 302)
        self.message.refresh_from_db()
        self.assertEqual(self.message.body, "")
        self.assertEqual(self.message.created_at, self.now)
        self.assertIsNotNone(self.message.unsent_at)
        for actor in (self.seeker, self.employer):
            response = self.page(actor)
            self.assertContains(response, "Message was unsent")
            self.assertNotContains(response, "REMOVED-CONTENT")
            bubble = self.bubble(response)
            self.assertNotIn("rc-message-menu", bubble)
            self.assertNotIn("rc-edited", bubble)
            self.assertNotIn("textarea", bubble)
            self.assertEqual("rc-mine" in bubble, actor == self.seeker)
        for action in ("message_edit", "message_unsend"):
            response = self.post(action, {"body": secret, "confirm": "true"})
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, "REMOVED-CONTENT", status_code=400)
        response = self.page(edit=self.message.pk)
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "REMOVED-CONTENT", status_code=400)
        self.message.refresh_from_db()
        self.assertEqual(self.message.body, "")

    def test_opposite_participant_and_third_party_cannot_forge_actions(self):
        for actor in (self.employer, self.third):
            for action in ("message_edit", "message_unsend"):
                response = self.post(action, {"body": "Forged", "confirm": "true"}, actor=actor)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(self.message.body, response.content.decode())
            response = self.page(actor, edit=self.message.pk)
            self.assertEqual(response.status_code, 403)
        other = flow.initiate(self.seeker, self.other_job.pk)[0]
        response = self.post("message_edit", {"body": "Wrong connection"}, connection=other)
        self.assertEqual(response.status_code, 404)
        self.message.refresh_from_db()
        self.assertEqual(self.message.body, "Original ordinary message")

    def test_wrong_active_role_is_rejected_and_does_not_change_receipts(self):
        self.seeker.account.active_role = "employer"
        self.seeker.account.save(update_fields=["active_role"])
        for action in ("message_edit", "message_unsend"):
            self.assertEqual(
                self.post(action, {"body": "Wrong role", "confirm": "true"}).status_code, 403
            )
        self.message.refresh_from_db()
        self.assertIsNone(self.message.read_at)

    def test_all_existing_readonly_states_block_edit_and_unsend(self):
        for field, value in (
            ("status", "pending"),
            ("status", "declined"),
            ("status", "withdrawn"),
            ("stage", "not_selected"),
        ):
            with self.subTest(field=field, value=value):
                Connection.objects.filter(pk=self.connection.pk).update(
                    status="accepted", stage="new"
                )
                Connection.objects.filter(pk=self.connection.pk).update(**{field: value})
                for action in ("message_edit", "message_unsend"):
                    self.assertEqual(
                        self.post(action, {"body": "Read only", "confirm": "true"}).status_code, 400
                    )
                self.assertNotIn("rc-message-menu", self.bubble(self.page()))
        Connection.objects.filter(pk=self.connection.pk).update(status="accepted", stage="new")
        flow.change_job_state(self.employer, self.job.pk, "close")
        self.assertEqual(self.post("message_edit", {"body": "Closed"}).status_code, 400)
        self.assertEqual(self.post("message_unsend", {"confirm": "true"}).status_code, 400)
        flow.change_job_state(self.employer, self.job.pk, "reopen")
        type(self.employer).objects.filter(pk=self.employer.pk).update(is_active=False)
        self.assertEqual(
            self.post("message_edit", {"body": "Inactive counterpart"}).status_code, 400
        )
        self.assertEqual(self.post("message_unsend", {"confirm": "true"}).status_code, 400)
        type(self.seeker).objects.filter(pk=self.seeker.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            flow.unsend_message(self.seeker, self.connection.pk, self.message.pk)

    def test_blank_overlong_invalid_edits_retain_attempt_and_do_not_mutate(self):
        for body in ("", " \n\t", "x" * 2001):
            response = self.post("message_edit", {"body": body})
            self.assertEqual(response.status_code, 400)
            self.assertIn("body", response.context["edit_form"].errors)
            self.assertEqual(response.context["edit_form"].data["body"], body)
            self.message.refresh_from_db()
            self.assertEqual(self.message.body, "Original ordinary message")
            self.assertIsNone(self.message.edited_at)
            with self.assertRaises(flow.WorkflowError):
                flow.edit_message(self.seeker, self.connection.pk, self.message.pk, body)

    def test_edit_confirmation_and_cancellation_do_not_mutate_and_unset_requires_confirmation(self):
        for action in ("edit", "unsend"):
            response = self.page(**{action: self.message.pk})
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Cancel")
        self.assertContains(response, "both participants")
        self.assertContains(response, "viewed or copied cannot be recalled")
        self.assertEqual(self.post("message_unsend").status_code, 400)
        self.page()  # Cancel navigates back to the normal thread.
        self.message.refresh_from_db()
        self.assertEqual(self.message.body, "Original ordinary message")
        self.assertIsNone(self.message.edited_at)
        self.assertIsNone(self.message.unsent_at)

    def test_unread_queries_exclude_unsent_and_edits_do_not_reset_read_receipt(self):
        self.login(self.employer)
        response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["connection_counts"]["messages"], 1)
        self.assertEqual(response.context["page_obj"][0].unread_messages, 1)
        flow.edit_message(self.seeker, self.connection.pk, self.message.pk, "Edited while unread")
        self.message.refresh_from_db()
        self.assertIsNone(self.message.read_at)
        response = self.client.get(reverse("employer_jobs"))
        self.assertEqual(response.context["connection_counts"]["messages"], 1)
        flow.unsend_message(self.seeker, self.connection.pk, self.message.pk)
        response = self.client.get(reverse("recruitment_connections"))
        self.assertEqual(response.context["connection_counts"]["messages"], 0)
        self.assertEqual(response.context["page_obj"][0].unread_messages, 0)
        self.page(self.employer)
        self.message.refresh_from_db()
        self.assertIsNone(self.message.read_at)

    def test_composer_validation_multiline_and_escaping_preserved(self):
        self.login(self.seeker)
        url = reverse("connection_message", args=[self.connection.pk])
        response = self.client.post(url, {"body": " \n\t", "submission_key": str(uuid4())})
        self.assertEqual(response.status_code, 400)
        self.assertIn("body", response.context["message_form"].errors)
        body = 'Two lines\n<script>alert("x")</script>'
        response = self.client.post(url, {"body": body, "submission_key": str(uuid4())})
        self.assertEqual(response.status_code, 302)
        response = self.page()
        self.assertContains(response, "Two lines<br>")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, 'maxlength="2000"')
        self.assertContains(response, 'rows="2"')
        self.assertContains(response, 'for="id_body"')

    def test_stale_edit_after_concurrent_unsend_does_not_echo_removed_body(self):
        self.page(edit=self.message.pk)
        original = flow.edit_message

        def unsent_first(*args, **kwargs):
            flow.unsend_message(self.seeker, self.connection.pk, self.message.pk)
            return original(*args, **kwargs)

        with patch.object(flow, "edit_message", side_effect=unsent_first):
            response = self.post("message_edit", {"body": self.message.body})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Message was unsent", status_code=400)
        self.assertNotContains(response, "Original ordinary message", status_code=400)

    def test_original_pagination_order_and_selected_edit_page_are_preserved(self):
        Message.objects.bulk_create(
            [
                Message(connection=self.connection, sender=self.seeker, body=f"Later {i}")
                for i in range(35)
            ]
        )
        response = self.page()
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertContains(response, "Older messages")
        response = self.page(edit=self.message.pk)
        self.assertEqual(response.context["page_obj"].number, 1)
        self.assertContains(response, "Save changes")
        self.assertEqual(self.post("message_edit", {"body": "Older page edit"}).status_code, 302)
        self.assertEqual(self.connection.messages.first().pk, self.message.pk)

    def test_get_and_csrf_protections_admin_readonly_and_no_hard_delete(self):
        self.login(self.seeker)
        for name in ("message_edit", "message_unsend"):
            url = reverse(name, args=[self.connection.pk, self.message.pk])
            self.assertEqual(self.client.get(url).status_code, 405)
            client = Client(enforce_csrf_checks=True)
            client.force_login(self.seeker)
            self.assertEqual(
                client.post(url, {"body": "Bad CSRF", "confirm": "true"}).status_code, 403
            )
            self.assertEqual(Client().post(url).status_code, 302)
        message_admin = admin.site._registry[Message]
        request = RequestFactory().get("/")
        for field in ("body", "created_at", "edited_at", "unsent_at"):
            self.assertIn(field, message_admin.get_readonly_fields(request, self.message))
        self.assertFalse(message_admin.has_change_permission(request, self.message))
        self.assertFalse(message_admin.has_delete_permission(request, self.message))
        flow.unsend_message(self.seeker, self.connection.pk, self.message.pk)
        self.assertTrue(Message.objects.filter(pk=self.message.pk).exists())

    def test_employer_can_edit_and_unsend_their_own_message(self):
        message = flow.send_message(self.employer, self.connection.pk, "Employer message")
        self.assertEqual(
            self.post(
                "message_edit", {"body": "Employer edit"}, actor=self.employer, message=message
            ).status_code,
            302,
        )
        self.assertEqual(
            self.post(
                "message_unsend", {"confirm": "true"}, actor=self.employer, message=message
            ).status_code,
            302,
        )
        self.assertContains(self.page(self.seeker), "Message was unsent")

    def test_deadline_is_rechecked_after_sqlite_transaction_retry(self):
        self.clock.return_value = self.now + timedelta(minutes=14, seconds=59)

        def lock_then_expire(*args, **kwargs):
            self.clock.return_value = self.now + timedelta(minutes=15)
            raise OperationalError("database is locked")

        with (
            patch.object(flow, "text", side_effect=lock_then_expire),
            self.assertRaisesMessage(flow.WorkflowError, "15-minute window has expired"),
        ):
            flow.edit_message(self.seeker, self.connection.pk, self.message.pk, "Never saved")
        self.message.refresh_from_db()
        self.assertEqual(self.message.body, "Original ordinary message")
        self.assertIsNone(self.message.edited_at)
