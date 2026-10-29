from django import forms

from .models import AlertRule, LeakIncident, WaterQualityTest


class WaterQualityTestForm(forms.ModelForm):
    class Meta:
        model = WaterQualityTest
        fields = ("zone", "sampled_at", "laboratory", "ph", "turbidity_ntu", "chlorine_mg_l", "conductivity_us_cm")
        widgets = {"sampled_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = "__all__"


class LeakIncidentForm(forms.ModelForm):
    class Meta:
        model = LeakIncident
        fields = ("meter_content_type", "meter_object_id", "trigger_test", "rule", "technician", "suspected_pipe", "suspected_pump", "position_on_pipe", "description")
