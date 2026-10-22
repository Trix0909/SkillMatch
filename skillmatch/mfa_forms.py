from django import forms

from .forms import StyledForm


class AuthenticatorCodeForm(StyledForm, forms.Form):
    code = forms.RegexField(
        regex=r"\A[0-9]{6}\Z",
        min_length=6,
        max_length=6,
        label="Authentication code",
        error_messages={"invalid": "Enter the 6-digit code from your authenticator app."},
        widget=forms.TextInput(
            attrs={"autocomplete": "one-time-code", "inputmode": "numeric", "pattern": "[0-9]{6}"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class EnableTwoFactorForm(StyledForm, forms.Form):
    password = forms.CharField(
        label="Current password",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        help_text="Confirm your password before setting up your authenticator app.",
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.style()

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Your password was incorrect. Please try again.")
        return password
