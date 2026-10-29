from django import forms
from .models import ConservationTarget, SustainabilityProject, MeasuredBenefit, OptimizationRun


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ConservationTargetForm(StyledModelForm):
    class Meta:
        model = ConservationTarget
        fields = "__all__"
        widgets = {"period_start": forms.DateInput(attrs={"type": "date"}), "period_end": forms.DateInput(attrs={"type": "date"})}


class SustainabilityProjectForm(StyledModelForm):
    class Meta:
        model = SustainabilityProject
        fields = "__all__"
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "completion_date": forms.DateInput(attrs={"type": "date"})}


class MeasuredBenefitForm(StyledModelForm):
    class Meta:
        model = MeasuredBenefit
        fields = "__all__"
        widgets = {"period_start": forms.DateInput(attrs={"type": "date"}), "period_end": forms.DateInput(attrs={"type": "date"})}


class OptimizationRunForm(StyledModelForm):
    class Meta:
        model = OptimizationRun
        fields = ("site", "budget_tnd", "objective")
