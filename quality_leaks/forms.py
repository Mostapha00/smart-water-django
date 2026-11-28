from django import forms

from consumption.models import WaterMeter

from .models import AlertRule, LeakIncident, WaterQualityTest

DATETIME = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class WaterQualityTestForm(forms.ModelForm):
    class Meta:
        model = WaterQualityTest
        fields = ("zone", "sampled_at", "laboratory", "ph", "turbidity_ntu", "chlorine_mg_l", "conductivity_us_cm")
        widgets = {"sampled_at": DATETIME}
        labels = {"zone": "Zone", "sampled_at": "Prélevé le", "laboratory": "Laboratoire", "ph": "pH",
                  "turbidity_ntu": "Turbidité (NTU)", "chlorine_mg_l": "Chlore (mg/L)", "conductivity_us_cm": "Conductivité (µS/cm)"}


class AlertRuleForm(forms.ModelForm):
    class Meta:
        model = AlertRule
        fields = "__all__"
        labels = {"name": "Nom", "version_code": "Version", "parameter": "Paramètre", "operator": "Opérateur",
                  "threshold": "Seuil", "unit": "Unité", "severity": "Sévérité",
                  "source_reference": "Référence (norme, source)", "active": "Active"}
        help_texts = {"severity": "« critical » ouvre automatiquement un incident quand une analyse enfreint la règle.",
                      "version_code": "Changer de version quand le seuil change, pour garder la trace des anciens incidents."}


class LeakIncidentForm(forms.ModelForm):
    """Le compteur est choisi dans une liste (le modèle le stocke en relation générique)."""

    meter = forms.ModelChoiceField(label="Compteur", queryset=WaterMeter.objects.select_related("zone"), required=False)

    class Meta:
        model = LeakIncident
        fields = ("trigger_test", "rule", "technician", "suspected_pipe", "suspected_pump", "position_on_pipe", "description")
        labels = {"trigger_test": "Analyse déclencheuse", "rule": "Règle d'alerte", "technician": "Technicien assigné",
                  "suspected_pipe": "Canalisation suspectée", "suspected_pump": "Pompe suspectée",
                  "position_on_pipe": "Position sur la canalisation (0 à 1)", "description": "Description"}
        help_texts = {"position_on_pipe": "Pour la maquette 3D : 0 = début, 0,5 = milieu, 1 = fin de la canalisation."}

    field_order = ["meter", "trigger_test", "rule", "technician", "suspected_pipe", "suspected_pump", "position_on_pipe", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if isinstance(self.instance.meter, WaterMeter):
            self.initial.setdefault("meter", self.instance.meter.pk)

    def clean(self):
        data = super().clean()
        if not data.get("meter") and not data.get("trigger_test"):
            raise forms.ValidationError("Indiquez la source de l'incident : un compteur, une analyse d'eau, ou les deux.")
        if data.get("suspected_pipe") and data.get("suspected_pump"):
            raise forms.ValidationError("Choisissez une canalisation OU une pompe suspectée, pas les deux.")
        return data

    def save(self, commit=True):
        self.instance.meter = self.cleaned_data.get("meter")
        return super().save(commit)
