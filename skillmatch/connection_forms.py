from datetime import timedelta
from uuid import uuid4

from django import forms
from django.conf import settings
from django.core import signing
from django.utils import timezone

from .forms import StyledForm
from .models import Connection
from .recruitment import stage_snapshot

CONSENT = "Acceptance shares the seeker's account email and optional phone with this employer, and the employer's account email with the seeker. Accepted contact access remains if a job closes or consideration ends; withdrawal revokes that connection's access."


class IntroductionForm(StyledForm, forms.Form):
    note = forms.CharField(
        required=False,
        max_length=500,
        strip=True,
        label="Introduction (optional)",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class InvitationForm(IntroductionForm):
    job = forms.ModelChoiceField(queryset=None, empty_label="Choose one of your active jobs")

    def __init__(self, *args, jobs, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["job"].queryset = jobs
        self.style()


class MessageBodyForm(StyledForm, forms.Form):
    body = forms.CharField(
        max_length=2000,
        strip=True,
        label="Message",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Write a message…"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class MessageForm(MessageBodyForm):
    submission_key = forms.UUIDField(initial=uuid4, widget=forms.HiddenInput)


class UnsendForm(forms.Form):
    confirm = forms.BooleanField(required=True, widget=forms.HiddenInput)


class StageForm(StyledForm, forms.Form):
    stage = forms.ChoiceField(choices=Connection.STAGES, widget=forms.HiddenInput)
    expected_state = forms.CharField(required=False, widget=forms.HiddenInput)
    confirm_not_selected = forms.BooleanField(required=False, widget=forms.HiddenInput)
    interview_at = forms.DateTimeField(
        required=False,
        label=f"Interview date and time ({settings.TIME_ZONE})",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    def __init__(self, *args, choices=None, connection=None, **kwargs):
        super().__init__(*args, **kwargs)
        if choices is not None:
            self.fields["stage"].choices = choices
        if connection is not None:
            self.fields["expected_state"].required = True
            self.initial["expected_state"] = signing.dumps(
                stage_snapshot(connection), salt="skillmatch.recruitment-progress"
            )
            if connection.interview_at:
                self.initial["interview_at"] = connection.interview_at
        self.fields["interview_at"].widget.attrs["min"] = (
            timezone.localtime(timezone.now()) + timedelta(minutes=1)
        ).strftime("%Y-%m-%dT%H:%M")
        self.fields["interview_at"].widget.attrs["required"] = True
        self.style()

    def clean_expected_state(self):
        token = self.cleaned_data["expected_state"]
        if not token:
            return None
        try:
            snapshot = signing.loads(token, salt="skillmatch.recruitment-progress")
        except signing.BadSignature as error:
            raise forms.ValidationError("Reload the connection and try again.") from error
        if not isinstance(snapshot, dict):
            raise forms.ValidationError("Reload the connection and try again.")
        return snapshot

    def clean(self):
        data = super().clean()
        if data.get("stage") == "interview":
            date = data.get("interview_at")
            if not date:
                if "interview_at" not in self.errors:
                    self.add_error("interview_at", "Choose an interview date and time.")
            elif date <= timezone.now():
                self.add_error("interview_at", "Choose a future interview date and time.")
        else:
            # A historical interview is not an input to shortlisting/offering/ending consideration.
            data["interview_at"] = None
        if data.get("stage") == "not_selected" and not data.get("confirm_not_selected"):
            self.add_error(
                "confirm_not_selected", "Confirm not selected before ending consideration."
            )
        return data
