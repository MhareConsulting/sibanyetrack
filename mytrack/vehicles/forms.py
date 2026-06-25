from django import forms

from mytrack.tenancy.models import Depot

from .models import Vehicle, VehicleDepotAssignment


class DepotForm(forms.ModelForm):
    class Meta:
        model = Depot
        fields = ["name", "address", "lat", "lon", "open_time", "close_time"]
        widgets = {
            "open_time": forms.TimeInput(attrs={"type": "time"}),
            "close_time": forms.TimeInput(attrs={"type": "time"}),
        }


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ["registration", "label", "home_depot", "is_active"]

    def __init__(self, *args, organisation=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organisation:
            self.fields["home_depot"].queryset = Depot.objects.filter(
                organisation=organisation, is_active=True
            )
            self.fields["home_depot"].empty_label = "— No depot —"


class VehicleDepotAssignmentForm(forms.ModelForm):
    class Meta:
        model = VehicleDepotAssignment
        fields = ["vehicle", "depot", "kind", "start_date", "end_date", "notes"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.TextInput(),
        }

    def __init__(self, *args, organisation=None, depot=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organisation:
            self.fields["vehicle"].queryset = Vehicle.objects.filter(
                organisation=organisation, is_active=True
            ).order_by("registration")
            self.fields["depot"].queryset = Depot.objects.filter(
                organisation=organisation, is_active=True
            )
        if depot:
            self.fields["depot"].initial = depot
            self.fields["depot"].widget = forms.HiddenInput()
