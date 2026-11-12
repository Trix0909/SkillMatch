import re
from html.parser import HTMLParser

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice

from skillmatch.models import Account, Connection, EmployerProfile, JobPost, JobSeekerProfile, Skill


class MenuLinks(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.links.append(attrs.get("href"))


class ProfileDropdownTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employer = User.objects.create_user(
            "hiring_user", first_name="Personal", last_name="Identity"
        )
        cls.seeker = User.objects.create_user("seeking_user", first_name="Amina", last_name="Kamau")
        Account.objects.create(user=cls.employer, active_role="employer")
        Account.objects.create(user=cls.seeker, active_role="seeker")
        cls.company = EmployerProfile.objects.create(
            user=cls.employer, company_name="Nairobi Works"
        )
        cls.profile = JobSeekerProfile.objects.create(
            user=cls.seeker, bio="Python", portfolio="Python"
        )
        Skill.objects.create(profile=cls.profile, name="Python")
        cls.job = JobPost.objects.create(
            employer=cls.company,
            title="Python role",
            description="Python",
            required_skills=["Python"],
        )
        cls.connection = Connection.objects.create(
            job=cls.job, seeker=cls.profile, initiated_by="seeker"
        )

    def menu(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/profile_dropdown.html")
        html = response.content.decode()
        self.assertEqual(html.count("data-profile-dropdown"), 1)
        return re.search(r'<details class="profile-dropdown".*?</details>', html, re.S).group()

    def assert_actions(self, response, user, profile_url, profile_label):
        menu = self.menu(response)
        for text in (
            "Signed in as",
            f"@{user.username}",
            profile_label,
            "Account security",
            "Connected accounts",
            "Log out",
        ):
            self.assertIn(text, menu)
        positions = [
            menu.index(label)
            for label in (profile_label, "Account security", "Connected accounts", "Log out")
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            MenuLinks(menu).links,
            [profile_url, reverse("account_security"), reverse("social_connections")],
        )
        self.assertIn('method="post"', menu)
        self.assertIn(f'action="{reverse("logout")}"', menu)
        self.assertIn('name="csrfmiddlewaretoken"', menu)
        self.assertIn('type="submit"', menu)
        self.assertIn('aria-expanded="false"', menu)
        self.assertIn('aria-controls="profile-menu-options"', menu)
        self.assertNotIn('href="#"', menu)
        return menu

    def test_seeker_menu_is_shared_across_dashboard_profile_jobs_security_and_connections(self):
        self.client.force_login(self.seeker)
        for name, args in (
            ("recommendations", []),
            ("profile_edit", []),
            ("jobs", []),
            ("saved_jobs", []),
            ("job_detail", [self.job.pk]),
            ("profile_detail", [self.profile.pk]),
            ("account_security", []),
            ("social_connections", []),
            ("methodology", []),
            ("recruitment_connections", []),
            ("connection_detail", [self.connection.pk]),
        ):
            with self.subTest(route=name):
                response = self.client.get(reverse(name, args=args))
                menu = self.assert_actions(
                    response,
                    self.seeker,
                    reverse("profile_detail", args=[self.profile.pk]),
                    "View profile",
                )
                self.assertIn("Amina Kamau", menu)
                self.assertIn("Job seeker account", menu)

    def test_employer_menu_is_shared_across_all_employer_shells_and_job_forms(self):
        self.client.force_login(self.employer)
        urls = [
            reverse(name, args=args)
            for name, args in (
                ("employer_jobs", []),
                ("profile_edit", []),
                ("candidates", []),
                ("saved_candidates", []),
                ("job_candidates", [self.job.pk]),
                ("job_create", []),
                ("job_edit", [self.job.pk]),
                ("job_detail", [self.job.pk]),
                ("job_delete", [self.job.pk]),
                ("profile_detail", [self.profile.pk]),
                ("account_security", []),
                ("social_connections", []),
                ("methodology", []),
                ("recruitment_connections", []),
                ("connection_detail", [self.connection.pk]),
            )
        ] + [reverse("employer_jobs") + "?view=all"]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                menu = self.assert_actions(
                    response, self.employer, reverse("profile_edit"), "View company profile"
                )
                self.assertIn("Nairobi Works", menu)
                self.assertIn("Employer account", menu)
                self.assertNotIn("Personal Identity", menu)

    def test_current_identity_is_independent_of_the_profile_being_viewed(self):
        self.client.force_login(self.employer)
        response = self.client.get(reverse("profile_detail", args=[self.profile.pk]))
        self.assertEqual(response.context["profile"].user_id, self.seeker.pk)
        self.assertEqual(response.context["profile_dropdown"]["name"], self.company.company_name)
        self.assertEqual(
            response.context["profile_dropdown"]["profile_url"], reverse("profile_edit")
        )

    def test_role_switch_updates_the_shared_identity_without_changing_profiles(self):
        company = EmployerProfile.objects.create(user=self.seeker, company_name="Amina Studio")
        self.client.force_login(self.seeker)
        self.assertEqual(
            self.client.post(reverse("switch_role"), {"active_role": "employer"}).status_code, 302
        )
        response = self.client.get(reverse("employer_jobs"))
        self.assertEqual(response.context["profile_dropdown"]["name"], "Amina Studio")
        self.assertIn("Employer account", self.menu(response))
        self.client.post(reverse("switch_role"), {"active_role": "seeker"})
        response = self.client.get(reverse("recommendations"))
        self.assertEqual(response.context["profile_dropdown"]["name"], "Amina Kamau")
        company.refresh_from_db()
        self.assertEqual(company.company_name, "Amina Studio")

    def test_photos_logos_initials_and_username_fallback(self):
        for user, route, initial in (
            (self.seeker, "recommendations", "A"),
            (self.employer, "employer_jobs", "N"),
        ):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse(route)).context["profile_dropdown"]["initial"], initial
            )
        self.profile.photo = "profiles/avatar.png"
        self.profile.save(update_fields=["photo"])
        self.company.logo = "profiles/company.png"
        self.company.save(update_fields=["logo"])
        for user, route, image in (
            (self.seeker, "recommendations", "/media/profiles/avatar.png"),
            (self.employer, "employer_jobs", "/media/profiles/company.png"),
        ):
            self.client.force_login(user)
            self.assertIn(image, self.menu(self.client.get(reverse(route))))
        User.objects.filter(pk=self.seeker.pk).update(first_name="", last_name="")
        self.client.force_login(self.seeker)
        self.assertEqual(
            self.client.get(reverse("recommendations")).context["profile_dropdown"]["name"],
            self.seeker.username,
        )

    def test_menu_escapes_names_and_long_values_are_not_replaced_with_mock_data(self):
        name = '<script>alert("company")</script>' + " Long Company" * 6
        self.company.company_name = name
        self.company.save(update_fields=["company_name"])
        self.client.force_login(self.employer)
        menu = self.menu(self.client.get(reverse("employer_jobs")))
        self.assertNotIn('<script>alert("company")</script>', menu)
        self.assertIn("&lt;script&gt;", menu)
        self.assertIn("Long Company", menu)

    def test_existing_logout_remains_post_and_csrf_protected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.seeker)
        response = client.get(reverse("jobs"))
        self.assert_actions(
            response, self.seeker, reverse("profile_detail", args=[self.profile.pk]), "View profile"
        )
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(reverse("logout"), {"csrfmiddlewaretoken": token}).status_code, 302
        )
        self.assertNotIn("_auth_user_id", client.session)

    def test_admin_keeps_its_own_menu_assets_and_destinations(self):
        user = User.objects.create_superuser("menu_admin", password="Admin-UI-test-123!")
        Account.objects.create(user=user, active_role="seeker")
        JobSeekerProfile.objects.create(user=user)
        device = TOTPDevice.objects.create(user=user, confirmed=True)
        self.client.force_login(user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'class="sm-account-menu"')
        self.assertContains(response, 'class="sm-account-dropdown"')
        self.assertContains(response, reverse("admin:password_change"))
        self.assertContains(response, reverse("admin:logout"))
        self.assertNotContains(response, "data-profile-dropdown")
        self.assertNotContains(response, "profile-dropdown.css")
        self.assertNotContains(response, "profile-dropdown.js")

    def test_anonymous_pages_do_not_render_the_signed_in_control(self):
        response = self.client.get(reverse("landing"))
        self.assertNotContains(response, "data-profile-dropdown")
        self.assertNotContains(response, "profile-dropdown.js")
