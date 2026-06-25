from django import forms

from .models import Driver


class DriverForm(forms.ModelForm):
    class Meta:
        model = Driver
        fields = [
            "full_name", "id_number", "phone_e164",
            "licence_code", "licence_expiry",
            "pdp_number", "pdp_expiry",
            "default_vehicle", "is_active", "notes",
        ]
        widgets = {
            "licence_expiry": forms.DateInput(attrs={"type": "date"}),
            "pdp_expiry": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, organisation=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organisation:
            self.fields["default_vehicle"].queryset = organisation.vehicles.filter(is_active=True)
