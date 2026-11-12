from django.urls import reverse
from django.utils import timezone

from skillmatch import recruitment as flow
from skillmatch.models import Account, EmployerProfile
from skillmatch.tests.test_connections import WorkflowCase


class NotificationBellTests(WorkflowCase):
    def page(self, user):
        self.login(user)
        return self.client.get(reverse("recruitment_connections"))

    def test_request_counted_once_and_bell_links_to_connections(self):
        for initiator, recipient in [("employer", self.seeker), ("seeker", self.employer)]:
            with self.subTest(initiator=initiator):
                job = self.job if initiator == "employer" else self.other_job
                if initiator == "seeker":
                    recipient = self.third
                self.pending(initiator, job)
                response = self.page(recipient)
                self.assertEqual(response.context["connection_notification_count"], 1)
                self.assertContains(
                    response,
                    '<span class="sd-notification-count" aria-hidden="true">1</span>',
                    html=True,
                )
                self.assertContains(response, 'href="/connections/"')

    def test_messages_updates_reads_and_unsent_messages(self):
        connection = self.accepted()
        response = self.page(self.seeker)
        self.assertEqual(response.context["connection_notification_count"], 1)
        first = flow.send_message(self.employer, connection.pk, "First update")
        second = flow.send_message(self.employer, connection.pk, "Second update")
        response = self.page(self.seeker)
        self.assertEqual(response.context["connection_notification_count"], 3)
        second.unsent_at = timezone.now()
        second.body = ""
        second.save(update_fields=["unsent_at", "body"])
        self.assertEqual(self.page(self.seeker).context["connection_notification_count"], 2)
        response = self.client.get(reverse("connection_detail", args=[connection.pk]))
        self.assertEqual(response.context["connection_notification_count"], 0)
        self.assertNotContains(response, 'class="sd-notification-count"')
        first.refresh_from_db()
        self.assertIsNotNone(first.read_at)

    def test_own_activity_other_accounts_and_other_mode_are_excluded(self):
        self.pending("employer")
        self.assertEqual(self.page(self.employer).context["connection_notification_count"], 0)
        self.assertEqual(self.page(self.third).context["connection_notification_count"], 0)
        EmployerProfile.objects.create(user=self.seeker, company_name="Second workspace")
        Account.objects.filter(user=self.seeker).update(active_role="employer")
        self.assertEqual(self.page(self.seeker).context["connection_notification_count"], 0)

    def test_footer_removed_from_public_and_both_workspaces(self):
        for user in [None, self.seeker, self.employer]:
            with self.subTest(user=user):
                self.client.logout()
                if user:
                    self.login(user)
                response = self.client.get(reverse("home"), follow=True)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'class="site-footer"')
                self.assertNotContains(response, 'class="sm-footer')
                self.assertNotContains(response, "168111")
                self.assertNotContains(response, "CS Project II")
