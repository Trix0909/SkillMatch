from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class GetStartedTests(TestCase):
    def test_public_page_and_role_choices(self):
        response = self.client.get(reverse("get_started"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Get started with")
        for role in ["seeker", "employer"]:
            self.assertContains(response, reverse("register") + "?role=" + role)
            signup = self.client.get(reverse("register"), {"role": role})
            self.assertEqual(signup.context["form"]["role"].value(), role)
        self.assertEqual(User.objects.count(), 0)

    def test_get_started_links_and_invalid_role(self):
        response = self.client.get(reverse("landing"))
        self.assertContains(response, reverse("get_started"))
        response = self.client.get(reverse("register"), {"role": "admin"})
        self.assertNotEqual(response.context["form"]["role"].value(), "admin")
        self.assertFalse(response.context["form"].is_bound)

    def test_posted_role_remains_authoritative_on_errors(self):
        response = self.client.post(reverse("register") + "?role=employer", {"role": "seeker"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["role"].value(), "seeker")
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(User.objects.count(), 0)

    def test_signed_in_visitors_return_to_workspace(self):
        user = User.objects.create_user("existing")
        self.client.force_login(user)
        self.assertRedirects(
            self.client.get(reverse("get_started")), reverse("home"), fetch_redirect_response=False
        )
