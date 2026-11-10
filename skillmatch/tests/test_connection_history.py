from unittest.mock import patch

from django.db import OperationalError, connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models.query import QuerySet
from django.test import TransactionTestCase
from django.urls import reverse

from skillmatch import recruitment as flow
from skillmatch.models import Connection, ConnectionActivity, JobPost, JobSeekerProfile, Message
from skillmatch.tests.test_connections import WorkflowCase


class HistoryEdgeTests(WorkflowCase):
    def test_contact_email_edit_does_not_verify_it_or_change_provider_identity(self):
        from allauth.account.models import EmailAddress
        from allauth.socialaccount.models import SocialAccount

        from skillmatch.forms import ProfileForm

        old = EmailAddress.objects.create(user=self.seeker, email=self.seeker.email, verified=True)
        social = SocialAccount.objects.create(
            user=self.seeker, provider="google", uid="synthetic-provider-uid"
        )
        form = ProfileForm(
            {
                "first_name": "Amina",
                "last_name": "Kamau",
                "email": "new-unverified@example.com",
                "phone": "",
                "bio": "Python",
                "portfolio": "Python",
                "skills_json": '["Python"]',
                "certification_level": "basic",
                "experience_level": "junior",
            },
            instance=self.profile,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        old.refresh_from_db()
        social.refresh_from_db()
        self.assertTrue(old.verified)
        self.assertEqual(old.email, "private-seeker@example.com")
        self.assertFalse(
            EmailAddress.objects.filter(
                user=self.seeker, email="new-unverified@example.com", verified=True
            ).exists()
        )
        self.assertEqual(social.uid, "synthetic-provider-uid")

    def test_messages_arriving_after_page_selection_remain_unread(self):
        c = self.accepted()
        first = Message.objects.create(connection=c, sender=self.seeker, body="Selected message")
        original_update = QuerySet.update
        arrived = []

        def update(query, **kwargs):
            if query.model is Message and "read_at" in kwargs and not arrived:
                arrived.append(
                    Message.objects.create(connection=c, sender=self.seeker, body="New arrival")
                )
            return original_update(query, **kwargs)

        self.login(self.employer)
        with patch.object(QuerySet, "update", update):
            response = self.client.get(reverse("connection_detail", args=[c.pk]))
        first.refresh_from_db()
        arrived[0].refresh_from_db()
        self.assertIsNotNone(first.read_at)
        self.assertIsNone(arrived[0].read_at)
        self.assertNotContains(response, "New arrival")

    def test_only_displayed_received_activity_is_read(self):
        c = self.pending()
        ConnectionActivity.objects.bulk_create(
            [
                ConnectionActivity(
                    connection=c, actor=self.seeker, event="stage", stage="shortlisted"
                )
                for _ in range(25)
            ]
        )
        own = ConnectionActivity.objects.create(
            connection=c, actor=self.employer, event="stage", stage="shortlisted"
        )
        self.login(self.employer)
        response = self.client.get(reverse("connection_detail", args=[c.pk]))
        self.assertEqual(response.context["activity_page"].number, 2)
        self.assertEqual(
            c.activities.exclude(actor=self.employer).filter(read_at__isnull=False).count(), 6
        )
        own.refresh_from_db()
        self.assertIsNone(own.read_at)
        self.assertTrue(
            c.activities.exclude(actor=self.employer).filter(read_at__isnull=True).exists()
        )

    def test_transient_failure_rolls_back_every_write_before_whole_retry(self):
        original = flow.activity
        attempts = []

        def flaky(*args):
            attempts.append(True)
            if len(attempts) == 1:
                raise OperationalError("database is locked")
            return original(*args)

        with patch.object(flow, "activity", flaky):
            c, _ = flow.initiate(self.seeker, self.job.pk)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(Connection.objects.count(), 1)
        self.assertEqual(c.activities.count(), 1)

    def test_exhausted_lock_contention_returns_retryable_status_without_partial_data(self):
        with patch.object(flow, "activity", side_effect=OperationalError("database is locked")):
            self.login(self.seeker)
            response = self.client.post(reverse("job_apply", args=[self.job.pk]))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Connection.objects.count(), 0)
        self.assertEqual(ConnectionActivity.objects.count(), 0)

    def test_wrong_workspace_message_does_not_update_unread_receipts(self):
        c = self.accepted()
        message = Message.objects.create(connection=c, sender=self.employer, body="Private")
        self.seeker.account.active_role = "employer"
        self.seeker.account.save()
        self.login(self.seeker)
        self.assertEqual(
            self.client.get(reverse("connection_detail", args=[c.pk])).status_code, 403
        )
        message.refresh_from_db()
        self.assertIsNone(message.read_at)


class ConnectionMigrationTests(TransactionTestCase):
    def test_baseline_data_migrates_without_profile_or_job_loss(self):
        executor = MigrationExecutor(connection)
        baseline = [("skillmatch", "0007_profile_images")]
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(baseline)
            apps = executor.loader.project_state(baseline).apps
            user = apps.get_model("auth", "User").objects.create(
                username="migration_user", email="stored@example.com"
            )
            seeker = apps.get_model("skillmatch", "JobSeekerProfile").objects.create(
                user_id=user.pk,
                bio="Old bio",
                portfolio="Old portfolio",
                photo="profiles/person.png",
            )
            employer = apps.get_model("skillmatch", "EmployerProfile").objects.create(
                user_id=user.pk,
                company_name="Old company",
                description="Existing company story",
                tagline="Local teams, meaningful work",
                logo="profiles/logo.png",
                cover_image="profiles/cover.png",
            )
            job = apps.get_model("skillmatch", "JobPost").objects.create(
                employer=employer, title="Old job", description="Existing job"
            )
            MigrationExecutor(connection).migrate(latest)
            profile = JobSeekerProfile.objects.get(pk=seeker.pk)
            self.assertEqual(profile.phone, "")
            self.assertEqual(profile.bio, "Old bio")
            self.assertEqual(profile.portfolio, "Old portfolio")
            self.assertEqual(profile.photo.name, "profiles/person.png")
            self.assertEqual(profile.user.email, "stored@example.com")
            company = profile.user.employer_profile
            self.assertEqual(company.company_name, "Old company")
            self.assertEqual(company.description, "Existing company story")
            self.assertEqual(company.tagline, "Local teams, meaningful work")
            self.assertEqual(company.logo.name, "profiles/logo.png")
            self.assertEqual(company.cover_image.name, "profiles/cover.png")
            self.assertEqual(JobPost.objects.get(pk=job.pk).description, "Existing job")
            self.assertEqual(Connection.objects.count(), 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
