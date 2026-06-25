from django import forms
from django.contrib.auth import get_user_model

from mytrack.tenancy.models import Organisation

User = get_user_model()


def _licensed_seat_count(org, exclude_user_id=None):
    qs = User.objects.filter(
        organisation=org,
        consumes_license=True,
        is_active=True,
    )
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.count()


class StaffUserEditForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "role",
            "organisation",
            "consumes_license",
            "is_active",
            "is_staff",
        ]
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-control"}),
            "organisation": forms.Select(attrs={"class": "form-control"}),
            "consumes_license": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, can_edit_staff=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not can_edit_staff:
            del self.fields["is_staff"]
        self.fields["organisation"].queryset = Organisation.objects.order_by("name")
        self.fields["organisation"].required = False

    def clean(self):
        cleaned = super().clean()
        org = cleaned.get("organisation")
        consumes = cleaned.get("consumes_license")
        active = cleaned.get("is_active")
        if org and consumes and active:
            exclude = self.instance.pk if self.instance.pk else None
            if _licensed_seat_count(org, exclude_user_id=exclude) >= org.seat_limit:
                raise forms.ValidationError(
                    "That organisation is at its seat limit. "
                    "Turn off “consumes licence”, pick another org, or raise the seat limit on the org."
                )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get("new_password")
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
        return user


class StaffUserCreateForm(forms.ModelForm):
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Password (again)",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )

    class Meta:
        model = User
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "organisation",
            "consumes_license",
            "is_active",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-control"}),
            "organisation": forms.Select(attrs={"class": "form-control"}),
            "consumes_license": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, initial_org=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["organisation"].queryset = Organisation.objects.order_by("name")
        self.fields["organisation"].required = True
        self.fields["is_active"].initial = True
        self.fields["consumes_license"].initial = True
        if initial_org is not None:
            self.fields["organisation"].initial = initial_org.pk

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 != p2:
            raise forms.ValidationError("The two password fields do not match.")
        if not p1:
            raise forms.ValidationError("Password is required.")
        org = cleaned.get("organisation")
        consumes = cleaned.get("consumes_license")
        active = cleaned.get("is_active", True)
        if org and consumes and active and _licensed_seat_count(org) >= org.seat_limit:
            raise forms.ValidationError(
                "That organisation is at its seat limit. Uncheck “consumes licence” or raise the limit."
            )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
