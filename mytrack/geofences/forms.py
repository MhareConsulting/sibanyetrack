from django import forms
from .models import Geofence


class GeofenceForm(forms.ModelForm):
    class Meta:
        model = Geofence
        fields = ["name", "polygon", "is_active", "enforce_hours", "hours_start", "hours_end", "active_days"]
        widgets = {
            "polygon": forms.HiddenInput(),
            "active_days": forms.HiddenInput(),
        }
