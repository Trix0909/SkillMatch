from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

from django.contrib.auth.models import User
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from skillmatch import recruitment as flow
from skillmatch.models import (
    Account,
    Connection,
    ConnectionActivity,
    EmployerProfile,
    JobPost,
    JobSeekerProfile,
    Message,
    Skill,
)


class WorkflowConcurrencyTests(TransactionTestCase):
    """Real separate connections, not mocked select_for_update promises on SQLite."""

    def setUp(self):
        self.employer = User.objects.create_user("concurrent_employer")
        self.seeker = User.objects.create_user("concurrent_seeker")
        Account.objects.create(user=self.employer, active_role="employer")
        Account.objects.create(user=self.seeker, active_role="seeker")
        self.company = EmployerProfile.objects.create(
            user=self.employer, company_name="Thread Studio"
        )
        self.profile = JobSeekerProfile.objects.create(
            user=self.seeker, bio="Python", portfolio="Python"
        )
        Skill.objects.create(profile=self.profile, name="Python")
        self.job = JobPost.objects.create(employer=self.company, title="Role", description="Python")

    def race(self, operations):
        barrier = Barrier(len(operations))

        def work(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            except flow.WorkflowError as error:
                return error.status
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(work, operations))

    def test_concurrent_duplicate_application_creates_one_request_and_event(self):
        results = self.race([lambda: flow.initiate(self.seeker, self.job.pk) for _ in range(3)])
        self.assertTrue(all(isinstance(result, tuple) for result in results), results)
        self.assertEqual(Connection.objects.count(), 1)
        self.assertEqual(ConnectionActivity.objects.count(), 1)

    def test_stale_simultaneous_reschedules_cannot_overwrite_each_other(self):
        connection, _ = flow.initiate(self.seeker, self.job.pk)
        flow.respond(self.employer, connection.pk, "accept")
        flow.set_stage(self.employer, connection.pk, "shortlisted")
        flow.set_stage(
            self.employer, connection.pk, "interview", timezone.now() + timedelta(days=1)
        )
        connection.refresh_from_db()
        snapshot = flow.stage_snapshot(connection)
        dates = [timezone.now() + timedelta(days=2), timezone.now() + timedelta(days=3)]
        events = connection.activities.count()
        results = self.race(
            [
                lambda: flow.set_stage(
                    self.employer, connection.pk, "interview", dates[0], snapshot
                ),
                lambda: flow.set_stage(
                    self.employer, connection.pk, "interview", dates[1], snapshot
                ),
            ]
        )
        self.assertEqual(sum(isinstance(result, tuple) for result in results), 1)
        self.assertIn(409, results)
        connection.refresh_from_db()
        self.assertIn(connection.interview_at, dates)
        self.assertEqual(connection.activities.count(), events + 1)

    def test_opposing_application_and_invitation_accept_one_original(self):
        results = self.race(
            [
                lambda: flow.initiate(self.seeker, self.job.pk, note="Seeker intro"),
                lambda: flow.initiate(
                    self.employer,
                    self.job.pk,
                    seeker_pk=self.profile.pk,
                    role="employer",
                    note="Employer intro",
                ),
            ]
        )
        self.assertTrue(all(isinstance(result, tuple) for result in results), results)
        c = Connection.objects.get()
        self.assertEqual(c.status, "accepted")
        self.assertEqual(c.note, "Seeker intro" if c.initiated_by == "seeker" else "Employer intro")
        self.assertEqual(
            list(c.activities.values_list("event", flat=True)), ["created", "accepted"]
        )

    def test_simultaneous_accept_and_withdraw_has_valid_atomic_history(self):
        c, _ = flow.initiate(self.seeker, self.job.pk)
        self.race(
            [
                lambda: flow.respond(self.employer, c.pk, "accept"),
                lambda: flow.respond(self.seeker, c.pk, "withdraw"),
            ]
        )
        c.refresh_from_db()
        self.assertEqual(c.status, "withdrawn")
        self.assertEqual(c.activities.filter(event="withdrawn").count(), 1)
        self.assertLessEqual(c.activities.filter(event="accepted").count(), 1)

    def test_job_closure_serializes_with_acceptance_and_preserves_history(self):
        c, _ = flow.initiate(self.seeker, self.job.pk)
        results = self.race(
            [
                lambda: flow.change_job_state(self.employer, self.job.pk, "close"),
                lambda: flow.respond(self.employer, c.pk, "accept"),
            ]
        )
        self.job.refresh_from_db()
        c.refresh_from_db()
        self.assertFalse(self.job.is_active)
        self.assertIn(c.status, ["pending", "accepted"])
        self.assertNotIn(503, results)
        self.assertEqual(c.activities.filter(event="accepted").count(), int(c.status == "accepted"))

    def test_job_closure_serializes_with_messaging(self):
        c, _ = flow.initiate(self.seeker, self.job.pk)
        flow.respond(self.employer, c.pk, "accept")
        results = self.race(
            [
                lambda: flow.change_job_state(self.employer, self.job.pk, "close"),
                lambda: flow.send_message(self.seeker, c.pk, "Before closure"),
            ]
        )
        self.assertNotIn(503, results)
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_active)
        self.assertLessEqual(Message.objects.count(), 1)
        with self.assertRaises(flow.WorkflowError):
            flow.send_message(self.seeker, c.pk, "After closure")

    def test_repeated_concurrent_close_submissions_do_not_reopen_job(self):
        results = self.race(
            [lambda: flow.change_job_state(self.employer, self.job.pk, "close") for _ in range(3)]
        )
        self.assertTrue(all(isinstance(result, JobPost) for result in results), results)
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_active)

    def test_ordinary_edit_and_manual_close_preserve_both_changes(self):
        data = {
            "title": "Edited concurrently",
            "description": "Python",
            "skills_json": '["Python"]',
            "certification_level": "basic",
            "experience_level": "junior",
            "close_date": "",
        }
        results = self.race(
            [
                lambda: flow.save_job_edit(self.employer, self.job.pk, data),
                lambda: flow.change_job_state(self.employer, self.job.pk, "close"),
            ]
        )
        self.assertNotIn(503, results)
        self.job.refresh_from_db()
        self.assertFalse(self.job.is_active)
        self.assertEqual(self.job.title, "Edited concurrently")

    @override_settings(CONNECTION_REQUEST_LIMIT=1)
    def test_concurrent_last_rate_limit_slot_cannot_be_overspent(self):
        other_job = JobPost.objects.create(
            employer=self.company, title="Other", description="Python"
        )
        results = self.race(
            [
                lambda: flow.initiate(self.seeker, self.job.pk),
                lambda: flow.initiate(self.seeker, other_job.pk),
            ]
        )
        self.assertEqual(results.count(429), 1, results)
        self.assertEqual(Connection.objects.count(), 1)
        self.assertEqual(ConnectionActivity.objects.count(), 1)

    def test_repeated_message_submission_key_is_atomic(self):
        c, _ = flow.initiate(self.seeker, self.job.pk)
        flow.respond(self.employer, c.pk, "accept")
        key = uuid4()
        results = self.race(
            [
                lambda: flow.send_message(self.seeker, c.pk, "Only once", submission_key=key)
                for _ in range(2)
            ]
        )
        self.assertTrue(all(isinstance(result, Message) for result in results), results)
        self.assertEqual(Message.objects.count(), 1)

    def test_concurrent_edit_and_unsend_cannot_restore_removed_body(self):
        connection, _ = flow.initiate(self.seeker, self.job.pk)
        flow.respond(self.employer, connection.pk, "accept")
        message = flow.send_message(self.seeker, connection.pk, "Original")
        results = self.race(
            [
                lambda: flow.edit_message(
                    self.seeker, connection.pk, message.pk, "Edit racing unsend"
                ),
                lambda: flow.unsend_message(self.seeker, connection.pk, message.pk),
            ]
        )
        self.assertNotIn(503, results)
        message.refresh_from_db()
        self.assertEqual(message.body, "")
        self.assertIsNotNone(message.unsent_at)
        self.assertIsNone(message.edited_at)
        self.assertEqual(ConnectionActivity.objects.count(), 2)
        with self.assertRaises(flow.WorkflowError):
            flow.edit_message(self.seeker, connection.pk, message.pk, "Must stay removed")

    def test_concurrent_duplicate_unsends_keep_one_placeholder(self):
        connection, _ = flow.initiate(self.seeker, self.job.pk)
        flow.respond(self.employer, connection.pk, "accept")
        message = flow.send_message(self.seeker, connection.pk, "Original")
        results = self.race(
            [lambda: flow.unsend_message(self.seeker, connection.pk, message.pk) for _ in range(2)]
        )
        self.assertEqual(sum(isinstance(result, Message) for result in results), 1)
        self.assertEqual(results.count(400), 1)
        message.refresh_from_db()
        self.assertEqual(message.body, "")
        self.assertEqual(connection.messages.count(), 1)
