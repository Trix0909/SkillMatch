import json
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from .models import Account, JobSeekerProfile, EmployerProfile, JobPost, Skill, EvidenceLink, normalize_skill


def parse_skills(value):
    try:
        values = json.loads(value)
    except (ValueError, TypeError):
        raise ValidationError('Add skills individually using Add skill.')
    if not isinstance(values, list) or not 1 <= len(values) <= 40:
        raise ValidationError('Add between 1 and 40 skills.')
    clean, seen = [], set()
    for name in values:
        if not isinstance(name, str):
            raise ValidationError('Each skill must be text.')
        name = normalize_skill(name)
        if not name or len(name) > 80:
            raise ValidationError('Each skill must contain 1–80 characters.')
        if name.casefold() in seen:
            raise ValidationError(f'“{name}” is already in your skills. Remove the duplicate.')
        seen.add(name.casefold())
        clean.append(name)
    return clean


class StyledForm:
    def style(self):
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            if isinstance(field.widget, forms.Textarea):
                if field.widget.attrs.get('rows', 10) == 10:
                    field.widget.attrs['rows'] = 4


class RegistrationForm(StyledForm, UserCreationForm):
    first_name = forms.CharField(max_length=150, label='First name')
    last_name = forms.CharField(max_length=150, label='Last name')
    email = forms.EmailField()
    role = forms.ChoiceField(choices=[('seeker', 'I’m looking for work'), ('employer', 'I’m hiring')])
    company_name = forms.CharField(max_length=150, required=False, label='Company name (employers)')

    class Meta(UserCreationForm.Meta):
        fields = ['first_name', 'last_name', 'username', 'email', 'role', 'company_name', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()

    def clean_username(self):
        username = super().clean_username()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already taken.')
        return username

    def clean(self):
        data = super().clean()
        if data.get('role') == 'employer' and not data.get('company_name', '').strip():
            self.add_error('company_name', 'Enter your company name.')
        return data

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=True)
        Account.objects.create(user=user, role=self.cleaned_data['role'])
        if self.cleaned_data['role'] == 'seeker':
            JobSeekerProfile.objects.create(user=user)
        else:
            EmployerProfile.objects.create(user=user, company_name=self.cleaned_data['company_name'])
        return user


class LoginForm(StyledForm, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class ProfileForm(StyledForm, forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    skills_json = forms.CharField(widget=forms.HiddenInput, label='Skills')
    links = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}), label='Supporting evidence links', help_text='One http:// or https:// link per line. Optional, up to 8 links.')

    class Meta:
        model = JobSeekerProfile
        fields = ['first_name', 'last_name', 'skills_json', 'certification_level', 'experience_level', 'bio', 'portfolio', 'links']
        labels = {'bio': 'Professional summary', 'portfolio': 'Project portfolio'}
        help_texts = {'bio': 'Describe your professional background (up to 2,000 characters).',
                      'portfolio': 'Describe the work you have done and the skills you used (up to 6,000 characters).'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bio'].required = True
        self.fields['portfolio'].required = True
        if self.instance.pk:
            self.initial.update(first_name=self.instance.user.first_name, last_name=self.instance.user.last_name,
                                skills_json=json.dumps([s.name for s in self.instance.skills.all()]),
                                links='\n'.join(e.url for e in self.instance.evidence_links.all()))
        self.style()

    def clean_skills_json(self):
        return parse_skills(self.cleaned_data['skills_json'])

    def clean_links(self):
        urls = list(dict.fromkeys(u.strip() for u in self.cleaned_data['links'].splitlines() if u.strip()))
        if len(urls) > 8:
            raise ValidationError('Use at most 8 evidence links.')
        for url in urls:
            if len(url) > 500:
                raise ValidationError('Each link must be at most 500 characters.')
            URLValidator(schemes=['http', 'https'])(url)
        return urls

    @transaction.atomic
    def save(self, commit=True):
        profile = super().save(commit=True)
        profile.user.first_name = self.cleaned_data['first_name']
        profile.user.last_name = self.cleaned_data['last_name']
        profile.user.save(update_fields=['first_name', 'last_name'])
        names = self.cleaned_data['skills_json']
        normalized = [n.casefold() for n in names]
        profile.skills.exclude(normalized_name__in=normalized).delete()
        for name in names:
            Skill.objects.update_or_create(profile=profile, normalized_name=name.casefold(), defaults={'name': name})
        profile.evidence_links.all().delete()
        EvidenceLink.objects.bulk_create([EvidenceLink(profile=profile, url=u) for u in self.cleaned_data['links']])
        return profile


class EmployerForm(StyledForm, forms.ModelForm):
    class Meta:
        model = EmployerProfile
        fields = ['company_name', 'description']
        labels = {'description': 'About your company'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()


class JobForm(StyledForm, forms.ModelForm):
    skills_json = forms.CharField(widget=forms.HiddenInput, label='Required skills')

    class Meta:
        model = JobPost
        fields = ['title', 'description', 'skills_json', 'certification_level', 'experience_level']
        labels = {'certification_level': 'Minimum certification level', 'experience_level': 'Minimum experience level'}
        help_texts = {'description': 'Describe the role, responsibilities and skills needed (up to 8,000 characters).'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['skills_json'] = json.dumps(self.instance.required_skills or [])
        self.style()

    def clean_skills_json(self):
        skills = parse_skills(self.cleaned_data['skills_json'])
        self.instance.required_skills = skills
        return skills

    def _update_errors(self, errors):
        # Map model validation back to the structured tag field on this form.
        if hasattr(errors, 'error_dict') and 'required_skills' in errors.error_dict:
            errors.error_dict['skills_json'] = errors.error_dict.pop('required_skills')
        super()._update_errors(errors)

    def save(self, commit=True):
        self.instance.required_skills = self.cleaned_data['skills_json']
        return super().save(commit)


class SearchForm(StyledForm, forms.Form):
    q = forms.CharField(max_length=8000, label='Job description or skill keywords', widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Describe the skills and work you need…'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style()
