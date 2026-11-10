from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from skillmatch.models import Account, EmployerProfile, JobSeekerProfile
from skillmatch.profile_images import ProfileImageField


def upload(fmt="PNG", size=(32, 24), name="photo.png"):
    stream = BytesIO()
    Image.new("RGB", size, "green").save(stream, format=fmt)
    return SimpleUploadedFile(name, stream.getvalue(), content_type="image/" + fmt.lower())


class ProfileImageTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media = Path(directory.name)
        override = self.settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user("image_editor", first_name="Amina", last_name="Kamau")
        self.account = Account.objects.create(user=self.user, active_role="employer")
        self.company = EmployerProfile.objects.create(
            user=self.user, company_name="Test Studio", description="Existing story"
        )
        self.seeker = JobSeekerProfile.objects.create(
            user=self.user, bio="Existing bio", portfolio="Existing project"
        )
        self.client.force_login(self.user)

    def company_data(self, **extra):
        return {"company_name": "Test Studio", "description": "Existing story", **extra}

    def seeker_data(self, **extra):
        return {
            "first_name": "Amina",
            "last_name": "Kamau",
            "bio": "Existing bio",
            "portfolio": "Existing project",
            "skills_json": '["Python"]',
            "certification_level": "basic",
            "experience_level": "junior",
            **extra,
        }

    def test_company_uploads_save_normalized_images_and_render_in_previews(self):
        response = self.client.post(
            reverse("profile_edit"),
            self.company_data(
                logo=upload("JPEG", name="client.jpg"),
                cover_image=upload("WEBP", name="cover.webp"),
            ),
        )
        self.assertRedirects(response, reverse("employer_jobs"))
        self.company.refresh_from_db()
        for field in [self.company.logo, self.company.cover_image]:
            self.assertTrue(field.name.endswith(".png"))
            self.assertNotIn("client", field.name)
            with Image.open(field.path) as image:
                self.assertEqual(image.format, "PNG")
        response = self.client.get(reverse("profile_edit"))
        self.assertContains(response, self.company.logo.url)
        self.assertContains(response, self.company.cover_image.url)
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertEqual(self.company.description, "Existing story")

    def test_replacing_and_clearing_company_images_preserves_other_fields(self):
        self.client.post(
            reverse("profile_edit"), self.company_data(logo=upload(), cover_image=upload())
        )
        self.company.refresh_from_db()
        old_name, cover_name = self.company.logo.name, self.company.cover_image.name
        self.client.post(reverse("profile_edit"), self.company_data(logo=upload()))
        self.company.refresh_from_db()
        self.assertNotEqual(self.company.logo.name, old_name)
        self.assertEqual(self.company.cover_image.name, cover_name)
        self.client.post(
            reverse("profile_edit"),
            self.company_data(**{"logo-clear": "on", "cover_image-clear": "on"}),
        )
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)
        self.assertFalse(self.company.cover_image)
        self.assertEqual(self.company.description, "Existing story")
        self.assertContains(self.client.get(reverse("profile_edit")), "landing-nairobi.jpg")

    def test_seeker_photo_saves_displays_and_survives_role_switch(self):
        self.account.active_role = "seeker"
        self.account.save()
        response = self.client.post(reverse("profile_edit"), self.seeker_data(photo=upload()))
        self.seeker.refresh_from_db()
        self.assertRedirects(response, reverse("profile_detail", args=[self.seeker.pk]))
        name = self.seeker.photo.name
        self.assertContains(
            self.client.get(reverse("profile_detail", args=[self.seeker.pk])), self.seeker.photo.url
        )
        self.assertContains(self.client.get(reverse("profile_edit")), self.seeker.photo.url)
        # Existing switch endpoint and its POST/CSRF behaviour are retained.
        self.assertEqual(
            self.client.post(reverse("switch_role"), {"active_role": "employer"}).status_code, 302
        )
        self.assertEqual(
            self.client.post(reverse("switch_role"), {"active_role": "seeker"}).status_code, 302
        )
        self.seeker.refresh_from_db()
        self.assertEqual(self.seeker.photo.name, name)
        self.client.post(reverse("profile_edit"), self.seeker_data(**{"photo-clear": "on"}))
        self.seeker.refresh_from_db()
        self.assertFalse(self.seeker.photo)

    def test_invalid_form_does_not_store_image(self):
        response = self.client.post(
            reverse("profile_edit"), self.company_data(company_name="", logo=upload())
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("company_name", response.context["form"].errors)
        self.assertEqual(list(self.media.rglob("*.png")), [])
        self.company.refresh_from_db()
        self.assertFalse(self.company.logo)

    def test_upload_rejects_non_images_svg_and_truncated_images(self):
        for content in [
            b"not an image",
            b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
            upload().read()[:30],
        ]:
            with self.subTest(content=content[:8]):
                response = self.client.post(
                    reverse("profile_edit"),
                    self.company_data(
                        logo=SimpleUploadedFile("fake.png", content, content_type="image/png")
                    ),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("logo", response.context["form"].errors)
        self.assertEqual(list(self.media.rglob("*.png")), [])

    def test_size_pixel_and_animation_limits(self):
        field = ProfileImageField()
        oversized = SimpleUploadedFile("large.png", b"x" * (5 * 1024 * 1024 + 1))
        with self.assertRaisesMessage(ValidationError, "5 MB"):
            field.clean(oversized)
        with self.assertRaisesMessage(ValidationError, "12 megapixels"):
            field.clean(upload(size=(4000, 3001)))
        stream = BytesIO()
        Image.new("RGB", (8, 8), "red").save(
            stream, format="PNG", save_all=True, append_images=[Image.new("RGB", (8, 8), "blue")]
        )
        with self.assertRaisesMessage(ValidationError, "still image"):
            field.clean(SimpleUploadedFile("animated.png", stream.getvalue()))

    def test_image_reencoding_strips_metadata_and_appended_content(self):
        from PIL.PngImagePlugin import PngInfo

        stream = BytesIO()
        metadata = PngInfo()
        metadata.add_text("private", "location information")
        Image.new("RGB", (16, 16), "green").save(stream, format="PNG", pnginfo=metadata)
        clean = ProfileImageField().clean(
            SimpleUploadedFile("image.png", stream.getvalue() + b"<script>bad()</script>")
        )
        self.assertNotIn(b"<script>", clean.read())
        clean.seek(0)
        with Image.open(clean) as image:
            self.assertNotIn("private", image.info)

    def test_upload_cannot_target_another_profile_and_requires_csrf(self):
        other_user = User.objects.create_user("other_image_owner")
        other = EmployerProfile.objects.create(user=other_user, company_name="Other company")
        self.client.post(
            reverse("profile_edit"),
            self.company_data(logo=upload(), user=other_user.pk, pk=other.pk),
        )
        other.refresh_from_db()
        self.assertFalse(other.logo)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(
            protected.post(reverse("profile_edit"), self.company_data(logo=upload())).status_code,
            403,
        )
        anonymous = Client()
        self.assertEqual(
            anonymous.post(reverse("profile_edit"), self.company_data(logo=upload())).status_code,
            302,
        )
