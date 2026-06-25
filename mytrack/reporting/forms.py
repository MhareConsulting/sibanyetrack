from django import forms

from .models import CustomReportDefinition, CustomReportDomain


class CustomReportBuilderForm(forms.ModelForm):
    JSON_LIST_FIELDS = ("columns", "metrics", "group_by", "sort_by")
    JSON_OBJECT_FIELDS = ("filters", "schedule_config")

    class Meta:
        model = CustomReportDefinition
        fields = ["name", "domain", "columns", "metrics", "group_by", "filters", "sort_by", "schedule_config", "is_active"]
        widgets = {
            "columns": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "metrics": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "group_by": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "filters": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
            "sort_by": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "schedule_config": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "domain": forms.Select(attrs={"class": "form-control"}),
        }

    def clean(self):
        cleaned = super().clean()
        domain = cleaned.get("domain")
        if domain not in dict(CustomReportDomain.choices):
            raise forms.ValidationError("Invalid report domain.")
        for field_name in self.JSON_LIST_FIELDS:
            value = cleaned.get(field_name)
            if value is not None and not isinstance(value, list):
                self.add_error(field_name, "Must be a JSON array.")
        for field_name in self.JSON_OBJECT_FIELDS:
            value = cleaned.get(field_name)
            if value is not None and not isinstance(value, dict):
                self.add_error(field_name, "Must be a JSON object.")
        return cleaned
