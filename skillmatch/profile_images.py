"""Validated, normalized raster uploads for profile presentation."""

from io import BytesIO
from uuid import uuid4

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError


def profile_image_path(instance, filename):
    # Never retain client filenames, paths or executable extensions.
    return f"profiles/{instance._meta.model_name}/{instance.user_id}/{uuid4().hex}.png"


class ProfileImageInput(forms.ClearableFileInput):
    template_name = "skillmatch/widgets/profile_image.html"


class ProfileImageField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "help_text",
            "JPG, PNG or WebP. Maximum 5 MB and 12 megapixels. Changes apply when you save.",
        )
        kwargs.setdefault(
            "widget", ProfileImageInput(attrs={"accept": "image/jpeg,image/png,image/webp"})
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        value = super().clean(data, initial)
        if not data or not value:
            return value
        if value.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Choose an image smaller than 5 MB.")
        try:
            value.seek(0)
            with Image.open(value) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise forms.ValidationError("Choose a JPG, PNG or WebP image.")
                if image.width * image.height > 12_000_000:
                    raise forms.ValidationError("Choose an image with no more than 12 megapixels.")
                if getattr(image, "is_animated", False):
                    raise forms.ValidationError("Choose a still image, not an animation.")
                image.load()
                image = ImageOps.exif_transpose(image).convert("RGBA")
                image.thumbnail((2400, 2400))
                # Re-encode pixels only: remove metadata and any appended content.
                clean = Image.new("RGBA", image.size)
                clean.paste(image)
                output = BytesIO()
                clean.save(output, format="PNG")
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise forms.ValidationError("Upload a valid JPG, PNG or WebP image.") from exc
        return SimpleUploadedFile("image.png", output.getvalue(), content_type="image/png")
